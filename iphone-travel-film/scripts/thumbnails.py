"""Step 10 — YouTube thumbnails (1280x720 JPG, < 2 MB), several styles for the user to choose from.

Current travel-thumbnail conventions this follows: one clear subject, 1–3 huge bold words (readable at phone size),
punchy but natural colour, strong subject/background separation, a small location/flag badge, nothing in the
bottom-right corner (YouTube's duration stamp).

  thumbnails.py pick                 rank candidate frames → previews/thumbnails/candidates.jpg (numbered)
  thumbnails.py make [N N ...]       render all styles; order = pop subject (a person or animal), cinematic hero
                                     (wide landmark/scenery), minimal, … (default: best 4)

Text comes from project.json:  "thumbnail_text": ["JAPAN", "IN 27 MIN"],  "thumbnail_badge": "🇯🇵 Tokyo → Kyoto"
(Claude proposes these from the trip; keep the big text to ≤ 3 words.)
Subject cut-outs use Apple Vision's foreground-instance mask ("lift subject") on the Neural Engine."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont
from common import CFG, P, jload, edl_shots, grab

TW, TH = 1280, 720
OUT = P('previews', 'thumbnails'); os.makedirs(OUT, exist_ok=True)
F = '/System/Library/Fonts/'

def sf(size, weight='Black'):
    f = ImageFont.truetype(F + 'SFNS.ttf', size)
    try: f.set_variation_by_name(weight)
    except Exception: pass
    return f

def condensed(size):
    try: return ImageFont.truetype(F + 'Avenir Next Condensed.ttc', size, index=8)   # Heavy
    except OSError: return sf(size)

def emoji(text, h):
    """Render emoji (flags included) with macOS CoreText via AppKit — Pillow can't shape flag ligatures."""
    import io, AppKit
    font = AppKit.NSFont.fontWithName_size_('Apple Color Emoji', 160)
    s = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, {AppKit.NSFontAttributeName: font})
    sz = s.size(); w, hh = int(sz.width) + 4, int(sz.height) + 4
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, w, hh, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    s.drawAtPoint_((2, 2)); AppKit.NSGraphicsContext.restoreGraphicsState()
    im = Image.open(io.BytesIO(bytes(rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})))).convert('RGBA')
    bb = im.getbbox(); im = im.crop(bb) if bb else im
    return im.resize((max(1, int(im.width * h / im.height)), h), Image.LANCZOS)

# ------------------------------------------------------------------ subject mask (Apple Vision)
def subject_mask(img):
    """Foreground instance mask for a PIL RGB image → L image (0..255), or None."""
    import Vision, Quartz
    from Foundation import NSURL
    tmp = P('tmp', 'thumb_mask_src.jpg'); img.save(tmp, quality=95)
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(tmp), None)
    rq = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    h.performRequests_error_([rq], None)
    if not rq.results(): return None
    obs = rq.results()[0]
    pb, err = obs.generateScaledMaskForImageForInstances_fromRequestHandler_error_(obs.allInstances(), h, None)
    if pb is None: return None
    Quartz.CVPixelBufferLockBaseAddress(pb, 1)
    w, hh, bpr = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb), Quartz.CVPixelBufferGetBytesPerRow(pb)
    raw = bytes(Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * hh)); Quartz.CVPixelBufferUnlockBaseAddress(pb, 1)
    m = np.frombuffer(raw, np.float32).reshape(hh, bpr // 4)[:, :w]
    return Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).resize(img.size, Image.LANCZOS)

# ------------------------------------------------------------------ candidates
def pick(n=16):
    V = jload('meta/vision.json', {}); E, edl = edl_shots()
    L = jload('locations.json', {}); pip = set(L.get('dual_selfie', []))
    cands = []
    for i, e in enumerate(edl):
        if e.get('tag') == 'dual-selfie' or e['file'] in pip or e.get('portrait'): continue      # picture-in-picture inset clutters thumbnails
        fr = V.get(e['file'], [])
        for s in range(int(e['ss']) + 1, int(e['ss'] + e['dur']) - 1):
            if s >= len(fr) or fr[s].get('aes') is None or fr[s].get('util'): continue
            people = max(fr[s]['humans'] or [0])
            score = fr[s]['aes'] + 0.25 * (0.04 < people < 0.5)
            cands.append((score, i, e['file'], s + 0.5, e['seg'], people))
    cands.sort(reverse=True); chosen, used = [], {}
    for c in cands:                                   # diversity: ≤ 2 per segment, not from the same shot
        if used.get(c[4], 0) >= 2 or any(c[1] == o[1] for o in chosen): continue
        chosen.append(c); used[c[4]] = used.get(c[4], 0) + 1
        if len(chosen) >= n: break
    json.dump([dict(n=k, shot=c[1], file=c[2], t=c[3], seg=c[4], score=round(c[0], 3), people=c[5]) for k, c in enumerate(chosen)],
              open(os.path.join(OUT, 'candidates.json'), 'w'), indent=1)
    from sheets import _font
    S = Image.new('RGB', (4 * 480, ((len(chosen) + 3) // 4) * 270)); Fn = _font(28)
    for k, c in enumerate(chosen):
        im = grab(c[2], c[3], 960, 540).resize((480, 270)); d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 60, 36), fill=0); d.text((8, 3), str(k), font=Fn, fill=(255, 220, 0)); S.paste(im, ((k % 4) * 480, (k // 4) * 270))
    S.save(os.path.join(OUT, 'candidates.jpg'), quality=85); print(f'{len(chosen)} candidates → previews/thumbnails/candidates.jpg')

# ------------------------------------------------------------------ helpers
def grade(im, sat=1.22, con=1.12, bri=1.03):
    return ImageEnhance.Brightness(ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(sat)).enhance(con)).enhance(bri)

def cover(im, w=TW, h=TH):
    k = max(w / im.width, h / im.height); im = im.resize((int(im.width * k + 0.5), int(im.height * k + 0.5)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2; return im.crop((x, y, x + w, y + h))

def text_stroke(d, xy, s, f, fill=(255, 255, 255), stroke=(0, 0, 0), sw=8, anchor='la'):
    d.text(xy, s, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)

def shadow_text(img, xy, s, f, fill=(255, 255, 255), blur=10, off=(0, 6), alpha=170, anchor='la'):
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).text((xy[0] + off[0], xy[1] + off[1]), s, font=f, fill=(0, 0, 0, alpha), anchor=anchor)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur))); ImageDraw.Draw(img).text(xy, s, font=f, fill=fill, anchor=anchor)

def fit_font(d, s, maker, max_w, start):
    size = start
    while size > 20 and d.textlength(s, font=maker(size)) > max_w: size -= 4
    return maker(size)

def badge(img, text, xy, h=46):
    """Rounded dark pill with optional leading emoji (flag)."""
    d = ImageDraw.Draw(img); parts = text.split(' ', 1)
    em = emoji(parts[0], h - 14) if parts and any(ord(ch) > 0x1F000 for ch in parts[0]) else None
    label = parts[1] if em is not None and len(parts) > 1 else text
    f = sf(int(h * 0.52), 'Bold'); tw = d.textlength(label, font=f); w = int(tw + 36 + (em.width + 12 if em else 0))
    d.rounded_rectangle((xy[0], xy[1], xy[0] + w, xy[1] + h), h // 2, fill=(15, 15, 18, 215))
    x = xy[0] + 18
    if em: img.alpha_composite(em, (x, xy[1] + 7)); x += em.width + 12
    d.text((x, xy[1] + h / 2), label, font=f, fill=(255, 255, 255), anchor='lm')

# ------------------------------------------------------------------ styles
YELLOW = (255, 214, 10)

def subject_crop(big):
    """Zoom a 16:9 crop of the 4K frame onto the main subject (≈60 % of the height, on the right third).
    Returns (1280x720 image, mask) or (None, None) when there is no clear subject."""
    small = big.resize((1280, 720), Image.LANCZOS); m = subject_mask(small)
    if m is None: return None, None
    a = np.asarray(m) > 128; cov = a.mean()
    if not 0.004 < cov < 0.6: return None, None
    ys, xs = np.nonzero(a); k = big.width / 1280
    x0, x1, y0, y1 = xs.min() * k, xs.max() * k, ys.min() * k, ys.max() * k
    ch = max(720, min(big.height, (y1 - y0) / 0.58, (x1 - x0) / 0.42 * 9 / 16)); cw = ch * 16 / 9
    cx = (x0 + x1) / 2 - cw * 0.27                      # subject sits right of centre, text goes left
    cy = (y0 + y1) / 2
    L = int(min(max(0, cx - cw / 2), big.width - cw)); T = int(min(max(0, cy - ch / 2), big.height - ch))
    crop = big.crop((L, T, int(L + cw), int(T + ch))).resize((TW, TH), Image.LANCZOS)
    m2 = subject_mask(crop)
    return (crop, m2) if m2 is not None and (np.asarray(m2) > 128).mean() > 0.02 else (None, None)

def style_pop(big, words, badge_text):
    """Subject lifted from the background (Apple Vision) with a white outline + glow, zoomed in on the right;
    huge 2-line text on the left. Returns None when there is no clear subject."""
    src, m = subject_crop(big)
    if src is None: return None
    img = grade(src, 1.1, 1.05, 0.72).filter(ImageFilter.GaussianBlur(2.5)).convert('RGBA')
    subj = grade(src, 1.28, 1.12, 1.06).convert('RGBA'); subj.putalpha(m)
    ring = m.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(1.2))
    glow = Image.new('RGBA', img.size, (255, 255, 255, 0))
    glow.putalpha(m.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55)))
    white = Image.new('RGBA', img.size, (255, 255, 255, 0)); white.putalpha(ring)
    img.alpha_composite(glow); img.alpha_composite(white); img.alpha_composite(subj)
    d = ImageDraw.Draw(img); x0 = 48
    w1, w2 = (words + [''])[:2]
    f1 = fit_font(d, w1, condensed, TW * 0.46, 230); text_stroke(d, (x0, 130), w1, f1, fill=(255, 255, 255), sw=10)
    if w2:
        f2 = fit_font(d, w2, condensed, TW * 0.46, 150); y2 = 130 + f1.size * 0.95
        tw = d.textlength(w2, font=f2); d.rectangle((x0 - 12, y2 + f2.size * 0.12, x0 + tw + 12, y2 + f2.size * 1.02), fill=YELLOW)
        d.text((x0, y2), w2, font=f2, fill=(10, 10, 10))
    if badge_text: badge(img, badge_text, (int(x0), 44))
    return img

def style_cinematic(src, words, badge_text):
    """Full-bleed hero landscape, filmic grade, one giant word, journey line under it."""
    img = grade(src, 1.18, 1.15, 1.0).convert('RGBA')
    vg = Image.new('L', (TW, TH), 0); ImageDraw.Draw(vg).rectangle((0, int(TH * 0.45), TW, TH), fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(120)); sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(vg.point(lambda v: v * 0.8)); img.alpha_composite(sh)
    d = ImageDraw.Draw(img); w = words[0]
    f = fit_font(d, w, lambda s: sf(s, 'Black'), TW * 0.86, 260)
    shadow_text(img, (TW / 2, TH * 0.70), w, f, anchor='ms', blur=16, alpha=200)
    if len(words) > 1:
        fs = sf(46, 'Bold'); shadow_text(img, (TW / 2, TH * 0.70 + 64), ' '.join(words[1:]).upper(), fs, fill=YELLOW, anchor='ms', blur=8)
    if badge_text: badge(img, badge_text, (40, 36))
    return img

def style_collage(srcs, words, badge_text):
    """3 slanted panels of different places + bold title block — 'whole trip in one video' look."""
    img = Image.new('RGBA', (TW, TH), (255, 255, 255, 255)); n = len(srcs); sk = 90
    for k, s in enumerate(srcs):
        x0, x1 = k * TW / n, (k + 1) * TW / n
        poly = [(x0 + sk / 2 if k else 0, 0), (x1 + sk / 2 if k < n - 1 else TW, 0), (x1 - sk / 2 if k < n - 1 else TW, TH), (x0 - sk / 2 if k else 0, TH)]
        m = Image.new('L', (TW, TH), 0); ImageDraw.Draw(m).polygon(poly, fill=255)
        panel = grade(cover(s, int(TW / n + sk * 2), TH), 1.25, 1.1).convert('RGBA')
        layer = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); layer.paste(panel, (int(x0 - sk), 0)); img.paste(layer, (0, 0), m)
        if k: ImageDraw.Draw(img).line([(x0 + sk / 2, 0), (x0 - sk / 2, TH)], fill=(255, 255, 255), width=12)
    d = ImageDraw.Draw(img); w = ' '.join(words[:2])
    f = fit_font(d, w, condensed, TW * 0.8, 170); tw = d.textlength(w, font=f)
    bx0, by0 = (TW - tw) / 2 - 34, TH * 0.36; d.rounded_rectangle((bx0, by0, bx0 + tw + 68, by0 + f.size * 1.05), 18, fill=YELLOW)
    d.text((TW / 2, by0 + f.size * 0.53), w, font=f, fill=(10, 10, 10), anchor='mm')
    if badge_text: badge(img, badge_text, (40, 36))
    return img

def style_minimal(src, words, badge_text):
    """Calm 'aesthetic vlog' look: soft grade, small elegant text bottom-left, lots of image."""
    img = grade(src, 1.05, 1.02, 1.04).convert('RGBA')
    g = Image.new('L', (TW, TH), 0); ImageDraw.Draw(g).rectangle((0, int(TH * 0.55), int(TW * 0.7), TH), fill=255)
    g = g.filter(ImageFilter.GaussianBlur(140)); sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(g.point(lambda v: v * 0.7)); img.alpha_composite(sh)
    d = ImageDraw.Draw(img)
    if len(words) > 1: d.text((56, TH - 230), ' '.join(words[1:]).upper(), font=sf(30, 'Semibold'), fill=(235, 235, 235))
    shadow_text(img, (52, TH - 200), words[0].lower(), sf(150, 'Bold'), blur=10, alpha=140)
    if badge_text: badge(img, badge_text, (40, 36))
    return img

def make(nums=None):
    cands = json.load(open(os.path.join(OUT, 'candidates.json')))
    nums = nums or [c['n'] for c in cands[:4]]
    words = CFG.get('thumbnail_text') or [CFG.get('output_name', 'MY TRIP').replace('_', ' ').upper()]
    btxt = CFG.get('thumbnail_badge', '')
    big = {c['n']: grab(c['file'], c['t'], 3840, 2160) for c in cands if c['n'] in nums}
    frames = {n: im.resize((TW, TH), Image.LANCZOS) for n, im in big.items()}
    outs = []
    def save(im, name):
        if im is None: print(f'skipped {name}: no clear subject'); return
        p = os.path.join(OUT, name); im.convert('RGB').save(p, quality=92, optimize=True)
        if os.path.getsize(p) > 2_000_000: im.convert('RGB').save(p, quality=82, optimize=True)
        outs.append(p)
    a = (nums * 4)[:4]          # order matters: 1st = pop subject, 2nd = cinematic hero, 3rd = minimal, 2nd-4th = collage
    save(style_pop(big[a[0]], words, btxt), 'thumb_1_pop.jpg')
    save(style_cinematic(frames[a[1]], words, btxt), 'thumb_2_cinematic.jpg')
    save(style_collage([frames[n] for n in dict.fromkeys(a[1:] + a[:1])][:3], words, btxt), 'thumb_3_collage.jpg')
    save(style_minimal(frames[a[2]], words, btxt), 'thumb_4_minimal.jpg')
    people = [n for n in sorted(nums, key=lambda n: -next(c['people'] for c in cands if c['n'] == n)) if n != a[0]]
    if people: save(style_pop(big[people[0]], words, btxt), 'thumb_5_pop_people.jpg')
    ims = [Image.open(p).resize((640, 360)) for p in outs]
    S = Image.new('RGB', (1280, 360 * ((len(ims) + 1) // 2)), (20, 20, 20))
    for k, im in enumerate(ims): S.paste(im, ((k % 2) * 640, (k // 2) * 360))
    S.save(os.path.join(OUT, 'all_thumbnails.jpg'), quality=88)
    for p in outs: print(p, f'{os.path.getsize(p) / 1e6:.2f} MB')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'pick': pick()
    elif cmd == 'make': make([int(x) for x in sys.argv[2:]] or None)
    else: sys.exit(__doc__)
