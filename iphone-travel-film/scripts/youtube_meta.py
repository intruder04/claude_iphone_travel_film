"""Step 11 — YouTube upload text: chapters computed from the final edit, plus a renders/YOUTUBE.md skeleton.

  youtube_meta.py            writes renders/YOUTUBE.md (next to the film) with exact chapter timestamps (from meta/edl.json) and the facts
                             Claude needs (route, cities, dates, camera, length, HDR) — Claude then writes the
                             title options, the description and the tags into it (see SKILL.md step 11)

YouTube rules applied: first chapter at 00:00, at least 3 chapters, each ≥ 10 s (shorter ones are merged);
tags total ≤ 500 characters; 3 hashtags at the end of the description show above the title."""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, P, jload, edl_shots, part_suffix, PART

CH_MIN = 40.0     # a place shown this long gets its own chapter even without an on-screen title

def chapters():
    """Chapters from the edit: a cold-open teaser is 'Highlights'; after it, every stretch of one place that lasts
    ≥ CH_MIN seconds (or carries an on-screen title) starts a chapter. Short in-between stretches stay inside the
    previous chapter, so every minute of the film is covered and labels match what is on screen."""
    E, edl = edl_shots(); S = {s['id']: s for s in E['segments']}
    blocks = []                                                  # [start, dur, label, titled]
    t = 0.0
    for e in edl:
        s = S[e['seg']]; tz = e.get('tag') == 'teaser'
        label = 'Highlights' if tz else s.get('place') or s['id']
        if not tz and s.get('new_city') and s.get('city') and not label.lower().startswith(s['city'].lower()):
            label = f"{s['city']} — {label}"
        if blocks and blocks[-1][2].split(' — ')[-1] == label.split(' — ')[-1]: blocks[-1][1] += e['dur']
        else: blocks.append([t, e['dur'], label, bool(s.get('title')) and not tz])
        t += e['dur']
    ch = []
    for a, d, lab, titled in blocks:
        if ch and ch[-1][1] == lab: continue
        if not ch or titled or d >= CH_MIN or lab == 'Highlights': ch.append([a, lab])
    out = []
    for i, (a, lab) in enumerate(ch):                            # YouTube: each chapter ≥ 10 s
        nxt = ch[i + 1][0] if i + 1 < len(ch) else t
        if out and nxt - a < 10: continue
        out.append([a, lab])
    if out: out[0][0] = 0.0
    return out, t, edl, S

def main():
    ch, total, edl, S = chapters()
    idx = jload('meta/index.json')
    d0, d1 = idx[0]['time'][:10], idx[-1]['time'][:10]
    days = (datetime.date.fromisoformat(d1) - datetime.date.fromisoformat(d0)).days + 1
    cities = list(dict.fromkeys(S[e['seg']].get('city', '') for e in edl if S[e['seg']].get('city')))
    models = sorted({r.get('model', '') for r in idx if r.get('model')})
    stamp = lambda s: f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}" if total >= 3600 else f"{int(s // 60):02d}:{int(s % 60):02d}"
    lines = ['# YouTube upload text', '',
             f'<!-- facts for Claude: {days} days ({d0} → {d1}); route {" → ".join(cities)}; camera {", ".join(models)}; '
             f'film {total / 60:.1f} min, 4K 60fps HLG HDR; music: {"yes" if CFG.get("music") else "none (original sound)"} -->', '',
             '## Title options', '- TODO: 10+ options, ≤ 70 chars, grouped: search-first (place + 4K HDR up front), story/feeling, '
             'specific hook (a concrete moment from the film), calm/ambient if there is no narration/music. Recommend one + a test partner.', '',
             '## Description', 'TODO: 2–3 sentence summary of the trip and what the viewer will see.', '',
             f'📍 Route: {" → ".join(cities)}', f'🎥 Shot on {", ".join(models) or "iPhone"} · 4K 60fps · HDR', '',
             'CHAPTERS'] + [f'{stamp(a)} {lab}' for a, lab in ch] + ['', 'TODO: 3 hashtags', '',
             '## Tags (comma-separated, ≤ 500 characters)', 'TODO']
    if PART: lines.insert(2, f'<!-- this is Part {PART} of a split film: say so in the titles and link the other parts in the description -->')
    out = f'YOUTUBE{part_suffix()}.md'
    open(P('renders', out), 'w').write('\n'.join(lines))
    print(f'{len(ch)} chapters → renders/{out} (fill in the TODOs)')

if __name__ == '__main__':
    main()
