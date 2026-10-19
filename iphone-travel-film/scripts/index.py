"""Step 1 — index every clip: capture time (local), GPS, duration, fps, orientation, HDR, lens.

iPhone .MOV files carry com.apple.quicktime.location.ISO6709 and creationdate (with local UTC offset).
Clips without GPS inherit the position of the nearest clip in time (flagged gps_inferred).
Output: meta/index.json (sorted by capture time)."""
import datetime, glob, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SRC, P, jsave, probe
from tqdm import tqdm

EXT = ('.mov', '.mp4', '.m4v')

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
        t = x.get('CreationDate') or p['format'].get('tags', {}).get('com.apple.quicktime.creationdate') \
            or p['format'].get('tags', {}).get('creation_time')
        try:
            t = datetime.datetime.strptime(t.replace(':', '-', 2)[:19], '%Y-%m-%d %H:%M:%S') if t[4] == ':' \
                else datetime.datetime.fromisoformat(t[:19])
        except Exception:
            t = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(SRC, f)))
        w, h = v['width'], v['height']
        out.append(dict(file=f, time=t.isoformat(), dur=float(p['format']['duration']), fps=n / d,
                        portrait=(abs(rot) == 90) != (h > w), hdr=v.get('color_transfer') == 'arib-std-b67',
                        lat=x.get('GPSLatitude'), lon=x.get('GPSLongitude'), alt=x.get('GPSAltitude'),
                        model=x.get('Model', ''), lens=x.get('LensModel', ''),
                        audio=any(s['codec_type'] == 'audio' and s['codec_name'] == 'aac' for s in p['streams'])))
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
          f"{sum(not r['hdr'] for r in out)} SDR, {sum(r.get('gps_inferred', False) for r in out)} without GPS")
    print(f"dates {out[0]['time'][:10]} → {out[-1]['time'][:10]}")

if __name__ == '__main__':
    main()
