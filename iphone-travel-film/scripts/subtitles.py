"""Step 8c — burned-in subtitles for what is said on camera (project.json "subtitles": true).

  subtitles.py draft          cues from the speech word timestamps (Parakeet / Whisper) of every shot in the edit →
                              subtitles.draft.json + review/subtitles_review.md (clip, clip time, language, text)
  subtitles.py sample CLIP T  previews/subtitle_sample.jpg: the subtitle style over a real frame (SDR) to check
  subtitles.py srt            renders/<output_name>.srt on the film's timeline (upload to YouTube as captions too)

Claude reads review/subtitles_review.md, listens where needed, and writes subtitles.json (same format as the draft):
fix misheard words and names, drop speech that isn't the filmmaker's or their companions' (announcements, strangers,
background chatter) unless it matters, and translate when project.json "subtitle_language" differs from the spoken
language. Only subtitles.json is ever burned in — an unreviewed draft never reaches the film.
  {"IMG_0001.MOV": [{"start": 3.12, "end": 5.80, "text": "This is our first ramen in Japan"}, ...]}
Times are clip seconds, so cues survive re-edits. render_all.py draws the cues that fall inside each shot."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, P, jload, jsave, edl_shots, grab, part_suffix

MAX_CHARS, MAX_DUR, MIN_DUR, PAUSE = 84, 6.0, 1.2, 0.7
CJK = ('ja', 'zh', 'ko')

def cues_for(words, lang, a=0.0, b=1e9):
    """Group words fully inside [a, b] into readable cues: ≤ 2 lines, ≤ 6 s, split at sentence ends and pauses."""
    ws = [w for w in words if w[0] >= a - 0.05 and w[1] <= b + 0.1 and w[2]]
    sep = '' if lang in CJK else ' '
    out, cur = [], []
    def flush():
        if cur: out.append(dict(start=cur[0][0], end=cur[-1][1], text=sep.join(w[2] for w in cur).strip()))
    for w in ws:
        if cur:
            txt = sep.join(x[2] for x in cur + [w])
            if (w[0] - cur[-1][1] > PAUSE or len(txt) > MAX_CHARS or w[1] - cur[0][0] > MAX_DUR
                    or cur[-1][2][-1:] in '.?!。？！'):
                flush(); cur = []
        cur.append(w)
    flush()
    for i, c in enumerate(out):                        # readable minimum on screen, never overlapping the next cue
        nxt = out[i + 1]['start'] - 0.05 if i + 1 < len(out) else b
        c['end'] = round(min(max(c['end'] + 0.25, c['start'] + MIN_DUR), nxt), 2); c['start'] = round(c['start'], 2)
    return out

def draft():
    SP = jload('meta/speech.json', {}); _, shots = edl_shots()
    res, lines = {}, ['# Subtitles to review', 'Fix wording, drop speech that should not be subtitled, translate if asked, '
                      'then save as subtitles.json (clip-time cues).', '']
    for sh in shots:
        sp = SP.get(sh['file'])
        if not sp or not sp.get('words') or sh.get('speed', 1.0) != 1.0 or sh.get('tag') == 'teaser': continue
        cs = cues_for(sp['words'], sp.get('lang'), sh['ss'], sh['ss'] + sh['dur'])
        if not cs: continue
        res.setdefault(sh['file'], [])
        res[sh['file']] += [c for c in cs if c not in res[sh['file']]]
        lines.append(f"## {sh['file']}  (shot {sh['ss']:.1f}s +{sh['dur']:.1f}s, {sh['seg']}, language {sp.get('lang')})")
        lines += [f"- {c['start']:6.2f}–{c['end']:6.2f}  {c['text']}" for c in cs] + ['']
    jsave('subtitles.draft.json', res); open(P('review', 'subtitles_review.md'), 'w').write('\n'.join(lines))
    have = jload('subtitles.json', {}) if os.path.exists(P('subtitles.json')) else {}
    missing = [c for c in res if c not in have]
    print(f'{sum(len(v) for v in res.values())} cues in {len(res)} shots → subtitles.draft.json, review/subtitles_review.md')
    if missing: print(f'{len(missing)} clips with speech are not in subtitles.json yet: ' + ', '.join(missing[:15]) + (' …' if len(missing) > 15 else ''))

def sample(clip, t):
    import gfx
    from PIL import Image
    t = float(t); im = grab(clip, t, 3840, 2160).convert('RGBA')
    cues = jload('subtitles.json', {}).get(clip) or jload('subtitles.draft.json', {}).get(clip) or \
        [dict(start=t - 1, end=t + 1, text='Sample subtitle that is long enough to need two lines on the screen')]
    ov = gfx.subtitle(cues, t) or gfx.subtitle([dict(start=t - 1, end=t + 1, text='(no cue at this time)')], t)
    r, g, b, a = ov.split(); up = lambda ch: ch.point(lambda v: min(255, int(v * 255 / 191)))   # HLG 75 % white → SDR white
    im.alpha_composite(Image.merge('RGBA', (up(r), up(g), up(b), a)))
    im.convert('RGB').resize((1920, 1080)).save(P('previews', 'subtitle_sample.jpg'), quality=88)
    print(P('previews', 'subtitle_sample.jpg'))

def srt():
    S = jload('subtitles.json'); _, shots = edl_shots(); t0, n, out = 0.0, 0, []
    def ts(x): return f'{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round(x % 1 * 1000)) % 1000:03d}'
    for sh in shots:
        for c in (S.get(sh['file'], []) if sh.get('speed', 1.0) == 1.0 and sh.get('tag') != 'teaser' else []):
            a, b = max(c['start'], sh['ss']), min(c['end'], sh['ss'] + sh['dur'])
            if b - a < 0.3: continue
            n += 1; out.append(f"{n}\n{ts(t0 + a - sh['ss'])} --> {ts(t0 + b - sh['ss'])}\n{c['text']}\n")
        t0 += sh['dur']
    f = P('renders', f"{CFG.get('output_name', 'Travel_Film')}{part_suffix()}.srt"); open(f, 'w').write('\n'.join(out)); print(f'{n} cues → {f}')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'draft'
    if cmd == 'draft': draft()
    elif cmd == 'sample': sample(sys.argv[2], sys.argv[3])
    elif cmd == 'srt': srt()
    else: sys.exit(__doc__)
