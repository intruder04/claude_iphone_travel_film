"""Step 8a — horizon / tilt check.   horizon.py measure | sheet | fix SHOT [SHOT ...]
 Estimate camera roll for every shot in the edit: line segments (LSD) on the analysis frames inside
the shot window; roll = length-weighted median deviation of near-vertical lines from 90° (buildings, poles)
and of long near-horizontal lines from 0° (sea/water horizons). Flags |roll| > THRESH for visual review."""
import json, glob, os, sys, numpy as np, cv2
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK as W, P, edl_shots
THRESH = float(os.environ.get('THRESH', 1.8))
def roll(path):
    g = cv2.imread(path, 0)
    if g is None: return None
    lsd = cv2.createLineSegmentDetector(); lines = lsd.detect(g)[0]
    if lines is None: return None
    v, vw, h, hw = [], [], [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        L = np.hypot(x2 - x1, y2 - y1)
        if L < g.shape[0] * 0.08: continue
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        if 70 < a < 110: v.append(a - 90); vw.append(L)
        elif (a < 12 or a > 168) and L > g.shape[1] * 0.25: h.append(a if a < 90 else a - 180); hw.append(L)
    def wmed(x, w):
        if len(x) < 3: return None, 0
        o = np.argsort(x); x, w = np.array(x)[o], np.array(w)[o]; c = np.cumsum(w)
        return float(x[np.searchsorted(c, c[-1] / 2)]), float(c[-1])
    rv, wv = wmed(v, vw); rh, wh = wmed(h, hw)
    return rv, wv, rh, wh
def shot(args):
    i, e = args
    fs = sorted(glob.glob(f"{W}/frames/{e['file']}/*.jpg"))
    a, b = int(e['ss'] * 2), int((e['ss'] + e['dur']) * 2)
    rs = [roll(f) for f in fs[a:b + 1][::2]]
    rv = [r[0] for r in rs if r and r[0] is not None and r[1] > 300]
    rh = [r[2] for r in rs if r and r[2] is not None and r[3] > 400]
    est = float(np.median(rv)) if len(rv) >= 2 else (float(np.median(rh)) if len(rh) >= 2 else None)
    src = 'verticals' if len(rv) >= 2 else ('horizon' if len(rh) >= 2 else '-')
    return i, e['file'], est, src, float(np.std(rv)) if len(rv) >= 2 else None
def sheet(min_abs=3.0):
    """review/tilt_N.jpg — flagged shots with a level grid, for Claude to judge by eye. Low-angle shots of tall
    things (gates, bamboo, towers) show converging verticals, not roll: do NOT 'fix' those."""
    from PIL import Image, ImageDraw
    from sheets import _font
    H = json.load(open(P('meta/horizon.json'))); E, edl = edl_shots(); F = _font(22); CW, CH = 768, 432
    ids = [int(i) for i, v in sorted(H.items(), key=lambda kv: -abs(kv[1]['roll'] or 0)) if v['roll'] is not None and abs(v['roll']) > min_abs]
    for s in range(0, len(ids), 8):
        S = Image.new('RGB', (CW * 2, CH * 4))
        for k, i in enumerate(ids[s:s + 8]):
            e = edl[i]; fs = sorted(glob.glob(P('frames', e['file'], '*.jpg'))); f = fs[min(len(fs) - 1, int((e['ss'] + e['dur'] / 2) * 2))]
            im = Image.open(f).resize((CW, CH)); d = ImageDraw.Draw(im)
            for x in range(0, CW, 64): d.line((x, 0, x, CH), fill=(255, 255, 0))
            for y in range(0, CH, 54): d.line((0, y, CW, y), fill=(255, 255, 0))
            d.rectangle((0, 0, 260, 30), fill=0); d.text((4, 3), f"shot {i}  {H[str(i)]['roll']:+.1f}°", font=F, fill=(255, 80, 80))
            S.paste(im, ((k % 2) * CW, (k // 2) * CH))
        S.save(P('review', f'tilt_{s // 8}.jpg'), quality=85)
    print(f'{len(ids)} shots on review/tilt_*.jpg')

def fixes(shots):
    """Write meta/rotate.json for the shots Claude confirmed as tilted. Tries both directions on the analysis frame
    and keeps the one that levels it; capped at ±6° (each degree costs ~3 % crop)."""
    from PIL import Image
    H = json.load(open(P('meta/horizon.json'))); E, edl = edl_shots(); out = {}
    for i in shots:
        e = edl[i]; r = H[str(i)]['roll']; fs = sorted(glob.glob(P('frames', e['file'], '*.jpg')))
        im = Image.open(fs[min(len(fs) - 1, int((e['ss'] + e['dur'] / 2) * 2))]); res = {}
        for sgn in (1, -1):
            im.rotate(sgn * r, resample=Image.BICUBIC).save(P('tmp', 'rot.jpg')); m = roll(P('tmp', 'rot.jpg'))
            res[sgn] = m[0] if m and m[0] is not None else 99
        sgn = min(res, key=lambda k: abs(res[k])); out[str(i)] = round(float(np.clip(sgn * r, -6, 6)), 2)
        print(f"shot {i} {e['file']}: measured {r:+.1f}°, correction {out[str(i)]:+.1f}°, residual {res[sgn]:+.1f}°")
    json.dump(out, open(P('meta/rotate.json'), 'w'), indent=1)

def measure():
    E, edl = edl_shots()
    with ProcessPoolExecutor(os.cpu_count()) as ex: res = list(ex.map(shot, enumerate(edl)))
    out = {str(i): dict(file=f, roll=r, src=s, spread=sp) for i, f, r, s, sp in res}
    json.dump(out, open(f'{W}/meta/horizon.json', 'w'), indent=1)
    flagged = [(i, f, r, s, sp) for i, f, r, s, sp in res if r is not None and abs(r) > THRESH]
    print(f'{len(res)} shots measured, {sum(r is None for _, _, r, _, _ in res)} without usable lines, {len(flagged)} flagged > {THRESH}°')
    for i, f, r, s, sp in sorted(flagged, key=lambda x: -abs(x[2])): print(f'  shot {i:3d} {f} roll {r:+.1f}° ({s}, spread {sp if sp is None else round(sp,1)})')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'measure'
    if cmd == 'measure': measure()          # meta/horizon.json + list of candidates
    elif cmd == 'sheet': sheet()            # review/tilt_*.jpg for visual confirmation
    elif cmd == 'fix': fixes([int(x) for x in sys.argv[2:]])   # meta/rotate.json for confirmed shot numbers
