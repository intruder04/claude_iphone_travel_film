"""Shared settings, paths and hardware helpers for every script.

A project is one folder (WORK) containing project.json (see templates/project.json).
WORK = $TRAVEL_FILM_WORK, or the current directory. Source videos are only ever read, never written.

Hardware notes (Apple Silicon, measured on M4 16 GB with 4K60 10-bit HLG):
  * decode/encode on the media engines via VideoToolbox (-hwaccel videotoolbox, hevc_videotoolbox)
  * hevc_videotoolbox -prio_speed 1 is ~1.6x faster than default at the same SSIM
  * 2 parallel encode sessions ~= the encoder's ceiling; a 3rd/4th adds RAM but no speed
  * GPU tone-mapping (HLG -> SDR previews) via libplacebo on Vulkan/MoltenVK
"""
import json, os, sys, shutil, subprocess

WORK = os.path.abspath(os.environ.get('TRAVEL_FILM_WORK', os.getcwd()))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(SCRIPTS)

def _load_cfg():
    p = os.path.join(WORK, 'project.json')
    if not os.path.exists(p):
        sys.exit(f'project.json not found in {WORK}. Create one from templates/project.json, '
                 f'then run from that folder or set TRAVEL_FILM_WORK.')
    return json.load(open(p))

CFG = _load_cfg()
SRC = os.path.abspath(os.path.expanduser(CFG['source_dir']))
LANG = CFG.get('local_language', '')
# clips whose rotation tag is wrong (phone thought it was vertical while filming horizontally) — decoded as stored
NOROT = set(CFG.get('ignore_rotation_tag', []))          # ISO code of the local script shown in titles, '' = none
for _d in ('meta', 'meta/probe', 'meta/metrics', 'meta/clip', 'frames', 'landmarks', 'review',
           'renders', 'renders/shots', 'previews', 'tmp'):
    os.makedirs(os.path.join(WORK, _d), exist_ok=True)

def P(*parts):
    """Path inside the project folder."""
    return os.path.join(WORK, *parts)

def jload(name, default=None):
    p = P(name)
    if not os.path.exists(p):
        if default is not None: return default
        sys.exit(f'{name} is missing — run the earlier pipeline step first')
    return json.load(open(p))

def jsave(name, obj, indent=1):
    json.dump(obj, open(P(name), 'w'), indent=indent, ensure_ascii=False)

# ---------------------------------------------------------------- ffmpeg / hardware
def _brew_prefix(formula):
    try: return subprocess.run(['brew', '--prefix', formula], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError: return ''

_full = _brew_prefix('ffmpeg-full')
FF = os.path.join(_full, 'bin', 'ffmpeg') if _full and os.path.exists(os.path.join(_full, 'bin', 'ffmpeg')) else shutil.which('ffmpeg')
FFPROBE = os.path.join(_full, 'bin', 'ffprobe') if _full and os.path.exists(os.path.join(_full, 'bin', 'ffprobe')) else shutil.which('ffprobe')
_mvk = _brew_prefix('molten-vk')
ENV = dict(os.environ, VK_ICD_FILENAMES=os.path.join(_mvk, 'etc/vulkan/icd.d/MoltenVK_icd.json') if _mvk else '',
           DYLD_FALLBACK_LIBRARY_PATH='/opt/homebrew/lib')
VK = ['-init_hw_device', 'vulkan=vk', '-filter_hw_device', 'vk']
DEC = ['-hwaccel', 'videotoolbox']
HLG_TAGS = ['-color_primaries', 'bt2020', '-color_trc', 'arib-std-b67', '-colorspace', 'bt2020nc', '-color_range', 'tv']
# CPU tone-map (works everywhere; used for small analysis frames)
TONEMAP_CPU = ("zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
               "zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")

def sdr_gpu(w, h):
    """GPU tone-map HLG -> SDR BT.709 + scale (libplacebo on Vulkan). CPU frames in/out."""
    return ("setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc:range=tv,format=p010le,hwupload,"
            f"libplacebo=w={w}:h={h}:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
            "tonemapping=bt.2390:peak_detect=false:format=yuv420p,hwdownload,format=yuv420p")

def src(clip):
    """ffmpeg input args for a source clip (honours ignore_rotation_tag)."""
    return (['-noautorotate'] if clip in NOROT else []) + ['-i', os.path.join(SRC, clip)]

def probe(clip):
    """Cached ffprobe JSON of a source clip."""
    p = P('meta/probe', clip + '.json')
    if not os.path.exists(p):
        out = subprocess.run([FFPROBE, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams',
                              os.path.join(SRC, clip)], capture_output=True, text=True).stdout
        open(p, 'w').write(out)
    return json.load(open(p))

def fps_of(clip):
    v = [s for s in probe(clip)['streams'] if s['codec_type'] == 'video'][0]
    a, b = map(int, v['r_frame_rate'].split('/')); return a / b

def grab(clip, t, w=1920, h=1080, sdr=True):
    """One frame of a source clip as a PIL image (SDR tone-mapped by default)."""
    from PIL import Image
    dur = float(probe(clip)['format']['duration']); t = max(0.0, min(t, dur - 0.15))
    vf = f'scale={w}:{h}' + (',' + TONEMAP_CPU if sdr else '')
    raw = subprocess.run([FF, '-v', 'error', '-ss', f'{t:.3f}', *src(clip), '-frames:v', '1',
                          '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    if len(raw) < w * h * 3:              # e.g. SDR source: tone-map not applicable → plain scale
        raw = subprocess.run([FF, '-v', 'error', '-ss', f'{t:.3f}', *src(clip), '-frames:v', '1', '-vf', f'scale={w}:{h}',
                              '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    return Image.frombytes('RGB', (w, h), raw[:w * h * 3]) if len(raw) >= w * h * 3 else Image.new('RGB', (w, h))

# A finished film over ~1 hour is better as several videos: locations.json segments carry "part": N, and every
# film-level step (render_all, subtitles srt, youtube_meta) works on one part when TRAVEL_FILM_PART=N is set.
PART = int(os.environ['TRAVEL_FILM_PART']) if os.environ.get('TRAVEL_FILM_PART') else None

def part_suffix():
    return f'_Part{PART}' if PART else ''

def edl_shots(part=PART):
    """Shots of the current edit (sub-2 s flash cuts dropped), only those of `part` when the film is split."""
    E = jload('meta/edl.json'); seg_part = {s['id']: s.get('part') for s in E['segments']}
    return E, [e for e in E['edl'] if e['dur'] >= 2.0 and (part is None or seg_part.get(e['seg']) == part)]
