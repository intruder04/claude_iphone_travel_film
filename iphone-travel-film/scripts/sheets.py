"""Contact sheets so Claude can *look* at the footage (the most important quality step).

  sheets.py clips              review/sheet_NN.jpg   10 clips per sheet, 3 frames each (20/50/80 %), number + time + length
  sheets.py compact            review/compact_N.jpg  1 frame per clip, 54 per sheet (fast overview of a whole trip)
  sheets.py intent             review/intent_NN.jpg  8 clips per sheet, 6 frames across each clip with timestamps,
                                plus text Vision read and speech — to decide what each clip is FOR and where its moment is
  sheets.py grid CLIP T [...]  review/grid/CLIP_T.jpg 1920x1080 frame with a labelled 100 px grid, for pinning
                                coordinates of landmarks/animals precisely (pairs of CLIP T may repeat)
"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
from common import P, jload, grab

def _font(sz):
    for f in ('/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/System/Library/Fonts/Helvetica.ttc'):
        if os.path.exists(f): return ImageFont.truetype(f, sz)
    return ImageFont.load_default()

def clips():
    from multiprocessing import Pool
    d = jload('meta/index.json')
    with Pool(os.cpu_count()) as p: n = p.map(_sheet, [(i, d[i * 10:(i + 1) * 10]) for i in range((len(d) + 9) // 10)])
    print(f'{len(n)} sheets in review/')

def _sheet(args):
    i, rs = args; CW, CH = 400, 225; F = _font(22)
    S = Image.new('RGB', (CW * 3, CH * len(rs)), (40, 40, 40))
    for k, r in enumerate(rs):
        fs = sorted(glob.glob(P('frames', r['file'], '*.jpg'))); cell = Image.new('RGB', (CW * 3, CH))
        for j, q in enumerate((0.2, 0.5, 0.8)):
            if not fs: break
            f = Image.open(fs[min(len(fs) - 1, int(q * len(fs)))]); f.thumbnail((CW, CH))
            cell.paste(f, (j * CW + (CW - f.width) // 2, (CH - f.height) // 2))
        d = ImageDraw.Draw(cell); t = f"{os.path.splitext(r['file'])[0]}  {r['time'][5:16].replace('T', ' ')}  {r['dur']:.0f}s"
        d.rectangle((0, 0, d.textlength(t, font=F) + 12, 30), fill=(0, 0, 0)); d.text((6, 3), t, font=F, fill=(255, 255, 0))
        S.paste(cell, (0, k * CH))
    S.save(P('review', f'sheet_{i:02d}.jpg'), quality=80); return i

def intent():
    from multiprocessing import Pool
    d = jload('meta/index.json')
    with Pool(os.cpu_count()) as p: n = p.map(_intent_sheet, [(i, d[i * 8:(i + 1) * 8]) for i in range((len(d) + 7) // 8)])
    print(f'{len(n)} intent sheets in review/')

def _intent_sheet(args):
    i, rs = args; CW, CH, LH = 300, 169, 26; F, Fs = _font(20), _font(15)
    AV = jload('meta/apple_vision.json', {}); SP = jload('meta/speech.json', {})
    S = Image.new('RGB', (CW * 6, (CH + LH) * len(rs)), (25, 25, 25)); d = ImageDraw.Draw(S)
    for k, r in enumerate(rs):
        fs = sorted(glob.glob(P('frames', r['file'], '*.jpg'))); y = k * (CH + LH)
        txt = ' | '.join(dict.fromkeys(t for _, t in AV.get(r['file'], {}).get('text', [])))[:70]
        sp = SP.get(r['file'], {}).get('text', '')[:60]
        lab = f"{os.path.splitext(r['file'])[0]}  {r['time'][5:16].replace('T', ' ')}  {r['dur']:.0f}s" + (f'  TEXT: {txt}' if txt else '') + (f'  SAID: {sp}' if sp else '')
        d.text((6, y + 3), lab, font=F, fill=(255, 220, 0))
        for j in range(6):
            if not fs: break
            q = (j + 0.5) / 6; f = Image.open(fs[min(len(fs) - 1, int(q * len(fs)))]); f.thumbnail((CW, CH))
            S.paste(f, (j * CW + (CW - f.width) // 2, y + LH + (CH - f.height) // 2))
            d.text((j * CW + 4, y + LH + 2), f'{q * r["dur"]:.0f}s', font=Fs, fill=(255, 255, 255))
    S.save(P('review', f'intent_{i:02d}.jpg'), quality=78); return i

def compact():
    d = jload('meta/index.json'); F = _font(16); CW, CH, C = 320, 180, 6
    for s in range(0, len(d), 54):
        chunk = d[s:s + 54]; S = Image.new('RGB', (CW * C, CH * ((len(chunk) + C - 1) // C)))
        for i, r in enumerate(chunk):
            fs = sorted(glob.glob(P('frames', r['file'], '*.jpg')))
            c = Image.new('RGB', (CW, CH))
            if fs:
                im = Image.open(fs[len(fs) // 2]); im.thumbnail((CW, CH)); c.paste(im, ((CW - im.width) // 2, (CH - im.height) // 2))
            dr = ImageDraw.Draw(c); lab = os.path.splitext(r['file'])[0][-6:]
            dr.rectangle((0, 0, 8 + dr.textlength(lab, font=F), 20), fill=0); dr.text((3, 1), lab, font=F, fill=(255, 255, 0))
            S.paste(c, ((i % C) * CW, (i // C) * CH))
        S.save(P('review', f'compact_{s // 54}.jpg'), quality=78)
    print('compact sheets in review/')

def grid(clip, t):
    im = grab(clip, float(t)); d = ImageDraw.Draw(im); F = _font(18)
    for x in range(100, 1920, 100):
        d.line((x, 0, x, 1080), fill=(255, 255, 0), width=1)
        if x % 200 == 100: d.text((x + 2, 2), str(x), font=F, fill=(255, 255, 0))
    for y in range(100, 1080, 100):
        d.line((0, y, 1920, y), fill=(255, 255, 0), width=1)
        if y % 200 == 100: d.text((2, y + 2), str(y), font=F, fill=(255, 255, 0))
    os.makedirs(P('review/grid'), exist_ok=True)
    out = P('review/grid', f'{os.path.splitext(clip)[0]}_{t}.jpg'); im.save(out, quality=85); print(out)

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'clips'
    if cmd == 'clips': clips()
    elif cmd == 'compact': compact()
    elif cmd == 'intent': intent()
    elif cmd == 'grid':
        a = sys.argv[2:]
        for c, t in zip(a[::2], a[1::2]): grid(c if '.' in c else c + '.MOV', t)
    else: sys.exit(__doc__)
