"""Step 5 — render the 4 title styles on one of the user's own shots so they can choose.

  title_demos.py SEGMENT_ID [CLIP START]
Uses the segment's names from locations.json (as a new-city card) over CLIP from START (default: the first clip of
the segment). Writes previews/title_<style>_SDR.mp4 (animated) and previews/title_styles.jpg (2x2 still sheet)."""
import datetime, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ProcessPoolExecutor
from common import FF, P, jload, CFG
from tqdm import tqdm

def _one(args):
    from compose import render, preview
    import gfx
    name, seg, info = args
    out = P('tmp', f'title_{name}.mov')
    render(seg, out, lambda t: gfx.STYLES[name](info, t - 0.4, dur=5.6))
    preview(out, P('previews', f'title_{name}_SDR.mp4')); os.remove(out)
    return name

def main():
    import gfx
    L = jload('locations.json'); sid = sys.argv[1] if len(sys.argv) > 1 else next(s['id'] for s in L['segments'] if s.get('title'))
    s = next(x for x in L['segments'] if x['id'] == sid)
    idx = {r['file']: r for r in jload('meta/index.json')}
    clip = sys.argv[2] if len(sys.argv) > 2 else s['from']; start = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    r = idx[clip]
    info = dict(city=s.get('city', ''), city_local=s.get('city_local', ''), place=s.get('place', ''),
                place_local=s.get('place_local', ''), country=s.get('country', ''), new_city=True,
                date=datetime.datetime.fromisoformat(r['time']).strftime(CFG.get('date_format', '%-d %B %Y')),
                coords=f"{abs(r['lat']):.3f}° {'N' if r['lat'] >= 0 else 'S'}  {abs(r['lon']):.3f}° {'E' if r['lon'] >= 0 else 'W'}" if r.get('lat') is not None else '')
    seg = dict(file=clip, ss=start, dur=min(6.5, r['dur'] - start - 0.1), portrait=r['portrait'], hdr=r['hdr'])
    with ProcessPoolExecutor(2) as ex:
        list(tqdm(ex.map(_one, [(n, seg, info) for n in gfx.STYLES]), total=len(gfx.STYLES), desc='Rendering title styles', unit='style'))
    ins = sum((['-ss', '3', '-i', P('previews', f'title_{n}_SDR.mp4')] for n in gfx.STYLES), [])
    lab = ';'.join(f"[{i}]scale=960:-2,drawtext=text='{n[0]}':x=20:y=20:fontsize=44:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=10[v{i}]"
                   for i, n in enumerate(gfx.STYLES))
    subprocess.run([FF, '-v', 'error', '-y', *ins, '-filter_complex', lab + ';[v0][v1][v2][v3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0',
                    '-frames:v', '1', P('previews', 'title_styles.jpg')])
    print('previews/title_styles.jpg + previews/title_*_SDR.mp4')

if __name__ == '__main__':
    main()
