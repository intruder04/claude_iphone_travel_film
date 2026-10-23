"""Step 9 — assemble the full film from meta/edl.json.

  - every shot is rendered to renders/shots/NNN.mov (HLG HEVC 10-bit 60p, PCM audio) with a fingerprint of its inputs
    (clip window, title text, fades, rotation, animal labels, style, graphics code); a cached shot is reused only when
    the fingerprint matches, so edits can never leave stale titles/labels — just re-run
  - if intents.json / locations.json are newer than meta/edl.json the plan is rebuilt first
  - a location title only on the first shot of a segment with "title": true; segments with "new_city" get the
    cinematic card (B by default, project.json city_change_style) as a chapter marker
  - city changes: the last shot of a city fades to black with the sound fading out, the first shot of the new city
    fades in from black (sound fading in) under the city card
  - animal labels (meta/animal_labels.json, keyed by clip + clip time) and horizon fixes (meta/rotate.json, keyed by
    clip) are applied wherever that clip is used
  - any shot of a clip that has landmarks/<clip>_callouts.mov (tracked 📍 labels, landmarks.py) is cut from it
  - teaser shots (cold open, edl tag "teaser") carry no titles, labels or subtitles; the film / part card comes on the
    first real shot, which fades in from black
  - project.json "day_counter": true prefixes the title date with "Day N" (day 1 = date of the first shot)
  - project.json "end_card": true puts an end card on the last shot: "Next: Part N" in a split film, trip facts at the end
  - speed changes (edl "speed"): slow motion without a badge; sped-up shots carry a "4×" badge for their whole length.
    Subtitles and animal labels (clip-time based) are only drawn on normal-speed shots
  - subtitles (subtitles.json, clip-time cues reviewed by Claude; project.json "subtitles": true) are burned in at the
    bottom centre; while a lower-third / pin / vertical title is on screen they move to the top
  - shots are joined losslessly (concat demuxer) and the audio is loudness-normalised (-14 LUFS, YouTube)
Memory-safe: at most JOBS shots in flight (default 2), each ffmpeg under the RSS watchdog.
Split films: TRAVEL_FILM_PART=N renders only the segments with "part": N (its own fades, a "Part N" line on its first
card) into <output_name>_PartN_HDR.mp4.
Usage: render_all.py [TITLE_STYLE]   (A_lower_third | B_cinematic | C_map_pin | D_vertical; default project.json title_style)
"""
import json, os, sys, subprocess, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tqdm import tqdm
from compose import render, run
from common import FF, HLG_TAGS, CFG, P, PART, part_suffix
import gfx

W = P()
STYLE = sys.argv[1] if len(sys.argv) > 1 else CFG.get('title_style', 'A_lower_third')
JOBS = int(os.environ.get('JOBS', 2))
OUT = f'{W}/renders'; SH = f'{OUT}/shots'; os.makedirs(SH, exist_ok=True)
# never render a stale plan: if intents/locations/animals changed after the edit list was built, rebuild it first
def _fresh():
    edl = f'{W}/meta/edl.json'; srcs = [f'{W}/{n}' for n in ('intents.json', 'locations.json')]
    if os.path.exists(edl) and any(os.path.exists(s) and os.path.getmtime(s) > os.path.getmtime(edl) for s in srcs):
        here = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(f'{W}/intents.json'):
            print('Step 1/3: edit inputs changed → rebuilding edit list and re-tracking animal labels (~2 min, no % bar)…')
            subprocess.run([sys.executable, '-I', os.path.join(here, 'edit_plan.py')], check=True)
            if os.path.exists(f'{W}/animals.json'):
                subprocess.run([sys.executable, '-I', os.path.join(here, 'animals.py'), 'track'], check=True)
_fresh()
E = json.load(open(f'{W}/meta/edl.json'))
E['edl'] = [e for e in E['edl'] if e['dur'] >= 2.0]          # no sub-2s flash cuts
# location data is read live from locations.json (the copy inside edl.json can be stale after title/desc edits)
try: SEGS = {s['id']: s for s in json.load(open(f'{W}/locations.json'))['segments']}
except (FileNotFoundError, KeyError): SEGS = {s['id']: s for s in E['segments']}
if PART:                                                     # one part of a split film
    E['edl'] = [e for e in E['edl'] if SEGS.get(e['seg'], {}).get('part') == PART]
    if not E['edl']: sys.exit(f'no shots with "part": {PART} in locations.json')
title_fn = gfx.STYLES[STYLE]
try: ANIMALS = json.load(open(f'{W}/meta/animal_labels.json'))     # {clip: [label with clip-time start/end, ...]}
except FileNotFoundError: ANIMALS = {}
try: ROT = json.load(open(f'{W}/meta/rotate.json'))        # {clip: PIL-convention degrees}
except FileNotFoundError: ROT = {}
SUBS = {}
if CFG.get('subtitles', False):
    try: SUBS = json.load(open(f'{W}/subtitles.json'))    # {clip: [{start, end, text}]} in clip seconds
    except FileNotFoundError: print('WARNING: "subtitles": true but subtitles.json is missing — run subtitles.py draft and review it')

DAY1 = datetime.date.fromisoformat(min(e['time'] for e in json.load(open(f'{W}/meta/edl.json'))['edl'])[:10])

def info_for(seg, shot):
    d = datetime.datetime.fromisoformat(shot['time'])
    lat, lon = seg.get('lat'), seg.get('lon')
    coords = f"{abs(lat):.3f}° {'N' if lat >= 0 else 'S'}  {abs(lon):.3f}° {'E' if lon >= 0 else 'W'}" if lat is not None else ''
    return dict(city=seg.get('city', ''), city_local=seg.get('city_local', ''), place=seg.get('place', ''),
                place_local=seg.get('place_local', ''), country=seg.get('country', ''), area=seg.get('area', ''), desc=seg.get('desc', ''),
                date=(f"Day {(d.date() - DAY1).days + 1}  ·  " if CFG.get('day_counter') else '') + d.strftime(CFG.get('date_format', '%-d %B %Y')),
                coords=coords, new_city=seg.get('new_city', False))

def end_card_info():
    """Text for the end card: the next part in a split film, else facts about the whole trip."""
    allsegs = list(SEGS.values())
    if PART and any(s.get('part') == PART + 1 for s in allsegs):
        nxt = next(s for s in allsegs if s.get('part') == PART + 1)
        return dict(kind='next', big=f'Next: Part {PART + 1}', small=nxt.get('part_title', ''))
    full = json.load(open(f'{W}/meta/edl.json'))['edl']
    days = (datetime.date.fromisoformat(max(e['time'] for e in full)[:10]) - DAY1).days + 1
    cities = list(dict.fromkeys(SEGS[e['seg']].get('city', '') for e in full if SEGS[e['seg']].get('country') == CFG.get('end_card_country', 'Japan')))
    places = len({SEGS[e['seg']]['place'] for e in full if SEGS[e['seg']].get('title')})
    return dict(kind='facts', big='Thanks for watching', small=f'{days} days  ·  {places} places  ·  ' + '  ·  '.join(c for c in cities if c))

FADE = float(CFG.get('city_fade_seconds', 1.0))
ENC_VERSION = 'vt-hevc-60M-80M-g120'   # part of every shot fingerprint: changing encoder settings re-renders all shots

def plan():
    jobs, seen = [], set(); edl = E['edl']
    city = [SEGS[e['seg']].get('city', '') for e in edl]
    tz = [e.get('tag') == 'teaser' for e in edl]
    first = next(i for i, t in enumerate(tz) if not t)  # first real shot: opens the film / part
    for i, sh in enumerate(edl):
        seg = SEGS[sh['seg']]; title = None
        want = seg.get('title_shot')                     # optional: the clip that should carry the title
        if not tz[i] and seg.get('title') and sh['seg'] not in seen and sh['dur'] >= 3.5 and (not want or sh['file'] == want):
            title = info_for(seg, sh); seen.add(sh['seg'])
        if PART and i == first:                          # a part opens on a chapter card that names the part
            title = dict(title or info_for(seg, sh), new_city=True)
            title['part'] = f"PART {PART}" + (f"  ·  {seg['part_title'].upper()}" if seg.get('part_title') else '')
        if tz[i]:                                        # teaser: short dips between shots, black before the film starts
            fi, fo = (0.5 if i == 0 else 0.12), (0.8 if i == first - 1 else 0.12)
        else:
            fi = 0.8 if i in (0, first) else (FADE if city[i] != city[i - 1] else 0)
            fo = 2.0 if i == len(edl) - 1 else (FADE if city[i] != city[i + 1] else 0)
        end = end_card_info() if CFG.get('end_card') and i == len(edl) - 1 else None
        jobs.append((i, sh, seg, title, fi, fo, end))
    return jobs

def do(job):
    i, sh, seg, title, fi, fo, end_card = job
    teaser = sh.get('tag') == 'teaser'
    callouts = f"{W}/landmarks/{sh['file']}_callouts.mov"
    # fingerprint of everything that shapes this shot; the cache file is named by its hash, so inserting or removing
    # shots elsewhere never invalidates it — only shots whose own inputs changed are rendered again
    speed = float(sh.get('speed', 1.0))
    fp = json.dumps(dict(sh={k: sh[k] for k in ('file', 'ss', 'dur', 'portrait', 'hdr')}, speed=speed, title=title, fi=fi, fo=fo,
                         rot=ROT.get(sh['file'], 0.0), animals=[(a['name'], a['start'], a['end']) for a in ANIMALS.get(sh['file'], [])],
                         subs=[] if teaser else SUBS.get(sh['file'], []), end=end_card, teaser=teaser,
                         callouts=os.path.getmtime(callouts) if os.path.exists(callouts) else None,
                         style=STYLE, gfx=os.path.getmtime(gfx.__file__), enc=ENC_VERSION), sort_keys=True, default=str)
    import hashlib
    out = f"{SH}/{hashlib.sha1(fp.encode()).hexdigest()[:16]}.mov"
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    s = dict(file=sh['file'], ss=sh['ss'], dur=sh['dur'], portrait=sh['portrait'], hdr=sh['hdr'],
             rotate=-ROT.get(sh['file'], 0.0), fade_in=fi, fade_out=fo, speed=speed)  # ffmpeg rotate is clockwise-positive, PIL ccw
    if os.path.exists(callouts):
        s['source'] = callouts                                          # pre-rendered 4K HLG clip with landmark pins
    layers, end, title_low = [], 0.0, None
    if title:
        tdur = min(5.0, sh['dur'] - 0.4)
        tf = gfx.STYLES[CFG.get('city_change_style', 'B_cinematic')] if title.get('new_city') else title_fn
        layers.append(lambda t, info=title, td=tdur, tf=tf: tf(info, t - 0.3, dur=td)); end = max(end, tdur + 0.5)
        if tf is not gfx.title_cinematic: title_low = (0.0, tdur + 0.5)   # titles that use the bottom of the frame
    labels = [dict(lb, start=lb['start'] - sh['ss'], end=min(lb['end'], sh['ss'] + sh['dur']) - sh['ss'],
                   track=lb['track']) for lb in ANIMALS.get(sh['file'], [])
              if lb['start'] < sh['ss'] + sh['dur'] - 0.5 and lb['end'] > sh['ss'] + 0.5 and lb.get('shot_ss') == sh['ss'] and speed == 1.0
              and not teaser]
    if labels:
        co = gfx.Callouts(marker='dot')                                 # animal labels: no pin, short
        def animal_layer(t, labels=labels, co=co):
            items = []
            for lb in labels:
                al = gfx.env(t, lb['start'], lb['end'], 0.35)
                if al > 0.01:
                    x, y = lb['track'][min(len(lb['track']) - 1, int(t * 60))]
                    items.append(dict(name=lb['name'], x=x, y=y, alpha=al, zone=(60, 60)))
            return co.frame(items, t) if items else None
        layers.append(animal_layer); end = max(end, max(lb['end'] for lb in labels) + 0.1)
    cues = [dict(start=round(c['start'] - sh['ss'], 3), end=round(min(c['end'], sh['ss'] + sh['dur'] - 0.05) - sh['ss'], 3), text=c['text'])
            for c in SUBS.get(sh['file'], []) if c['end'] > sh['ss'] + 0.3 and c['start'] < sh['ss'] + sh['dur'] - 0.3 and speed == 1.0
            and not teaser]
    if cues:
        for c in cues:                                  # a cue that meets a bottom title stays at the top for its whole time
            c['top'] = bool(title_low and c['start'] < title_low[1] and c['end'] > title_low[0])
        def sub_layer(t, cues=cues):
            c = next((c for c in cues if c['start'] - 0.06 <= t < c['end'] + 0.06), None)
            return gfx.subtitle([c], t, top=c['top']) if c else None
        layers.append(sub_layer); end = max(end, max(c['end'] for c in cues) + 0.1)
    if speed > 1.0 and CFG.get('speed_badge', True):
        layers.append(lambda t, sp=speed, d=sh['dur']: gfx.speed_badge(sp, t, d)); end = sh['dur']
    if end_card:
        t0 = max(0.0, sh['dur'] - 6.5)
        layers.append(lambda t, info=end_card, t0=t0, d=sh['dur']: gfx.end_card(info, t - t0, d - t0)); end = sh['dur']
    fn, rng = None, None
    if layers:
        def fn(t, layers=layers):
            ims = [im for im in (L(t) for L in layers) if im is not None]
            if not ims: return None
            base = ims[0]
            for im in ims[1:]: base.alpha_composite(im)
            return base
        rng = (0, min(sh['dur'], end))
    for attempt in range(3):                # VideoToolbox can refuse a session when the media engine is busy: retry
        try:
            render(s, out + '.tmp.mov', fn, rng); break
        except RuntimeError:
            if attempt == 2: raise
            import time; time.sleep(5)
    os.replace(out + '.tmp.mov', out); open(out + '.json', 'w').write(fp)
    return out

if __name__ == '__main__':
    jobs = plan()
    print(f'{len(jobs)} shots, {sum(j[1]["dur"] for j in jobs)/60:.1f} min, title style {STYLE}, {JOBS} parallel jobs, '
          f'{sum(1 for j in jobs if j[4] and j[0])} city changes')
    with ThreadPoolExecutor(JOBS) as ex:
        futs = [ex.submit(do, j) for j in jobs]
        for f in tqdm(as_completed(futs), total=len(futs), desc='Shots', unit='shot', dynamic_ncols=True,
                      bar_format='{desc} {percentage:3.0f}% {n}/{total} | left {remaining} | done {elapsed}'):
            f.result()
        paths = [f.result() for f in futs]
    lst = f'{OUT}/concat{part_suffix()}.txt'
    open(lst, 'w').write(''.join(f"file '{os.path.relpath(p, OUT)}'\n" for p in paths))
    print('Joining shots…')
    run([FF, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', f'{OUT}/joined{part_suffix()}.mov'], 'concat').wait()
    print('Measuring loudness…')
    r = subprocess.run([FF, '-hide_banner', '-i', f'{OUT}/joined{part_suffix()}.mov', '-vn', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
    m = json.loads(r[r.rindex('{'):r.rindex('}') + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    final = f"{OUT}/{CFG.get('output_name', 'Travel_Film')}{part_suffix()}_HDR.mp4"   # MP4, not MOV: YouTube ignored HDR in MOV (nclc colr)
    print('Final mux (video stream copied, Dolby Vision RPU stripped, audio normalised to -14 LUFS)…')
    run([FF, '-v', 'error', '-y', '-i', f'{OUT}/joined{part_suffix()}.mov', '-map', '0:v', '-map', '0:a', '-c:v', 'copy', '-bsf:v', 'dovi_rpu=strip=1', '-tag:v', 'hvc1',
         '-af', ln + ',aresample=48000', '-c:a', 'aac', '-b:a', '320k', *HLG_TAGS, '-movflags', '+faststart', final], 'final').wait()
    if CFG.get('sdr_preview', False):                      # optional: a 1080p SDR copy for checking on any screen
        from compose import preview
        preview(final, f"{W}/previews/{CFG.get('output_name', 'Travel_Film')}_preview_1080p_SDR.mp4")
    if os.path.exists(f'{OUT}/joined{part_suffix()}.mov'): os.remove(f'{OUT}/joined{part_suffix()}.mov')   # intermediate, as big as the film
    print('DONE', final)
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verify.py'), final])
