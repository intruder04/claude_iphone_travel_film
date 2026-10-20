"""Check a finished film is a valid HLG HDR upload for YouTube: HEVC Main10 (or 10-bit), BT.2020 primaries,
ARIB STD-B67 transfer in BOTH the bitstream VUI and the container colr atom, plus duration and loudness.
Usage: verify.py FILM.mov"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import FF, FFPROBE

def main(f):
    ok = True
    p = json.loads(subprocess.run([FFPROBE, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', f],
                                  capture_output=True, text=True).stdout)
    v = [s for s in p['streams'] if s['codec_type'] == 'video'][0]
    a = [s for s in p['streams'] if s['codec_type'] == 'audio']
    def chk(name, cond, val):
        nonlocal ok; ok &= bool(cond); print(f"  {'✓' if cond else '✗'} {name}: {val}")
    print(f'{f}')
    chk('codec', v['codec_name'] == 'hevc' and v.get('pix_fmt', '').endswith('10le'), f"{v['codec_name']} {v.get('profile')} {v.get('pix_fmt')}")
    chk('resolution / fps', True, f"{v['width']}x{v['height']} @ {v['r_frame_rate']}")
    lvl = int(v.get('level', 0)); chk('HEVC level ≤ 5.2 (YouTube 4K/HDR path)', 0 < lvl <= 156, f'{lvl / 30:.1f}')
    pk = subprocess.run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-read_intervals', '%+60', '-show_entries', 'packet=flags',
                         '-of', 'csv=p=0', f], capture_output=True, text=True).stdout.split()
    kf = sum('K' in x for x in pk); chk('keyframe interval ≥ 1 s', kf <= 61, f'{kf} keyframes in the first 60 s')
    chk('container primaries', v.get('color_primaries') == 'bt2020', v.get('color_primaries'))
    chk('container transfer (HLG)', v.get('color_transfer') == 'arib-std-b67', v.get('color_transfer'))
    chk('container matrix', v.get('color_space') == 'bt2020nc', v.get('color_space'))
    tr = subprocess.run([FF, '-v', 'trace', '-i', f, '-c', 'copy', '-bsf:v', 'trace_headers', '-frames:v', '1', '-f', 'null', '-'],
                        capture_output=True, text=True).stderr
    vui = {k: int(m.group(1)) for k in ('colour_primaries', 'transfer_characteristics', 'matrix_coefficients')
           for m in [re.search(k + r'\s+\d+\s+=\s+(\d+)', tr)] if m}
    chk('bitstream VUI 9/18/9', vui == {'colour_primaries': 9, 'transfer_characteristics': 18, 'matrix_coefficients': 9}, vui)
    chk('audio', a and a[0]['codec_name'] == 'aac', f"{a[0]['codec_name']} {a[0].get('sample_rate')} Hz {a[0].get('channels')} ch" if a else 'none')
    d = float(p['format']['duration']); chk('duration', True, f'{d // 60:.0f} min {d % 60:.0f} s, {int(p["format"]["bit_rate"]) / 1e6:.0f} Mb/s')
    lo = subprocess.run([FF, '-hide_banner', '-i', f, '-vn', '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', lo); chk('loudness (YouTube ≈ -14 LUFS)', m and -16.5 < float(m[-1]) < -12, f'{m[-1]} LUFS' if m else '?')
    print('READY for YouTube HDR upload' if ok else 'NOT ready — see ✗ above')
    return ok

if __name__ == '__main__':
    sys.exit(0 if main(sys.argv[1]) else 1)
