"""Render one edit segment: source clip range -> 3840x2160 60p HLG HEVC 10-bit.

Memory-safe two-stage design (tested on a 16 GB Mac):
  1. Overlay graphics (if any) are rendered frame-by-frame in Python and streamed into a separate
     ffmpeg that compresses them with the hardware ProRes 4444 engine (alpha kept). Pipe back-pressure bounds memory.
  2. A second ffmpeg composites source + overlay file. Both inputs are files, so ffmpeg's scheduler
     reads them on demand and never queues unbounded decoded 4K frames.
Every ffmpeg runs under a watchdog that kills it if its RSS exceeds MEM_LIMIT_GB.
Decode/encode use the M4 media engines (VideoToolbox). Benchmarks on this Mac (4K60 10-bit HLG):
  1 encode session ~1x real-time; -prio_speed 1 ~1.6x (same SSIM); 2 sessions in parallel ~3x total.
  CPU filters (fps/scale/fade/overlay) cost ~0 extra wall time because the encoder is the bottleneck."""
import os, subprocess, sys, threading, time, tempfile
import psutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import FF, FFPROBE, ENV, VK, DEC, SRC, src, P, HLG_TAGS, sdr_gpu
from gfx import W, H, blank

TMP = P('tmp')
FPS = 60
MEM_LIMIT_GB = float(os.environ.get('MEM_LIMIT_GB', 5))

def _watch(p, label):
    """Kill the process tree if it grows past the memory limit."""
    try: pp = psutil.Process(p.pid)
    except psutil.NoSuchProcess: return
    while p.poll() is None:
        try:
            rss = sum(c.memory_info().rss for c in [pp, *pp.children(recursive=True)])
        except psutil.Error: break
        if rss > MEM_LIMIT_GB * 1e9:
            sys.stderr.write(f'[watchdog] {label}: {rss/1e9:.1f} GB > {MEM_LIMIT_GB} GB, killing\n'); p.kill(); break
        time.sleep(0.5)

def run(cmd, label, stdin=None):
    p = subprocess.Popen(cmd, stdin=stdin, env=ENV)
    threading.Thread(target=_watch, args=(p, label), daemon=True).start()
    return p

def video_chain(portrait, hdr, rot=0.0):
    norm = '' if hdr else ',zscale=tin=bt709:t=arib-std-b67:pin=bt709:p=bt2020:min=bt709:m=bt2020nc:npl=203'
    if not portrait:
        if rot:
            # level the horizon: upscale just enough that the rotated frame still fills 16:9, rotate, centre-crop
            import math
            a = math.radians(abs(rot)); k = math.cos(a) + (W / H) * math.sin(a)
            sw, sh = int(W * k / 2) * 2, int(H * k / 2) * 2
            return (f'[0:v]fps={FPS},scale={sw}:{sh}:flags=lanczos,format=yuv420p10le{norm},'
                    f'rotate={math.radians(rot):.6f}:ow={W}:oh={H}:bilinear=1[v]')
        return f'[0:v]fps={FPS},scale={W}:{H}:flags=lanczos,format=yuv420p10le{norm}[v]'
    # vertical clip: sharp centre + blurred, darkened fill (no black bars)
    return (f'[0:v]fps={FPS},format=yuv420p10le{norm},split[a][b];'
            f'[a]scale=480:270:force_original_aspect_ratio=increase,crop=480:270,gblur=sigma=10,scale={W}:{H},eq=brightness=-0.08[bg];'
            f'[b]scale=-2:{H}:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:0,format=yuv420p10le[v]')

def render_overlay(fn, t0, t1, out):
    """Stage 1: stream RGBA frames for [t0,t1) into a compressed alpha MOV."""
    n = int(round((t1 - t0) * FPS)); empty = None
    p = run([FF, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
             '-vf', 'format=bgra', '-c:v', 'prores_videotoolbox', '-profile:v', '4444', out], 'overlay-encode', stdin=subprocess.PIPE)
    for i in range(n):
        im = fn(t0 + i / FPS)
        if im is None:
            if empty is None: empty = blank().tobytes()
            b = empty
        else:
            b = im.tobytes()
        try: p.stdin.write(b)
        except BrokenPipeError: break
    p.stdin.close()
    if p.wait() != 0: raise RuntimeError('overlay encode failed')
    return out

def render(seg, out, overlay_fn=None, ov_range=None, bitrate='60M'):
    """seg: dict(file, ss, dur, portrait, hdr, fade_in, fade_out, audio, volume)."""
    ss, dur = seg['ss'], seg['dur']; n = int(round(dur * FPS))
    fc = video_chain(seg['portrait'], seg['hdr'], seg.get('rotate', 0.0))
    # video and audio come from two separate demuxers of the same file: with one shared demuxer ffmpeg keeps
    # decoding 4K video ahead to feed the (fast) audio path and buffers GBs of frames while the overlay waits
    vsrc = ['-i', seg['source']] if seg.get('source') else src(seg['file'])     # e.g. pre-rendered callout clip
    inputs = [*DEC, '-ss', f'{ss:.3f}', '-t', f'{dur:.3f}', '-an', *vsrc]
    ov = None; last = 'v'
    if overlay_fn:
        t0, t1 = ov_range or (0, dur)
        ov = tempfile.mktemp(suffix='.mov', dir=TMP)
        render_overlay(overlay_fn, t0, t1, ov)
        inputs += ['-i', ov]
        fc += (f';[1:v]setpts=PTS-STARTPTS+{t0}/TB,format=rgba,scale=out_color_matrix=bt2020nc:out_range=tv,format=yuva444p10le[g];'
               f'[v][g]overlay=format=yuv420p10:eof_action=pass:repeatlast=0[v2]')
        last = 'v2'
    fi, fo = seg.get('fade_in', 0), seg.get('fade_out', 0)
    post = []
    if fi: post.append(f'fade=t=in:st=0:d={fi}')
    if fo: post.append(f'fade=t=out:st={dur - fo:.3f}:d={fo}')
    post.append('setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc:range=tv')
    fc += f';[{last}]' + ','.join(post) + '[vo]'
    # audio: real fades only where the picture fades (film start/end, city changes); every other cut gets a 15 ms
    # de-click so the waveform doesn't jump — long fades on every cut make the sound dip audibly at each shot change
    DECLICK = 0.015
    afi, afo = (fi if fi else DECLICK), (fo if fo else DECLICK)
    af = [f'afade=t=in:st=0:d={afi}:curve=qsin', f'afade=t=out:st={dur - afo:.3f}:d={afo}:curve=qsin']
    if seg.get('volume', 1.0) != 1.0: af.append(f"volume={seg['volume']}")
    ai = 2 if ov else 1
    if seg.get('audio', True): inputs += ['-vn', '-ss', f'{ss:.3f}', '-t', f'{dur:.3f}', '-i', os.path.join(SRC, seg['file'])]
    cmd = [FF, '-v', 'error', '-y', *inputs, '-filter_complex', fc, '-map', '[vo]', '-frames:v', str(n)]
    if seg.get('audio', True):
        cmd += ['-map', f'{ai}:a:0', '-af', ','.join(af) + ',aresample=48000,apad', '-ac', '2', '-t', f'{dur:.3f}', '-c:a', 'pcm_s16le']
    # YouTube: keep the stream at a common HEVC level (5.1/5.2). VideoToolbox's default short GOP + 120 Mb/s peaks give
    # level 6.1, which YouTube accepted but never turned into 4K/HDR. 2 s GOP + ≤80 Mb/s peaks → level 5.2.
    cmd += ['-c:v', 'hevc_videotoolbox', '-prio_speed', '1', '-profile:v', 'main10', '-pix_fmt', 'p010le', '-b:v', bitrate, '-maxrate', '80M', '-g', str(FPS * 2),
            '-tag:v', 'hvc1', *HLG_TAGS, '-r', str(FPS), out]
    rc = run(cmd, 'compose ' + os.path.basename(out)).wait()
    if ov: os.remove(ov)
    if rc != 0: raise RuntimeError(f'ffmpeg failed for {out}')
    return out

def preview(src, out, width=1920):
    """SDR H.264 preview (GPU tone-map) for quick viewing anywhere, with a % progress bar."""
    from tqdm import tqdm
    dur = float(subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src],
                               capture_output=True, text=True).stdout or 0)
    p = subprocess.Popen([FF, '-v', 'error', '-y', *VK, *DEC, '-i', src, '-vf', sdr_gpu(width, width * 9 // 16),
                          '-c:v', 'h264_videotoolbox', '-b:v', '12M', '-c:a', 'aac', '-b:a', '192k', '-progress', 'pipe:1', '-nostats', out],
                         stdout=subprocess.PIPE, text=True, env=ENV)
    threading.Thread(target=_watch, args=(p, 'preview'), daemon=True).start()
    with tqdm(total=round(dur), desc='SDR preview', unit='s') as bar:
        for line in p.stdout:
            if line.startswith('out_time_us=') and line.strip()[12:].isdigit():
                bar.update(min(round(dur), int(line.strip()[12:]) // 1_000_000) - bar.n)
    if p.wait() != 0: raise RuntimeError('preview failed')
    return out
