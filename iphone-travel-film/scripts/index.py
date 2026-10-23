"""Step 1 — index every clip: capture time (local), GPS, duration, fps, orientation, HDR, lens.

iPhone .MOV files carry com.apple.quicktime.location.ISO6709 and creationdate (with local UTC offset).
Clips without GPS inherit the position of the nearest clip in time (flagged gps_inferred).
Screen recordings (flagged screen=true) only carry a UTC creation_time: their local time comes from the iOS file
name ("ScreenRecording_MM-DD-YYYY HH-MM-SS"), else from the UTC offset of the nearest camera clip.
Exact duplicates ("IMG_0837 2.MOV": same capture time and length as IMG_0837.MOV) are skipped.
Output: meta/index.json (sorted by capture time)."""
import datetime, glob, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SRC, P, jsave, probe, NOROT
from tqdm import tqdm

EXT = ('.mov', '.mp4', '.m4v')
SCREEN_NAME = re.compile(r'ScreenRecording_(\d\d)-(\d\d)-(\d{4}) (\d\d)-(\d\d)-(\d\d)')
SCREEN_ANY = re.compile(r'^(ScreenRecording_|RPReplay_|Screen Recording )', re.I)

def _local(s):
    """'2024:11:22 15:54:14+09:00' or ISO → (naive local datetime, UTC offset in minutes or None)."""
    if s[4] == ':': s = s.replace(':', '-', 2).replace(' ', 'T', 1)
    t = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    off = t.utcoffset()
    return t.replace(tzinfo=None), (off.total_seconds() / 60 if off is not None else None)

def main():
    files = sorted(f for f in os.listdir(SRC) if f.lower().endswith(EXT) and not f.startswith('.'))
    if not files: sys.exit(f'no videos found in {SRC}')
    print(f'{len(files)} videos in source folder')
    ex = json.loads(subprocess.run(['exiftool', '-j', '-n', '-api', 'LargeFileSupport=1', '-FileName', '-Duration',
                                    '-GPSLatitude', '-GPSLongitude', '-GPSAltitude', '-CreationDate', '-Model',
                                    '-LensModel', SRC], capture_output=True, text=True).stdout or '[]')
    ex = {x['FileName']: x for x in ex}
    with ThreadPoolExecutor(8) as pool:
        list(tqdm(pool.map(probe, files), total=len(files), desc='Probing clips', unit='clip'))
    out = []
    for f in files:
        x = ex.get(f, {}); p = probe(f)
        v = [s for s in p['streams'] if s['codec_type'] == 'video']
        if not v: continue
        v = v[0]; n, d = map(int, v['r_frame_rate'].split('/'))
        rot = next((sd['rotation'] for sd in v.get('side_data_list', []) if 'rotation' in sd), 0)
        tags = p['format'].get('tags', {})
        loc = x.get('CreationDate') or tags.get('com.apple.quicktime.creationdate')
        off, utc = None, None
        try:
            if loc:
                t, off = _local(str(loc))
            elif SCREEN_NAME.match(f):          # iOS names screen recordings with the phone's local time
                mo, d_, y, hh, mi, se = map(int, SCREEN_NAME.match(f).groups()); t = datetime.datetime(y, mo, d_, hh, mi, se)
            else:                               # only UTC known: shifted to local time below
                t, _ = _local(tags['creation_time']); utc = True
        except Exception:
            t = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(SRC, f)))
        w, h = v['width'], v['height']
        out.append(dict(file=f, time=t.isoformat(), dur=float(p['format']['duration']), fps=n / d,
                        portrait=((abs(rot) == 90) != (h > w)) and f not in NOROT, hdr=v.get('color_transfer') == 'arib-std-b67',
                        lat=x.get('GPSLatitude'), lon=x.get('GPSLongitude'), alt=x.get('GPSAltitude'),
                        model=x.get('Model', ''), lens=x.get('LensModel', ''), screen=bool(SCREEN_ANY.match(f)),
                        audio=any(s['codec_type'] == 'audio' and s['codec_name'] == 'aac' for s in p['streams']),
                        _off=off, _utc=utc))
    # UTC-only clips take the UTC offset of the nearest clip (in UTC) that has one
    known = [(datetime.datetime.fromisoformat(r['time']) - datetime.timedelta(minutes=r['_off']), r['_off'])
             for r in out if r['_off'] is not None]
    for r in out:
        if r['_utc'] and known:
            T = datetime.datetime.fromisoformat(r['time'])
            o = min(known, key=lambda k: abs(k[0] - T))[1]
            r['time'] = (T + datetime.timedelta(minutes=o)).isoformat()
    # exact duplicates (Photos export copies "IMG_0837 2.MOV"): same capture time and length → keep one
    seen, dups = {}, []
    for r in sorted(out, key=lambda r: (len(r['file']), r['file'])):
        k = (r['time'], round(r['dur'], 2))
        if k in seen: dups.append(r['file'])
        else: seen[k] = r['file']
    out = [r for r in out if r['file'] not in dups]
    for r in out: r.pop('_off'); r.pop('_utc')
    out.sort(key=lambda r: r['time'])
    have = [r for r in out if r['lat'] is not None]
    for r in out:
        if r['lat'] is None and have:
            T = datetime.datetime.fromisoformat(r['time'])
            nb = min(have, key=lambda o: abs(datetime.datetime.fromisoformat(o['time']) - T))
            r['lat'], r['lon'], r['gps_inferred'] = nb['lat'], nb['lon'], True
    jsave('meta/index.json', out)
    mins = sum(r['dur'] for r in out) / 60
    print(f"indexed {len(out)} clips, {mins:.0f} min of footage, {sum(r['portrait'] for r in out)} vertical, "
          f"{sum(not r['hdr'] for r in out)} SDR, {sum(r['screen'] for r in out)} screen recordings, "
          f"{sum(r.get('gps_inferred', False) for r in out)} without GPS, {len(dups)} exact duplicates skipped")
    print(f"dates {out[0]['time'][:10]} → {out[-1]['time'][:10]}")

if __name__ == '__main__':
    main()
