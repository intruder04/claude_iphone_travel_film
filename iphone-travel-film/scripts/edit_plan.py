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
  * optional aerial windows ("aerial" in locations.json; older projects call it "plane") are used as listed
    (steady holds only, zooms excluded). Most trips have none, and nothing else depends on them
  * with subtitles on, a shot with speech is extended (or trimmed back) to whole spoken sentences, so a subtitle
    never starts or stops mid-sentence; speech shots may run up to project.json "speech_max" (default 25 s)
  * screen recordings (index "screen": true) are used only when they explain the footage around them (the route on
    a map, a ticket app, a translation). "after": "IMG_….MOV" on the intent places one right after that camera clip
    (its own capture time is often minutes off the moment it belongs to); unmatched screen recordings get q 0
  * "speed" on an intent changes playback speed: 0.5 = slow motion, 2 / 3 / 4 / 8 = sped up (a "4×" badge is shown).
    Slow motion needs real frames: it is limited to 30 / (the clip's real average fps), so 60 fps clips go to 0.5x and
    low-light clips (variable frame rate, ~30 fps) are never slowed. Shots with speech are never speed-changed, unless
    the intent says "speech_ok": true (Claude checked that it is only announcements, a guide or background chatter).
    "win" is in source seconds; the shot's length on the timeline is the window divided by the speed
  * project.json "cold_open": true puts a ~25 s teaser of the best moments in front of the film (and of every part
    when the film is split): locations.json "teaser": {"1": ["IMG_….MOV", ...]} lists the clips (taken from their
    windows in this edit, ~3 s each); without a list the highest-rated, most aesthetic highlights are picked, one per place
  * project.json "end_card": true makes sure the last shot of the film / each part is long enough (≥ 7 s) for the card
  * one clip can hold several moments: write one intent per moment (different subjects, their own windows); the
    dull stretch between them is simply left out (e.g. the walk up an alley, then the shrine at its end)
  * talking shots are tightened (project.json "speech_tighten", default on): a silence longer than
    "speech_pause_cut" (1.6 s) between sentences is cut out, leaving ~0.4 s on each side, so the shot becomes
    several jump-cut pieces. A pause is kept when something happens in the picture (meta/shots events), and
    shots with "keep_pauses": true on the intent are never tightened
Order: segments in locations.json order; inside a segment, capture time (or the "after" clip's).
The target length in project.json is a guide only — the plan reports it, it never pads or cuts to hit it.
Output: meta/edl.json, EDIT_LIST.md"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import CFG, P, jload, jsave, probe

MAXLEN = {3: 12.0, 2: 7.0, 1: 4.5}
SPEECH_MAX, MIN_LEN, SNAP = float(CFG.get('speech_max', 25.0)), 2.0, 1.5
SENTENCE_EXTEND = 6.0       # how far a cut may move to keep a sentence whole

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

def sentence_safe(segs, a, b, dur):
    """Keep whole sentences: a cut inside a sentence moves to its start/end (≤ SENTENCE_EXTEND s away), else drops it."""
    for ss_, se_, _ in segs:
        if ss_ < a < se_: a = max(0.0, ss_ - 0.15) if a - ss_ <= SENTENCE_EXTEND else se_ + 0.1
        if ss_ < b < se_: b = min(dur - 0.05, se_ + 0.35) if se_ - b <= SENTENCE_EXTEND else ss_ - 0.05
    return a, b

def real_fps(f):
    """Average frame rate actually recorded (iPhones drop to ~25-30 fps in low light even in 60/120 fps modes)."""
    v = [s for s in probe(f)['streams'] if s['codec_type'] == 'video'][0]
    n, d = map(int, v.get('avg_frame_rate', '0/1').split('/'))
    return n / d if d else 30.0

def clamp_speed(f, speed, has_speech):
    if speed == 1.0: return 1.0
    if has_speech:
        print(f'  {f}: speed {speed:g} ignored — the window has speech'); return 1.0
    if speed < 1.0:
        lo = min(1.0, 30.0 / max(1.0, real_fps(f)))         # ≥ 30 distinct frames per second on screen
        if speed < lo - 0.02: print(f'  {f}: slow motion {speed:g} → {lo:.2g} (clip has {real_fps(f):.0f} fps)')
        return round(max(speed, lo), 2)
    return float(speed)

PAUSE_CUT, PAUSE_PAD = float(CFG.get('speech_pause_cut', 1.6)), 0.4

def tighten(f, ss, dd, words):
    """Cut long silences out of a talking shot: returns [(start, dur), ...] pieces in clip time."""
    a, b = ss, ss + dd
    ws = [w for w in words if w[0] >= a - 0.05 and w[1] <= b + 0.1]
    if len(ws) < 2: return [(ss, dd)]
    sh = shots(f) or {}
    def busy(x, y):                                         # something happens on screen during the pause: keep it
        return any(e[0] < y and e[1] > x for e in sh.get('events', []))
    keep, cur = [], [a, ws[0][1]]
    for w0, w1 in zip(ws[:-1], ws[1:]):
        gap0, gap1 = w0[1], w1[0]
        if gap1 - gap0 > PAUSE_CUT and not busy(gap0, gap1):
            cur[1] = gap0 + PAUSE_PAD; keep.append(cur); cur = [gap1 - PAUSE_PAD, w1[1]]
        else:
            cur[1] = w1[1]
    cur[1] = b; keep.append(cur)
    out = []
    for x, y in keep:                                       # pieces shorter than MIN_LEN grow into the cut silence
        if y - x < MIN_LEN: x, y = max(a, x - (MIN_LEN - (y - x)) / 2), min(b, y + (MIN_LEN - (y - x)) / 2)
        if out and x <= out[-1][1] + 0.05: out[-1][1] = max(out[-1][1], y)
        else: out.append([x, y])
    return [(round(x, 2), round(y - x, 2)) for x, y in out]

def refine(f, win, q, dur, has_speech, words, max_shot=None, segs=(), speed=1.0):
    a, b = max(0.0, win[0]), min(dur - 0.1, win[1])
    cap = SPEECH_MAX if has_speech else MAXLEN.get(q, 7.0)
    if max_shot: cap = min(cap, max_shot)                  # segment pace limit (busy places with many shots)
    cap *= speed                                            # caps are timeline seconds; the window is source seconds
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
    if segs and CFG.get('subtitles', False): a, b = sentence_safe(segs, a, b, dur)
    b = min(b, dur - 0.05)
    return round(a, 2), round(b - a, 2)

TEASER_SHOT, TEASER_LEN = 3.0, 25.0

def add_teasers(edl, part_of, chosen):
    """Insert a teaser (best moments, ~3 s each) in front of the film or of each part. Shots carry tag 'teaser'."""
    try:
        VIS = jload('meta/vision.json', {})
    except SystemExit:
        VIS = {}
    def aes(e):
        v = [x['aes'] for x in VIS.get(e['file'], [])[int(e['ss']):int(e['ss'] + e['dur']) + 1] if x.get('aes') is not None]
        return float(np.mean(v)) if v else 0.0
    out, parts = [], list(dict.fromkeys(part_of[e['seg']] for e in edl))
    for p in parts:
        shots = [e for e in edl if part_of[e['seg']] == p]
        want = chosen.get(str(p)) or chosen.get('all' if p is None else '') or []
        if want:
            pick = [next(e for e in shots if e['file'] == f) for f in want if any(e['file'] == f for e in shots)]
        else:
            cand = sorted([e for e in shots if e['q'] == 3 and e.get('speed', 1.0) == 1.0 and not e['portrait']
                           and e['tag'] not in ('screen', 'dual-selfie')], key=aes, reverse=True)
            pick, seen = [], set()
            for e in cand:
                if e['seg'] in seen: continue
                pick.append(e); seen.add(e['seg'])
                if len(pick) * TEASER_SHOT >= TEASER_LEN: break
            pick.sort(key=lambda e: edl.index(e))
        for e in pick:
            mid = e['ss'] + e['dur'] * e.get('speed', 1.0) / 2
            out.append(dict(e, ss=round(max(e['ss'], mid - TEASER_SHOT / 2), 2), dur=min(TEASER_SHOT, e['dur']), seg=shots[0]['seg'],
                            subject='teaser_' + e['subject'], tag='teaser', speed=1.0))
        out += shots
    print(f"cold open: {sum(1 for e in out if e['tag'] == 'teaser')} teaser shots in {len(parts)} part(s)")
    return out

def main():
    L = jload('locations.json'); I = jload('intents.json'); IDX = {r['file']: r for r in jload('meta/index.json')}
    SP = jload('meta/speech.json', {}); dual = set(L.get('dual_selfie', []))
    global SUBS
    SUBS = jload('subtitles.json', {}) if CFG.get('subtitles', False) and os.path.exists(P('subtitles.json')) else None
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
        r = IDX[o['file']]; words = SP.get(o['file'], {}).get('words', []); segs_ = SP.get(o['file'], {}).get('segs', [])
        w = o['win'] or [0.3, r['dur'] - 0.3]
        if o.get('speech_ok'): words, segs_ = [], []       # Claude listened: announcements / a guide / chatter, nothing to keep whole
        has_speech = o['file'] in dual or any(w[0] <= ws <= w[1] for ws, _, _ in words)
        speed = clamp_speed(o['file'], float(o.get('speed', 1.0)), has_speech)
        if o.get('exact'):                                  # Claude/user set the exact moment (e.g. a build-up that
            ss, dd = round(w[0], 2), round(min(w[1], r['dur'] - 0.05) - w[0], 2)   # must not be trimmed): keep as is
        else:
            ss, dd = refine(o['file'], w, o['q'], r['dur'], has_speech, words, segs[order[seg]].get('max_shot'), segs_, speed)
        dd = round(dd / speed, 2)                           # timeline length (source window / speed)
        if dd < MIN_LEN: continue
        base = dict(file=o['file'], ss=ss, dur=dd, seg=seg, subject=subj, q=o['q'], time=r['time'], portrait=r['portrait'],
                    hdr=r['hdr'], tag='screen' if r.get('screen') else ('dual-selfie' if o['file'] in dual else ''), note=o.get('note', ''),
                    exact=bool(o.get('exact')), speed=speed, order=(IDX[o['after']]['time'], 1) if o.get('after') in IDX else (r['time'], 0))
        # only speech worth subtitling (the reviewed subtitles.json: filmmaker, companions, a guide) is tightened;
        # strangers, announcements and mumbles must never cut a visual shot apart
        talk = [w for w in SP.get(o['file'], {}).get('words', []) if any(c['start'] - 0.3 <= w[0] <= c['end'] + 0.3 for c in SUBS.get(o['file'], []))] \
            if SUBS is not None else SP.get(o['file'], {}).get('words', [])
        pieces = tighten(o['file'], ss, dd, talk) if speed == 1.0 and talk and not o.get('keep_pauses') \
            and CFG.get('speech_tighten', True) else [(ss, dd)]
        for k, (a, d) in enumerate(pieces):
            edl.append(dict(base, ss=a, dur=d, subject=subj if len(pieces) == 1 else f'{subj}#{k + 1}', split=len(pieces) > 1))
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
            if v is not None and e['tag'] not in ('dual-selfie', 'screen') and not e.get('exact') and not e.get('split') and any(
                    k[1] is not None and float(v @ k[1]) > (0.965 if e['q'] == 3 else thr) and k[0]['q'] >= e['q'] for k in keep):
                dropped.append(e); continue
            keep.append((e, v))
    edl = [e for e in edl if e not in dropped]
    if dropped: print(f'look-alike pass removed {len(dropped)} shots: ' + ', '.join(f"{e['file'][:-4]}({e['subject']})" for e in dropped[:12]) + (' …' if len(dropped) > 12 else ''))
    # 3) aerial windows (optional: only projects with plane-window / observation-deck / drone footage list them)
    for s in segs:
        for k, (f, a, b, note) in enumerate(s.get('aerial', s.get('plane', []))):
            r = IDX[f]
            edl.append(dict(file=f, ss=a, dur=round(b - a, 2), seg=s['id'], subject=f'aerial_{k}', q=3, time=r['time'], portrait=False,
                            hdr=r['hdr'], tag='aerial', note=note, aerial_order=k, order=(r['time'], 0)))
    edl.sort(key=lambda e: (order[e['seg']], e.get('aerial_order', 0), e['order'], e['ss']))
    for e in edl: e.pop('order')
    edl = [e for e in edl if e['dur'] >= MIN_LEN]
    part_of = {s['id']: s.get('part') for s in segs}
    if CFG.get('end_card'):                                 # room for the end card on the last shot of each part
        last = {}
        for i, e in enumerate(edl): last[part_of[e['seg']]] = i
        for i in last.values():
            e = edl[i]
            if e.get('speed', 1.0) == 1.0 and e['dur'] < 7.0:
                e['dur'] = round(min(7.0, IDX[e['file']]['dur'] - 0.05 - e['ss']), 2)
    if CFG.get('cold_open'):
        edl = add_teasers(edl, part_of, L.get('teaser', {}))
    total = sum(e['dur'] for e in edl)
    jsave('meta/edl.json', dict(target=CFG.get('target_minutes', 0) * 60, total=round(total, 1), segments=segs, edl=edl))
    lines = ['# Edit list', f'{total / 60:.1f} min, {len(edl)} shots (target ~{CFG.get("target_minutes", "?")} min — a guide, not a rule)', '']
    t = 0; cur = None
    for e in edl:
        if e['seg'] != cur:
            cur = e['seg']; s = segs[order[cur]]
            lines.append(f"\n## {s.get('place') or s['id']} — {s.get('city', '')}{'  [NEW CITY]' if s.get('new_city') else ''}")
        sp = f"  [{e['speed']:g}x]" if e.get('speed', 1.0) != 1.0 else ''
        lines.append(f"- {int(t // 60):02d}:{t % 60:04.1f}  {e['file']}  {e['ss']:.1f}s +{e['dur']:.1f}s{sp}  q{e['q']}  {e['subject']}  {e['note']}")
        t += e['dur']
    parts = {}
    for e in edl: parts.setdefault(segs[order[e['seg']]].get('part'), []).append(e['dur'])
    if any(p is not None for p in parts):
        summary = ', '.join(f"part {p}: {sum(d) / 60:.1f} min" for p, d in sorted(parts.items(), key=lambda x: (x[0] is None, x[0] or 0)))
        lines.insert(2, f'Split into parts — {summary}'); print('  ' + summary)
        if None in parts: print('  WARNING: some segments have no "part" — they are in no part film')
    elif total > float(CFG.get('split_minutes', 60)) * 60:
        print(f'  RECOMMEND SPLITTING: {total / 60:.0f} min is long for one video. Propose parts (by chronology, city, theme '
              f'or event, each ~20-45 min) to the user; on approval set "part": N on every segment in locations.json.')
    open(P('EDIT_LIST.md'), 'w').write('\n'.join(lines))
    print(f'{len(edl)} shots, {total / 60:.1f} min → meta/edl.json, EDIT_LIST.md')

if __name__ == '__main__':
    main()
