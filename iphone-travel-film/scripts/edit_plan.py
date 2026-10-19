"""Step 6 — build the edit from Claude's per-clip intents (the preferred way; select_shots.py is the fallback).

intents.json (written by Claude from the intent sheets: what each clip is FOR):
  [{"file": "IMG_0001.MOV", "seg": "harbour", "subject": "fish_market_stalls", "q": 3, "win": [4.0, 15.5], "note": "..."}]
  q    0 drop · 1 filler · 2 good · 3 highlight          win  the moment, in clip seconds
  subject  clips with the same subject show the same thing with the same intent → only the BEST one is used
           (smoothest, sharpest, best framed: q first, then measured quality inside the window)

Cutting rules (all measured, nothing guessed):
  * never cut during a fast pan/zoom: in/out points move to the nearest calm moment (meta/shots, ±1.5 s)
  * never cut through a word: cuts move outside spoken words (meta/speech word timestamps)
  * length follows the content, not a quota: highlights up to 12 s, selfies/speech up to 18 s, good shots 7 s,
    fillers 4.5 s; a window is only trimmed when it is longer than that (best-scoring part kept)
  * an intent with "exact": true keeps its window untouched (no trimming/snapping) — for moments whose build-up
    matters, e.g. lights standing still before they start to move
  * a segment may set "max_shot" (seconds) to keep the pace up in places with many highlights
  * aerial "plane" windows from locations.json are used as listed (steady holds only, zooms excluded)
Order: segments in locations.json order; inside a segment, capture time.
The target length in project.json is a guide only — the plan reports it, it never pads or cuts to hit it.
Output: meta/edl.json, EDIT_LIST.md"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import CFG, P, jload, jsave

MAXLEN = {3: 12.0, 2: 7.0, 1: 4.5}
SPEECH_MAX, MIN_LEN, SNAP = 18.0, 2.0, 1.5

def per_second_score(f):
    """Quality per second: sharpness, shake, exposure, Apple aesthetics (same model as select_shots)."""
    try:
        import select_shots as ss
        r = ss.per_second(f)
        return None if r is None else r[0]
    except SystemExit:
        return None

def shots(f):
    p = P('meta/shots', f + '.json')
    return json.load(open(p)) if os.path.exists(p) else None

def calm_point(sh, t, direction, lim=SNAP):
    """Nearest time to t (searching `direction` first) where the camera is calm and not mid-pan/zoom."""
    if not sh or not sh.get('calm'): return t
    calm, fast, sp = np.array(sh['calm']), np.array(sh['fast']), np.array(sh['speed'])
    n = len(calm); i0 = int(round(t * 10))
    if 0 <= i0 < n and calm[i0] and not fast[i0]: return t
    order = []
    for d in range(1, int(lim * 10) + 1):
        order += [i0 + direction * d, i0 - direction * d]
    for i in order:
        if 0 <= i < n and calm[i] and not fast[i]: return i / 10
    lo, hi = max(0, i0 - int(lim * 10)), min(n - 1, i0 + int(lim * 10))       # no calm frame: slowest moment
    return (lo + int(np.argmin(sp[lo:hi + 1]))) / 10 if hi > lo else t

def word_safe(words, a, b):
    """Move cut points out of spoken words: start before a word that is cut, end after it."""
    for ws, we, _ in words:
        if ws < a < we: a = max(0.0, ws - 0.10)
        if ws < b < we: b = we + 0.25
    return a, b

def refine(f, win, q, dur, has_speech, words, max_shot=None):
    a, b = max(0.0, win[0]), min(dur - 0.1, win[1])
    cap = SPEECH_MAX if has_speech else MAXLEN.get(q, 7.0)
    if max_shot: cap = min(cap, max_shot)                  # segment pace limit (busy places with many shots)
    if b - a > cap:                                         # keep the best-scoring part of a long moment
        sc = per_second_score(f); sh = shots(f)
        L = int(cap); best, bi = -1e9, int(a)
        for s in range(int(a), int(b - L) + 1):
            v = float(np.mean(sc[s:s + L])) if sc is not None and s + L <= len(sc) else 0.0
            if sh and sh.get('events'):                    # prefer windows that contain the "event"
                v += sum(1.0 for e in sh['events'] if s <= e[0] and e[1] <= s + L)
            if v > best: best, bi = v, s
        a, b = float(bi), float(bi + L)
    sh = shots(f)
    a2 = calm_point(sh, a, +1); b2 = calm_point(sh, b, -1)
    if b2 - a2 >= MIN_LEN: a, b = a2, b2
    a, b = word_safe(words, a, b)
    b = min(b, dur - 0.05)
    return round(a, 2), round(b - a, 2)

def main():
    L = jload('locations.json'); I = jload('intents.json'); IDX = {r['file']: r for r in jload('meta/index.json')}
    SP = jload('meta/speech.json', {}); dual = set(L.get('dual_selfie', []))
    segs = L['segments']; order = {s['id']: k for k, s in enumerate(segs)}
    # 1) best clip per subject
    by_subject = {}
    for o in I:
        if o['q'] < 2 or not o.get('seg') or o['file'] not in IDX: continue
        sc = per_second_score(o['file']); w = o['win'] or [0, IDX[o['file']]['dur']]
        tech = float(np.mean(sc[int(w[0]):max(int(w[0]) + 1, int(w[1]))])) if sc is not None and len(sc) > int(w[0]) else 0.0
        key = (o['q'], tech)
        cur = by_subject.get((o['seg'], o['subject']))
        if cur is None or key > cur[0]: by_subject[(o['seg'], o['subject'])] = (key, o)
    # 2) refine cut points
    edl = []
    for (seg, subj), (key, o) in by_subject.items():
        r = IDX[o['file']]; words = SP.get(o['file'], {}).get('words', [])
        w = o['win'] or [0.3, r['dur'] - 0.3]
        has_speech = o['file'] in dual or any(w[0] <= ws <= w[1] for ws, _, _ in words)
        if o.get('exact'):                                  # Claude/user set the exact moment (e.g. a build-up that
            ss, dd = round(w[0], 2), round(min(w[1], r['dur'] - 0.05) - w[0], 2)   # must not be trimmed): keep as is
        else:
            ss, dd = refine(o['file'], w, o['q'], r['dur'], has_speech, words, segs[order[seg]].get('max_shot'))
        if dd < MIN_LEN: continue
        edl.append(dict(file=o['file'], ss=ss, dur=dd, seg=seg, subject=subj, q=o['q'], time=r['time'], portrait=r['portrait'],
                        hdr=r['hdr'], tag='dual-selfie' if o['file'] in dual else '', note=o.get('note', '')))
    # 2b) look-alike pass: different subjects that still LOOK the same (CLIP similarity of the chosen windows) in
    #     the same segment — keep the better one. Repetition is what makes travel edits drag.
    def emb(e):
        p = P('meta/clip', e['file'] + '.npy')
        if not os.path.exists(p): return None
        v = np.load(p); a, b = int(e['ss']), max(int(e['ss']) + 1, int(e['ss'] + e['dur']))
        v = v[a:b].mean(0) if len(v) > a else v.mean(0); return v / np.linalg.norm(v)
    thr = float(CFG.get('lookalike_threshold', 0.93)); dropped = []
    for seg in {e['seg'] for e in edl}:
        sh = sorted([e for e in edl if e['seg'] == seg], key=lambda e: (-e['q'], -e['dur']))
        keep = []
        for e in sh:
            v = emb(e)
            # highlights (q3) are only dropped when nearly identical to another highlight; good shots at `thr`
            if v is not None and e['tag'] != 'dual-selfie' and any(
                    k[1] is not None and float(v @ k[1]) > (0.965 if e['q'] == 3 else thr) and k[0]['q'] >= e['q'] for k in keep):
                dropped.append(e); continue
            keep.append((e, v))
    edl = [e for e in edl if e not in dropped]
    if dropped: print(f'look-alike pass removed {len(dropped)} shots: ' + ', '.join(f"{e['file'][:-4]}({e['subject']})" for e in dropped[:12]) + (' …' if len(dropped) > 12 else ''))
    # 3) aerial windows
    for s in segs:
        for k, (f, a, b, note) in enumerate(s.get('plane', [])):
            r = IDX[f]
            edl.append(dict(file=f, ss=a, dur=round(b - a, 2), seg=s['id'], subject=f'plane_{k}', q=3, time=r['time'], portrait=False,
                            hdr=r['hdr'], tag='plane', note=note, plane_order=k))
    edl.sort(key=lambda e: (order[e['seg']], e.get('plane_order', 0), e['time'], e['ss']))
    total = sum(e['dur'] for e in edl)
    jsave('meta/edl.json', dict(target=CFG.get('target_minutes', 0) * 60, total=round(total, 1), segments=segs, edl=edl))
    lines = ['# Edit list', f'{total / 60:.1f} min, {len(edl)} shots (target ~{CFG.get("target_minutes", "?")} min — a guide, not a rule)', '']
    t = 0; cur = None
    for e in edl:
        if e['seg'] != cur:
            cur = e['seg']; s = segs[order[cur]]
            lines.append(f"\n## {s.get('place') or s['id']} — {s.get('city', '')}{'  [NEW CITY]' if s.get('new_city') else ''}")
        lines.append(f"- {int(t // 60):02d}:{t % 60:04.1f}  {e['file']}  {e['ss']:.1f}s +{e['dur']:.1f}s  q{e['q']}  {e['subject']}  {e['note']}")
        t += e['dur']
    open(P('EDIT_LIST.md'), 'w').write('\n'.join(lines))
    print(f'{len(edl)} shots, {total / 60:.1f} min → meta/edl.json, EDIT_LIST.md')

if __name__ == '__main__':
    main()
