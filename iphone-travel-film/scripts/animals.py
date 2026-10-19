"""Step 8b — short animal labels (navy dot + name, no pin), once per species, at its first appearance in the edit.

  animals.py candidates   list edit shots where Apple Vision / CLIP saw an animal (start of the hunt; also look
                          at the footage yourself — small things like insects are often missed by detectors)
  animals.py search "a cicada on a red gate" ["…"]   text search over every analysed second of footage (CLIP
                          embeddings, GPU) — finds small creatures detectors miss; prints clip + time to inspect
  animals.py track        read animals.json, track each animal inside its shot → meta/animal_labels.json
  animals.py check        review/animal_check.jpg: start/middle/end crops with the tracked point marked

animals.json (written by Claude after looking at gridded frames, coordinates in 1920x1080 space):
  [{"file": "IMG_0001.MOV", "t": 7.9, "x": 979, "y": 576, "name": "Grey Heron"},              # optical-flow tracked
   {"file": "IMG_0002.MOV", "keys": [[4.0,1450,910],[5.2,1790,990]], "name": "Water Strider"}] # keyframed (tiny/fast)
"t" / the first key = the clip time where the animal FIRST becomes visible: the label appears right then, for ~2.6 s.
List every clip an animal is in; only its first appearance in the edit (edit order, not file order) gets a label.
Output meta/animal_labels.json {clip: [{name, start, end (clip time), shot_ss, track (60 fps from shot_ss)}]}."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import FF, SRC, src, P, jload, jsave, edl_shots, grab

TW, TH = 960, 540; S = 3840 / TW; SHOW = 2.6

def _load(clip, ss, dur):
    raw = subprocess.run([FF, '-v', 'error', '-hwaccel', 'videotoolbox', '-ss', f'{ss:.3f}', '-t', f'{dur:.3f}', *src(clip), '-vf', f'fps=60,scale={TW}:{TH},format=gray', '-f', 'rawvideo', '-'],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, TH, TW)

def _track(fr, k, p0):
    import cv2
    LK = dict(winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    def step(a, b, p, R=45):        # median flow of features on the animal: follows a moving subject
        m = np.zeros_like(a); cv2.circle(m, (int(p[0]), int(p[1])), R, 255, -1)
        pts = cv2.goodFeaturesToTrack(a, 80, 0.01, 3, mask=m)
        if pts is None or len(pts) < 4: return p
        q, st, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None, **LK); ok = st.ravel() == 1
        return p if ok.sum() < 3 else p + np.median((q - pts)[ok].reshape(-1, 2), axis=0)
    n = len(fr); tr = [None] * n; tr[k] = p0; p = p0
    for i in range(k, n - 1): p = step(fr[i], fr[i + 1], p); tr[i + 1] = p
    p = p0
    for i in range(k, 0, -1): p = step(fr[i], fr[i - 1], p); tr[i - 1] = p
    a = np.array(tr); pad = np.pad(a, ((7, 7), (0, 0)), mode='edge'); ker = np.ones(15) / 15
    return np.stack([np.convolve(pad[:, j], ker, 'valid') for j in range(2)], 1)

def candidates():
    V = jload('meta/vision.json', {}); C = jload('meta/clip_tags.json', {}); E, edl = edl_shots()
    words = ('bird', 'cat', 'dog', 'fish', 'duck', 'crow', 'squirrel', 'turtle', 'heron', 'insect', 'reptile', 'lizard',
             'animal', 'mammal', 'koi', 'deer', 'monkey', 'horse', 'cow', 'goat', 'sheep', 'frog', 'butterfly', 'crab',
             'snake', 'seal', 'dolphin', 'whale', 'jellyfish', 'penguin', 'camel', 'elephant')
    for i, e in enumerate(edl):
        fr = V.get(e['file'], []); a, b = int(e['ss']), int(e['ss'] + e['dur']) + 1
        an = {x for f in fr[a:b] for x in f['animals']}
        lab = {l for f in fr[a:b] for l, c in f['cls'] if l in words}
        tags = {t for t, _ in C.get(e['file'], {}).get('tags', [])[:3] if any(w in t for w in words)}
        if an or lab or tags or e.get('tag') not in ('', 'must', 'dual-selfie', 'keep whole'):
            print(f"shot {i:3d}  {e['file']}  {e['ss']:.1f}+{e['dur']:.1f}s  {e.get('tag', '')}  {sorted(an | lab | tags)}")

def search(queries, top=14):
    import glob, numpy as np, torch, open_clip
    m, _, _ = open_clip.create_model_and_transforms('ViT-B-16-quickgelu', pretrained='openai'); tok = open_clip.get_tokenizer('ViT-B-16-quickgelu')
    neg = ['a street', 'a building', 'a forest', 'people walking', 'water', 'a wall']
    with torch.no_grad(): t = m.encode_text(tok(queries + neg)); t = (t / t.norm(dim=-1, keepdim=True)).numpy()
    res = []
    for f in glob.glob(P('meta/clip', '*.npy')):
        e = np.load(f); p = np.exp(100 * (e @ t.T)); p /= p.sum(1, keepdims=True); sc = p[:, :len(queries)].sum(1)
        k = int(sc.argmax()); res.append((float(sc[k]), os.path.basename(f)[:-4], k))
    E, edl = edl_shots(); inedit = {e['file'] for e in edl}
    for sc, f, k in sorted(res, reverse=True)[:top]:
        print(f"{sc:.3f}  {f}  ~{k}s  {'(in edit)' if f in inedit else ''}")
    print('→ inspect with: sheets.py grid CLIP T')

def track():
    spec = jload('animals.json'); E, edl = edl_shots(); out = {}; seen = set()
    pos = {}
    for k, e in enumerate(edl):
        pos.setdefault(e['file'], []).append((k, e))
    def first_in_edit(a):
        t = a['keys'][0][0] if 'keys' in a else a['t']
        for k, e in pos.get(a['file'], []):
            if e['ss'] - 0.2 <= t <= e['ss'] + e['dur'] - 1.0: return k, e, t
        for k, e in pos.get(a['file'], []):                 # animal visible before the shot starts → label at shot start
            if t < e['ss'] and e['dur'] > 2.5: return k, e, e['ss'] + 0.2
        return None
    placed = sorted([(fe[0], a, fe[1], fe[2]) for a in spec for fe in [first_in_edit(a)] if fe], key=lambda x: x[0])
    for k, a, e, t0 in placed:
        if a['name'] in seen: continue                        # once per animal: its first appearance in the film
        seen.add(a['name'])
        st = max(e['ss'] + 0.15, t0); en = min(e['ss'] + e['dur'] - 0.3, st + SHOW)
        n = int(round(e['dur'] * 60)); ts = e['ss'] + np.arange(n) / 60
        if 'keys' in a:
            kt, kx, ky = zip(*a['keys'])
            tr = np.stack([np.interp(ts, kt, kx), np.interp(ts, kt, ky)], 1) * 2
        else:
            fr = _load(a['file'], e['ss'], e['dur']); kk = max(0, min(len(fr) - 1, int(round((a['t'] - e['ss']) * 60))))
            tr = _track(fr, kk, np.array([a['x'] / 2, a['y'] / 2])) * S
        out.setdefault(a['file'], []).append(dict(name=a['name'], start=round(st, 2), end=round(en, 2), shot_ss=e['ss'],
                                                  track=tr.round(1).tolist()))
        print(f"{a['name']:28} shot {k:3d}  {a['file']}  label {st:.1f}-{en:.1f}s (clip time)")
    missing = {a['name'] for a in spec} - seen
    if missing: print('not in the edit:', ', '.join(sorted(missing)))
    jsave('meta/animal_labels.json', out, None)

def check():
    from PIL import Image, ImageDraw
    from sheets import _font
    A = jload('meta/animal_labels.json'); F = _font(16); rows = []
    for clip, items in A.items():
        for it in items:
            cells = []
            for q in (0, 0.5, 1):
                lt = it['start'] + (it['end'] - it['start']) * q
                x, y = [v / 2 for v in it['track'][min(len(it['track']) - 1, int((lt - it['shot_ss']) * 60))]]
                im = grab(clip, lt).crop((int(x) - 160, int(y) - 110, int(x) + 160, int(y) + 110)); d = ImageDraw.Draw(im)
                d.line((145, 110, 175, 110), fill=(255, 0, 255), width=2); d.line((160, 95, 160, 125), fill=(255, 0, 255), width=2)
                d.text((4, 4), f"{it['name']} @{lt:.1f}s", font=F, fill=(255, 255, 0)); cells.append(im)
            r = Image.new('RGB', (960, 220)); [r.paste(c, (k * 320, 0)) for k, c in enumerate(cells)]; rows.append(r)
    Sh = Image.new('RGB', (1920, 220 * ((len(rows) + 1) // 2)))
    for k, r in enumerate(rows): Sh.paste(r, ((k % 2) * 960, (k // 2) * 220))
    Sh.save(P('review', 'animal_check.jpg'), quality=85); print(P('review', 'animal_check.jpg'))

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'search': search(sys.argv[2:] or ['a close-up of an insect', 'a small animal'])
    else: {'candidates': candidates, 'track': track, 'check': check}.get(cmd, lambda: sys.exit(__doc__))()
