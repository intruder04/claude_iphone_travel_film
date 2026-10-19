"""Step 7 — landmark callouts (📍 pin + label) that stick to buildings in aerial / skyline shots.

Workflow (Claude does the identification by looking at gridded frames — see references/landmarks.md):
  1. sheets.py grid CLIP T ...           gridded 1920x1080 frames to read pixel coordinates from
  2. write landmarks/anchors.json        {clip: [{name, anchors:[[t,x,y],...], zone:[half_w, h_below], lift}]}
     write landmarks/show.json           {clip: {name: [t_in, t_out]}}  (when each label is on screen)
  3. landmarks.py track [CLIP ...]       homography tracking from every anchor, forwards and backwards
  4. landmarks.py check [CLIP [NAME]]    drift sheets: crops around the tracked point over time → landmarks/drift/
     look at every sheet; add anchors where it drifts, shorten show windows where the landmark leaves frame
  5. landmarks.py render [CLIP ...]      4K HLG clips with callouts → landmarks/<clip>_callouts.mov (+ SDR preview)

Tracking: frames decoded once at 1280x720 (VideoToolbox), shared via memmap; per frame a RANSAC homography over
~600 Shi-Tomasi features (forward-backward checked) near the landmark — from a plane the city is ~planar, so this
is far steadier than patch tracking. Between two anchors the two tracks are cross-faded, so each anchor is exact."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import FF, SRC, P, jload, jsave, fps_of, grab
from tqdm import tqdm

TW, TH = 1280, 720; S = 1920 / TW

# ------------------------------------------------------------------ tracking
def _load(clip):
    raw = subprocess.run([FF, '-v', 'error', '-hwaccel', 'videotoolbox', '-i', os.path.join(SRC, clip), '-vf',
                          f'scale={TW}:{TH},format=gray', '-f', 'rawvideo', '-'], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, TH, TW)

def _step(a, b, p, R=260):
    import cv2
    LK = dict(winSize=(25, 25), maxLevel=4, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01))
    for rad in (R, 2 * R, None):
        m = np.zeros_like(a)
        if rad is None: m[:] = 255
        else: cv2.circle(m, (int(p[0]), int(p[1])), rad, 255, -1)
        pts = cv2.goodFeaturesToTrack(a, 600, 0.005, 6, mask=m, blockSize=5)
        if pts is None or len(pts) < 30: continue
        q, st, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None, **LK)
        r, st2, _ = cv2.calcOpticalFlowPyrLK(b, a, q, None, **LK)
        ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm(pts - r, axis=2).ravel() < 0.8)
        if ok.sum() < 25: continue
        d = np.linalg.norm(pts[ok].reshape(-1, 2) - p, axis=1); near = d < (rad * 0.5 if rad else R)
        Hm, inl = cv2.findHomography(np.concatenate([pts[ok], pts[ok][near]]), np.concatenate([q[ok], q[ok][near]]), cv2.RANSAC, 1.2)
        if Hm is None or inl.sum() < 20: continue
        v = Hm @ np.array([p[0], p[1], 1.0]); return v[:2] / v[2]
    return p

def _run(args):
    import cv2
    path, k, x, y, direction = args
    cv2.setNumThreads(1); fr = np.load(path, mmap_mode='r'); n = fr.shape[0]
    p = np.array([x / S, y / S]); out = {k: p}
    for i in (range(k, n - 1) if direction > 0 else range(k, 0, -1)):
        p = _step(np.asarray(fr[i]), np.asarray(fr[i + direction]), p); out[i + direction] = p
    return out

def track(clips):
    from multiprocessing import Pool
    A = jload('landmarks/anchors.json'); T = jload('landmarks/tracks.json', {})
    with Pool(min(8, os.cpu_count())) as pool:
        for clip in clips or list(A):
            fps = fps_of(clip); fr = _load(clip); n = len(fr); path = P('tmp', clip + '.frames.npy'); np.save(path, fr); del fr
            lms = A[clip]
            jobs = [(li, ai, (path, min(n - 1, int(round(t * fps))), x, y, d))
                    for li, lm in enumerate(lms) for ai, (t, x, y) in enumerate(lm['anchors']) for d in (1, -1)]
            res = list(tqdm(pool.imap(_run, [j[2] for j in jobs]), total=len(jobs), desc=f'Tracking {clip}', unit='pass'))
            os.remove(path); out = {}
            for li, lm in enumerate(lms):
                tracks = []
                for ai, (t, x, y) in enumerate(lm['anchors']):
                    k = min(n - 1, int(round(t * fps))); tr = [None] * n
                    for (l2, a2, _), r in zip(jobs, res):
                        if l2 == li and a2 == ai:
                            for i, p in r.items(): tr[i] = p
                    tracks.append((k, tr))
                ks = sorted(tracks, key=lambda kt: kt[0]); pts = []
                for i in range(n):
                    before = [kt for kt in ks if kt[0] <= i]; after = [kt for kt in ks if kt[0] >= i]
                    if before and after and before[-1][0] != after[0][0]:
                        (k0, t0), (k1, t1) = before[-1], after[0]; w = (i - k0) / (k1 - k0); p = (1 - w) * t0[i] + w * t1[i]
                    else:
                        p = (before[-1] if before else after[0])[1][i]
                    pts.append([round(float(p[0] * S), 1), round(float(p[1] * S), 1)])
                out[lm['name']] = pts
            T[clip] = dict(fps=fps, n=n, tracks=out); jsave('landmarks/tracks.json', T, None)

# ------------------------------------------------------------------ drift check sheets
def check(clip=None, name=None, step=1.5, crop=300, cols=8):
    from PIL import ImageDraw
    from sheets import _font
    from concurrent.futures import ThreadPoolExecutor
    T = jload('landmarks/tracks.json'); SH = jload('landmarks/show.json'); F = _font(14)
    os.makedirs(P('landmarks/drift'), exist_ok=True)
    todo = [(c, n) for c in ([clip] if clip else SH) for n in ([name] if name else SH[c])]
    for c, n in todo:
        t0, t1 = SH[c][n]; tr = T[c]['tracks'][n]; fps = T[c]['fps']
        ts = list(np.arange(t0, t1, step)) + [t1 - 0.05]
        with ThreadPoolExecutor(4) as ex: ims = list(ex.map(lambda t: grab(c, t), ts))
        from PIL import Image
        cells = []
        for t, im in zip(ts, ims):
            x, y = tr[min(len(tr) - 1, int(t * fps))]; ox, oy = int(x) - crop // 2, int(y) - crop // 2
            cc = im.crop((ox, oy, ox + crop, oy + crop)); d = ImageDraw.Draw(cc)
            for g in range((ox // 20 + 1) * 20, ox + crop, 20):
                d.line((g - ox, 0, g - ox, crop), fill=(255, 255, 0) if g % 100 == 0 else (255, 255, 0, 60))
                if g % 100 == 0: d.text((g - ox + 2, 2), str(g), font=F, fill=(255, 255, 0))
            for g in range((oy // 20 + 1) * 20, oy + crop, 20):
                d.line((0, g - oy, crop, g - oy), fill=(255, 255, 0) if g % 100 == 0 else (255, 255, 0, 60))
                if g % 100 == 0: d.text((2, g - oy + 2), str(g), font=F, fill=(255, 255, 0))
            m = crop // 2; d.line((m - 14, m, m + 14, m), fill=(255, 0, 255), width=3); d.line((m, m - 14, m, m + 14), fill=(255, 0, 255), width=3)
            d.rectangle((0, crop - 22, 170, crop), fill=(0, 0, 0)); d.text((4, crop - 20), f't={t:.1f}s ({x:.0f},{y:.0f})', font=F, fill=(255, 255, 255))
            cells.append(cc)
        k = min(cols, len(cells)); rows = (len(cells) + k - 1) // k
        Sh = Image.new('RGB', (k * crop, rows * crop + 30), (30, 30, 30))
        ImageDraw.Draw(Sh).text((6, 6), f'{c} — {n}', font=_font(20), fill=(255, 255, 255))
        for i, cc in enumerate(cells): Sh.paste(cc, ((i % k) * crop, 30 + (i // k) * crop))
        out = P('landmarks/drift', f"{os.path.splitext(c)[0]}_{n.replace(' ', '_')}.jpg"); Sh.save(out, quality=82); print(out)

# ------------------------------------------------------------------ render clips with callouts
def _overlay_for(clip):
    import gfx
    A = jload('landmarks/anchors.json'); T = jload('landmarks/tracks.json'); SH = jload('landmarks/show.json')
    t = T[clip]; fps = t['fps']
    zones = {l['name']: tuple(l.get('zone', (110, 300))) for l in A[clip]}; lift = {l['name']: l.get('lift', 0) for l in A[clip]}
    def smooth(a, k):
        a = np.array(a, float); pad = np.pad(a, ((k, k), (0, 0)), mode='edge'); ker = np.ones(2 * k + 1) / (2 * k + 1)
        return np.stack([np.convolve(pad[:, i], ker, 'valid') for i in range(2)], 1)
    tr = {n: smooth(p, int(fps * 0.15)) * 2 for n, p in t['tracks'].items()}      # 1920 → 3840 space
    co = gfx.Callouts()
    def fn(ts):
        i = min(int(ts * fps), t['n'] - 1); items = []
        for n, (a, b) in SH[clip].items():
            x, y = tr[n][i]
            al = gfx.env(ts, a, b, 0.5) * gfx.clamp(min(x - 60, gfx.W - 60 - x, y - 60, gfx.H - 60 - y) / 120)
            if al > 0.01: items.append(dict(name=n, x=x, y=y - lift[n], alpha=al, zone=zones[n]))
        return co.frame(items, ts) if items else None
    fn.co = co
    return fn

def _render_one(clip):
    from compose import render, preview
    r = {x['file']: x for x in jload('meta/index.json')}[clip]
    fn = _overlay_for(clip); out = P('landmarks', f'{clip}_callouts.mov')
    render(dict(file=clip, ss=0, dur=r['dur'] - 0.05, portrait=False, hdr=r['hdr']), out, fn)
    preview(out, out.replace('.mov', '_preview.mp4'))
    return f'{clip}: frames where labels could not avoid overlapping = {fn.co.overlaps}'

def render_all(clips):
    from concurrent.futures import ProcessPoolExecutor
    todo = clips or list(jload('landmarks/show.json'))
    with ProcessPoolExecutor(int(os.environ.get('JOBS', 2))) as ex:
        for msg in tqdm(ex.map(_render_one, todo), total=len(todo), desc='Rendering callout clips', unit='clip'): print(msg)

if __name__ == '__main__':
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ''), sys.argv[2:]
    if cmd == 'track': track(args)
    elif cmd == 'check': check(*(args[:2] if args else []))
    elif cmd == 'render': render_all(args)
    else: sys.exit(__doc__)
