"""Step 2 — where was each clip shot? (needs the user's OK to send GPS coordinates to OpenStreetMap)

  * reverse-geocodes every distinct position with Nominatim at 4 zoom levels (POI / street / district / city),
    1 request per second as the Nominatim usage policy requires, cached in meta/geocache.json
  * groups clips into "visits" (same place within 700 m and 2.5 h)
  * asks Overpass for named attractions around each visit (temples, museums, parks, viewpoints, ...)
Output: meta/visits.json — the raw material Claude uses to write locations.json after looking at the footage.
Set "user_agent" in project.json to something that identifies you (Nominatim policy)."""
import datetime, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from common import CFG, P, jload, jsave
from tqdm import tqdm

UA = CFG.get('user_agent', 'iphone-travel-film-skill/1.0')
LANG = CFG.get('label_language', 'en')
S = requests.Session(); S.headers['User-Agent'] = UA

def dist(a, b):
    return 6371000 * math.hypot(math.radians(b[0] - a[0]), math.radians(b[1] - a[1]) * math.cos(math.radians(a[0])))

def reverse(cache, lat, lon, zoom):
    k = f'{lat:.4f},{lon:.4f},{zoom}'
    if k in cache: return cache[k]
    for _ in range(3):
        try:
            r = S.get('https://nominatim.openstreetmap.org/reverse', timeout=20,
                      params=dict(lat=lat, lon=lon, zoom=zoom, format='jsonv2', addressdetails=1, namedetails=1,
                                  extratags=1, **{'accept-language': LANG}))
            if r.ok: cache[k] = r.json(); break
        except requests.RequestException: pass
        time.sleep(2)
    time.sleep(1.1)
    return cache.get(k)

POI_Q = ('[out:json][timeout:25];(nwr(around:{r},{lat},{lon})[name]'
         '[~"^(tourism|historic|leisure|amenity|natural|railway|man_made)$"~"^(attraction|museum|viewpoint|gallery|zoo|'
         'aquarium|theme_park|artwork|shrine|temple|monument|castle|memorial|park|garden|nature_reserve|place_of_worship|'
         'station|marketplace|peak|beach|bridge|tower|cape|wood|island|waterfall|ruins|church|cathedral|mosque)$"];);out tags center 60;')
OVERPASS = ['https://overpass.private.coffee/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
            'https://overpass-api.de/api/interpreter']

def pois(cache, lat, lon, r=350):
    k = f'{lat:.4f},{lon:.4f}'
    if k in cache: return cache[k]
    for ep in OVERPASS * 2:
        try:
            rr = S.post(ep, data={'data': POI_Q.format(r=r, lat=lat, lon=lon)}, timeout=30)
            if rr.ok: cache[k] = rr.json()['elements']; break
        except (requests.RequestException, ValueError): pass
        time.sleep(2)
    time.sleep(1)
    return cache.get(k, [])

def main():
    idx = jload('meta/index.json')
    geo = jload('meta/geocache.json', {})
    spots = sorted({(round(r['lat'], 4), round(r['lon'], 4)) for r in idx if r['lat'] is not None})
    for lat, lon in tqdm(spots, desc='Reverse geocoding (Nominatim, 1 req/s)', unit='place'):
        for z in (18, 16, 14, 10): reverse(geo, lat, lon, z)
        jsave('meta/geocache.json', geo, None)
    T = lambda r: datetime.datetime.fromisoformat(r['time'])
    visits = []
    for r in idx:
        if r['lat'] is None: continue
        p = (r['lat'], r['lon'])
        if visits:
            v = visits[-1]
            if dist(v['center'], p) < 700 and (T(r) - T(v['clips'][-1])).total_seconds() < 2.5 * 3600:
                v['clips'].append(r); n = len(v['clips'])
                v['center'] = ((v['center'][0] * (n - 1) + p[0]) / n, (v['center'][1] * (n - 1) + p[1]) / n); continue
        visits.append(dict(clips=[r], center=p))
    oc = jload('meta/overpass.json', {})
    out = []
    for i, v in enumerate(tqdm(visits, desc='Nearby attractions (Overpass)', unit='visit')):
        els = pois(oc, *v['center']); jsave('meta/overpass.json', oc, None)
        named = []
        for e in els:
            t = e.get('tags', {}); c = e.get('center') or e
            if 'lat' not in c: continue
            kind = next((f'{k}={t[k]}' for k in ('tourism', 'historic', 'leisure', 'amenity', 'natural', 'railway', 'man_made') if k in t), '')
            named.append(dict(name=t.get(f'name:{LANG}') or t.get('name:en') or t.get('name'), local=t.get('name'),
                              kind=kind, m=round(dist(v['center'], (c['lat'], c['lon'])))))
        named.sort(key=lambda x: x['m'])
        g = geo.get(f"{round(v['clips'][0]['lat'], 4):.4f},{round(v['clips'][0]['lon'], 4):.4f},14", {}) or {}
        a = g.get('address', {})
        out.append(dict(id=i, start=v['clips'][0]['time'], end=v['clips'][-1]['time'], center=v['center'],
                        country=a.get('country'), city=a.get('city') or a.get('town') or a.get('village') or a.get('county'),
                        area=a.get('quarter') or a.get('suburb') or a.get('neighbourhood'),
                        files=[c['file'] for c in v['clips']], dur=round(sum(c['dur'] for c in v['clips']), 1), pois=named[:25]))
    jsave('meta/visits.json', out)
    print(f'{len(out)} visits:')
    for x in out:
        print(f"  #{x['id']:<3} {x['start'][5:16]}  {x['city']} / {x['area']}  {len(x['files'])} clips {x['dur']:.0f}s  "
              f"near: {', '.join(p['name'] for p in x['pois'][:4] if p['name'])}")

if __name__ == '__main__':
    main()
