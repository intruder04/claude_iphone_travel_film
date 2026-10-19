"""Step 6 — build the edit decision list (EDL) from locations.json (written by Claude after reviewing the footage).

For every clip in a location segment: score each second (sharpness, shake = high-frequency jitter of global
motion, fast pans, darkness, clipping, Apple aesthetics), take the best window, snap cut points to quiet audio
so speech isn't chopped, and drop near-duplicates by CLIP similarity (stricter for repetitive places such as
forests: segment "dedupe" < 0.92). Must-keep / dual-camera selfie / interesting-animal clips are protected.
Segments with "keep_whole": true (e.g. aerial shots with landmark callouts) are used whole.
Runtime is split by segment "weight" and iterated until the total hits project.json "target_minutes".
Output: meta/edl.json and EDIT_LIST.md (human-readable)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import CFG, P, jload, jsave

TARGET = float(os.environ.get('TARGET_MIN', CFG.get('target_minutes', 10))) * 60
L = jload('locations.json'); IDX = {r['file']: r for r in jload('meta/index.json')}
VIS = jload('meta/vision.json', {})
ORDER = [r['file'] for r in jload('meta/index.json')]
pos = {f: i for i, f in enumerate(ORDER)}
EXC, DUAL, MUST = set(L.get('exclude', [])), set(L.get('dual_selfie', [])), set(L.get('must_keep', []))
ANIM = dict(L.get('animals_interesting', {}))

def in_seg(f, seg):
    return pos[seg['from']] <= pos[f] <= pos[seg['to']]

def per_second(f):
    try: m = json.load(open(P('meta/metrics', f + '.json')))
    except FileNotFoundError: return None
    n = int(len(m['sharp']) / 10)
    if n < 1: return None
    sh = np.log1p(np.array(m['sharp'][:n * 10]).reshape(n, 10).mean(1))
    dx, dy = np.array(m['dx'][:n * 10]), np.array(m['dy'][:n * 10])
    jit = lambda a: np.abs(a - np.convolve(a, np.ones(5) / 5, 'same'))
    shake = (jit(dx) + jit(dy)).reshape(n, 10).mean(1)
    br = np.array(m['bright'][:n * 10]).reshape(n, 10).mean(1)
    cl = np.array(m['clipped'][:n * 10]).reshape(n, 10).mean(1)
    pan = np.hypot(dx, dy).reshape(n, 10).mean(1)
    v = VIS.get(f, [])
    aes = np.array([(x['aes'] if x.get('aes') is not None else 0) for x in v] + [0] * n)[:n]
    s = (0.9 * (sh - 5.5) - 1.6 * np.clip(shake - 0.35, 0, None) - 0.03 * np.clip(pan - 6, 0, None)
         - 2.0 * (br < 28) - 1.0 * (cl > 0.35) + 1.4 * aes)
    s[0] -= 1.0; s[-1] -= 0.6                                     # record-button wobble
    return s, np.array(m['rms']) if m['rms'] else np.zeros(n * 10)

def best_window(s, Ls, exclude=()):
    n = len(s); Ls = max(1, min(Ls, n)); best = (-1e9, 0)
    for a in range(0, n - Ls + 1):
        if any(a < e1 and a + Ls > e0 for e0, e1 in exclude): continue
        sc = s[a:a + Ls].mean()
        if sc > best[0]: best = (sc, a)
    return best[0], best[1], Ls

def snap(t, rms, lim=0.5):
    if len(rms) == 0: return t
    i = int(t * 10); lo, hi = max(0, i - int(lim * 10)), min(len(rms) - 1, i + int(lim * 10))
    return t if hi <= lo else (lo + int(np.argmin(rms[lo:hi + 1]))) / 10

def emb(f, a, b):
    try: e = np.load(P('meta/clip', f + '.npy'))
    except FileNotFoundError: return None
    e = e[max(0, a):max(a + 1, b)].mean(0); return e / np.linalg.norm(e)

def candidates(seg):
    out = []
    for f in ORDER:
        if not in_seg(f, seg) or f in EXC: continue
        r = IDX[f]; ps = per_second(f)
        if ps is None: continue
        s, rms = ps
        want = 10 if f in DUAL else 8 if f in MUST else 7 if f in ANIM else 5
        if r['dur'] > 40: want += 3
        sc, a, Ls = best_window(s, want)
        bonus = 3 if f in MUST else 2.5 if f in DUAL else 2 if f in ANIM else 0
        wins = [(a, Ls, sc)]
        if r['dur'] > 40 and f not in ANIM:                        # long clip: maybe a 2nd, different moment
            sc2, a2, L2 = best_window(s, want, exclude=[(a - 3, a + Ls + 3)])
            e1, e2 = emb(f, a, a + Ls), emb(f, a2, a2 + L2)
            if sc2 > -1 and e1 is not None and e2 is not None and float(e1 @ e2) < 0.9: wins.append((a2, L2, sc2))
        for a, Ls, sc in wins:
            ss = snap(a + 0.25, rms); ee = snap(min(r['dur'] - 0.1, a + Ls), rms)
            if ee - ss < 2.0: ss, ee = a + 0.25, min(r['dur'] - 0.1, a + Ls)
            out.append(dict(file=f, ss=round(ss, 2), dur=round(ee - ss, 2), score=round(float(sc) + bonus, 2),
                            time=r['time'], portrait=r['portrait'], hdr=r['hdr'], seg=seg['id'],
                            tag='dual-selfie' if f in DUAL else ANIM.get(f, 'must' if f in MUST else ''),
                            emb=emb(f, int(a), int(a + Ls))))
    return out

def pick(cands, budget, thr):
    chosen, used = [], 0.0
    for c in sorted(cands, key=lambda c: -c['score']):
        protected = c['file'] in MUST or c['file'] in DUAL or c['file'] in ANIM
        if not protected and used + c['dur'] > budget: continue
        if not protected and c['emb'] is not None and any(o['emb'] is not None and float(c['emb'] @ o['emb']) > thr for o in chosen):
            continue
        if not protected and c['score'] < -1.2: continue           # genuinely bad (blur / shake / dark)
        chosen.append(c); used += c['dur']
    return chosen, used

def main():
    segs = L['segments']; whole = [s for s in segs if s.get('keep_whole')]
    fixed = sum(IDX[f]['dur'] - 0.6 for s in whole for f in ORDER if in_seg(f, s) and f not in EXC)
    flex = [s for s in segs if not s.get('keep_whole') and s.get('weight', 1) > 0]
    cands = {s['id']: candidates(s) for s in flex}; weights = {s['id']: s.get('weight', 1) for s in flex}
    thr = {s['id']: s.get('dedupe', 0.92) for s in flex}; scale = 1.0; res = {}
    for _ in range(14):
        tot = sum(weights.values())
        res = {k: pick(cands[k], (TARGET - fixed) * weights[k] / tot * scale, thr[k]) for k in weights}
        total = fixed + sum(u for _, u in res.values())
        if abs(total - TARGET) < 20: break
        scale *= TARGET / max(total, 1)
    edl = []
    for s in segs:
        if s.get('keep_whole'):
            for f in ORDER:
                if in_seg(f, s) and f not in EXC:
                    r = IDX[f]; edl.append(dict(file=f, ss=0.3, dur=round(r['dur'] - 0.6, 2), seg=s['id'], time=r['time'],
                                                portrait=r['portrait'], hdr=r['hdr'], tag='keep whole', score=9))
        elif s['id'] in res:
            for c in sorted(res[s['id']][0], key=lambda c: (c['time'], c['ss'])):
                c.pop('emb', None); edl.append(c)
    total = sum(e['dur'] for e in edl if e['dur'] >= 2)
    jsave('meta/edl.json', dict(target=TARGET, total=round(total, 1), segments=segs, edl=edl))
    lines = ['# Edit list', f'{total / 60:.1f} min, {len(edl)} shots', '']; t = 0; cur = None
    for e in edl:
        if e['dur'] < 2: continue
        if e['seg'] != cur:
            cur = e['seg']; s = next(x for x in segs if x['id'] == cur)
            lines.append(f"\n## {s.get('place') or s['id']} — {s.get('city', '')}")
        lines.append(f"- {int(t // 60):02d}:{t % 60:04.1f}  {e['file']}  {e['ss']:.1f}s +{e['dur']:.1f}s  {e['tag']}"); t += e['dur']
    open(P('EDIT_LIST.md'), 'w').write('\n'.join(lines))
    print(f'{len(edl)} shots, {total / 60:.1f} min (target {TARGET / 60:.0f}) → meta/edl.json, EDIT_LIST.md')
    for s in segs:
        sh = [e for e in edl if e['seg'] == s['id']]
        if sh: print(f"  {s['id']:18} {len(sh):3} shots {sum(e['dur'] for e in sh):6.1f}s")

if __name__ == '__main__':
    main()
