"""Step 3 — decode every clip once (VideoToolbox) and measure it.

Per clip:
  frames/<clip>/NNNN.jpg   2 fps, 768 px, SDR tone-mapped — for contact sheets, CLIP, Apple Vision, horizon
  meta/metrics/<clip>.json 10 fps: sharpness (Laplacian), brightness, clipping, global motion (phase correlation),
                           frame difference; audio RMS and low-frequency share (wind) every 0.1 s
4 clips in parallel; ~1 GB RAM total. Resumable: finished clips are skipped."""
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np
from common import FF, SRC, src, P, jload, TONEMAP_CPU
from tqdm import tqdm

def run(r):
    f = r['file']; out = P('frames', f); mf = P('meta/metrics', f + '.json')
    if os.path.exists(mf): return
    os.makedirs(out, exist_ok=True)
    pw, ph = (180, 320) if r['portrait'] else (320, 180)
    tm = TONEMAP_CPU if r['hdr'] else 'format=yuv420p'
    fc = (f"[0:v]fps=10,scale={'432:768' if r['portrait'] else '768:432'}:flags=bilinear,{tm},split=2[a][b];"
          f"[a]select='not(mod(n\\,5))'[a2];[b]scale={pw}:{ph},format=gray[b2]")
    raw = subprocess.run([FF, '-v', 'error', '-hwaccel', 'videotoolbox', *src(f), '-filter_complex', fc,
                          '-map', '[a2]', '-fps_mode', 'vfr', '-q:v', '4', f'{out}/%04d.jpg',   # vfr: keep only the 2 fps selection
                          '-map', '[b2]', '-f', 'rawvideo', '-'],
                         capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8)[: (len(raw) // (pw * ph)) * pw * ph].reshape(-1, ph, pw)
    sharp = [float(cv2.Laplacian(x, cv2.CV_64F).var()) for x in fr]
    bright = [float(x.mean()) for x in fr]
    clipped = [float(((x > 250) | (x < 5)).mean()) for x in fr]
    dx, dy, diff = [0.0], [0.0], [0.0]
    win = cv2.createHanningWindow((pw, ph), cv2.CV_32F)
    for a, b in zip(fr[:-1], fr[1:]):
        (sx, sy), _ = cv2.phaseCorrelate(a.astype(np.float32), b.astype(np.float32), win)
        dx.append(float(sx)); dy.append(float(sy)); diff.append(float(cv2.absdiff(a, b).mean()))
    rms, low = [], []
    if r.get('audio', True):
        au = subprocess.run([FF, '-v', 'error', '-i', os.path.join(SRC, f), '-map', '0:a:0', '-ac', '1', '-ar', '16000',
                             '-f', 's16le', '-'], capture_output=True).stdout
        a = np.frombuffer(au, np.int16).astype(np.float32) / 32768
        for i in range(0, len(a) - 1600, 1600):
            s = a[i:i + 1600]; rms.append(float(np.sqrt((s ** 2).mean()) + 1e-9))
            sp = np.abs(np.fft.rfft(s)); low.append(float(sp[:10].sum() / (sp.sum() + 1e-9)))
    json.dump(dict(fps=10, sharp=sharp, bright=bright, clipped=clipped, dx=dx, dy=dy, diff=diff, rms=rms, low=low),
              open(mf, 'w'))

if __name__ == '__main__':
    idx = jload('meta/index.json')
    todo = [r for r in idx if not os.path.exists(P('meta/metrics', r['file'] + '.json'))]
    with ThreadPoolExecutor(4) as ex:
        list(tqdm(ex.map(run, todo), total=len(todo), desc='Analysing clips (VideoToolbox decode)', unit='clip'))
    print('done')
