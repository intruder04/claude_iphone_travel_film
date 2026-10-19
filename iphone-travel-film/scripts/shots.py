"""Step 3b — camera-motion and in-shot structure for every clip (decides WHERE a shot may be cut).

One low-res decode per clip (VideoToolbox, 10 fps, 320 px) gives, per 0.1 s:
  speed   camera translation in % of frame width per second (global affine fit on tracked features)
  zoom    zoom rate in % per second (+ = zooming in)
  roll    rotation rate in degrees per second
  resid   motion INSIDE the frame after removing camera motion (a train passing, a bird taking off) 0..1
plus PySceneDetect (AdaptiveDetector) cut points — real scene changes inside one recording.

Derived per clip:
  calm[]  0.1 s steps where a cut is allowed: camera still or slow (no cutting mid-pan / mid-zoom)
  events  windows of high in-frame activity with a calm camera (the moment the shot was taken for)
Output: meta/shots/<clip>.json      Usage: shots.py [CLIP ...]   (4 clips in parallel, % progress)"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import FF, SRC, src, P, jload
from tqdm import tqdm

W_, H_ = 320, 180
FAST_PAN = 18.0       # % of frame width per second — above this a cut feels jarring
CALM = 6.0            # below this the camera counts as settled (cut allowed)
FAST_ZOOM = 12.0      # % per second

def analyse(r):
    import cv2
    from scenedetect.detectors import AdaptiveDetector
    clip = r['file']; out = P('meta/shots', clip + '.json')
    if os.path.exists(out): return
    w, h = (H_, W_) if r['portrait'] else (W_, H_)
    raw = subprocess.run([FF, '-v', 'error', '-hwaccel', 'videotoolbox', *src(clip), '-vf',
                          f'fps=10,scale={w}:{h}', '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    if n < 2: json.dump(dict(n=n), open(out, 'w')); return
    fr = np.frombuffer(raw, np.uint8)[:n * w * h * 3].reshape(n, h, w, 3)
    det = AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=15); cuts = []
    for i, f in enumerate(fr):
        for c in det.process_frame(i, f.copy()): cuts.append(round(int(c) / 10, 1))
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in fr]
    speed, zoom, roll, resid = [0.0], [0.0], [0.0], [0.0]
    for a, b in zip(gray[:-1], gray[1:]):
        pts = cv2.goodFeaturesToTrack(a, 200, 0.01, 6)
        M = None
        if pts is not None and len(pts) >= 12:
            q, st, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None, winSize=(15, 15), maxLevel=3)
            ok = st.ravel() == 1
            if ok.sum() >= 10: M, _ = cv2.estimateAffinePartial2D(pts[ok], q[ok], method=cv2.RANSAC, ransacReprojThreshold=1.0)
        if M is None:
            speed.append(speed[-1]); zoom.append(0.0); roll.append(0.0); resid.append(0.0); continue
        s = float(np.hypot(M[0, 0], M[1, 0])); ang = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
        speed.append(float(np.hypot(M[0, 2], M[1, 2])) / w * 100 * 10)       # % width / s
        zoom.append((s - 1) * 100 * 10); roll.append(ang * 10)
        warped = cv2.warpAffine(a, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
        d = cv2.absdiff(warped, b)[8:-8, 8:-8]
        resid.append(float((d > 28).mean()))                                  # share of pixels that moved on their own
    def sm(x, k=5):
        x = np.array(x, float)
        return np.convolve(np.pad(x, (k // 2, k - 1 - k // 2), mode='edge'), np.ones(k) / k, 'valid')
    sp, zm, rs = sm(speed), sm(np.abs(zoom)), sm(resid, 9)
    calm = ((sp < CALM) & (zm < FAST_ZOOM / 3)).astype(int).tolist()
    fast = ((sp > FAST_PAN) | (zm > FAST_ZOOM)).astype(int).tolist()
    # events: in-frame activity well above the clip's baseline while the camera is calm
    base = float(np.median(rs)); ev = []
    on = (rs > max(0.02, base * 2.5)) & (sp < CALM * 1.5)
    i = 0
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]: j += 1
            if j - i >= 5: ev.append([round(i / 10, 1), round(j / 10, 1), round(float(rs[i:j].max()), 3)])
            i = j
        else: i += 1
    json.dump(dict(n=n, fps=10, cuts=cuts, speed=[round(x, 2) for x in speed], zoom=[round(x, 2) for x in zoom],
                   roll=[round(x, 2) for x in roll], resid=[round(x, 4) for x in resid], calm=calm, fast=fast, events=ev),
              open(out, 'w'))

def _safe(r):
    try: analyse(r)
    except Exception as e: print(f"{r['file']}: {e}")

if __name__ == '__main__':
    from concurrent.futures import ProcessPoolExecutor
    idx = jload('meta/index.json'); os.makedirs(P('meta/shots'), exist_ok=True)
    todo = [r for r in idx if (not sys.argv[1:] or r['file'] in sys.argv[1:]) and not os.path.exists(P('meta/shots', r['file'] + '.json'))]
    with ProcessPoolExecutor(4) as ex:
        list(tqdm(ex.map(_safe, todo), total=len(todo), desc='Camera motion + scene cuts', unit='clip'))
    print('done')
