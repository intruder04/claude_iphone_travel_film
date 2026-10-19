"""Step 11 — YouTube upload text: chapters computed from the final edit, plus a renders/YOUTUBE.md skeleton.

  youtube_meta.py            writes renders/YOUTUBE.md (next to the film) with exact chapter timestamps (from meta/edl.json) and the facts
                             Claude needs (route, cities, dates, camera, length, HDR) — Claude then writes the
                             title options, the description and the tags into it (see SKILL.md step 11)

YouTube rules applied: first chapter at 00:00, at least 3 chapters, each ≥ 10 s (shorter ones are merged);
tags total ≤ 500 characters; 3 hashtags at the end of the description show above the title."""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, P, jload, edl_shots

def chapters():
    E, edl = edl_shots(); S = {s['id']: s for s in E['segments']}
    t, prev, ch = 0.0, None, []
    for e in edl:
        s = S[e['seg']]
        if e['seg'] != prev and s.get('title') and s.get('place'):
            label = s['place'] if not s.get('new_city') or s['place'].lower().startswith(s.get('city', '').lower()) \
                else f"{s.get('city')} — {s['place']}"
            ch.append([t, label])
        prev = e['seg']; t += e['dur']
    out = []
    for i, (a, lab) in enumerate(ch):
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
             '## Title options', '- TODO (3 options, ≤ 70 characters, place names + "4K HDR"; no clickbait)', '',
             '## Description', 'TODO: 2–3 sentence summary of the trip and what the viewer will see.', '',
             f'📍 Route: {" → ".join(cities)}', f'🎥 Shot on {", ".join(models) or "iPhone"} · 4K 60fps · HDR', '',
             'CHAPTERS'] + [f'{stamp(a)} {lab}' for a, lab in ch] + ['', 'TODO: 3 hashtags', '',
             '## Tags (comma-separated, ≤ 500 characters)', 'TODO']
    open(P('renders', 'YOUTUBE.md'), 'w').write('\n'.join(lines))
    print(f'{len(ch)} chapters → renders/YOUTUBE.md (fill in the TODOs)')

if __name__ == '__main__':
    main()
