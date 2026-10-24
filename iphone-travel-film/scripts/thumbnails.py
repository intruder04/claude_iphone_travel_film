"""Step 10 — YouTube thumbnails (1280x720 JPG, < 2 MB), several styles for the user to choose from.

Current travel-thumbnail conventions this follows: one clear subject, 1–3 huge bold words (readable at phone size),
punchy but natural colour, strong subject/background separation, a small location/flag badge, nothing in the
bottom-right corner (YouTube's duration stamp).

  thumbnails.py pick                 rank candidate frames → previews/thumbnails/candidates.jpg (numbered)
  thumbnails.py add CLIP@T ...       add hand-picked frames to the candidates (e.g. scenery the ranker missed)
  thumbnails.py make [N N ...]       render all styles; order = pop subject (a person or animal), cinematic hero
                                     (wide landmark/scenery), minimal, … (default: best 4)

Text comes from project.json, after the user picked from proposed options (never put the video length in it):
  "thumbnail_variants": [["JAPAN", "Tokyo · Kamakura · Kyoto"], ["SUMMER", "IN JAPAN"]],   # [headline, line 2]
  "thumbnail_badge": "🇯🇵 Japan 2026",  "thumbnail_route": ["Tokyo", "Kamakura", "Kyoto"],
  "thumbnail_accents": ["flag_badge", "yellow_bar", "route_dots"]
Split films (TRAVEL_FILM_PART=N): candidates come from that part only, output goes to renders/thumbnails/PartN/, and
"thumbnail_parts": {"N": {"variants": [[...]], "badge": "...", "face_frames": [...]}} overrides the settings above.
Every variant is rendered in every style → at least 10 thumbnails (more variants or frames are added if needed).
Subject cut-outs use Apple Vision's foreground-instance mask ("lift subject") on the Neural Engine."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont
from common import CFG, P, jload, edl_shots, grab, PART

TW, TH = 1280, 720
SUB = f'Part{PART}' if PART else ''
OUT = P('previews', 'thumbnails', SUB); os.makedirs(OUT, exist_ok=True)
DELIVER = P('renders', 'thumbnails', SUB); os.makedirs(DELIVER, exist_ok=True)   # finished thumbnails go next to the film
PCFG = CFG.get('thumbnail_parts', {}).get(str(PART), {}) if PART else {}      # per-part text, badge, face frames
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

def face_centered(img, aspect=1.0):
    """Crop around the largest face (Apple Vision) so later panel crops keep the face. Returns img unchanged if none."""
    import Vision
    from Foundation import NSURL
    tmp = P('tmp', 'thumb_face.jpg'); img.convert('RGB').save(tmp, quality=92)
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(tmp), None)
    rq = Vision.VNDetectFaceRectanglesRequest.alloc().init(); h.performRequests_error_([rq], None)
    fs = rq.results() or []
    if not fs: return img
    b = max(fs, key=lambda o: o.boundingBox().size.width).boundingBox()
    W_, H_ = img.size; cx = (b.origin.x + b.size.width / 2) * W_; cy = (1 - b.origin.y - b.size.height / 2) * H_
    ch = min(H_, max(b.size.height * H_ * 2.6, H_ * 0.55)); cw = min(W_, ch * aspect)
    x0 = min(max(0, cx - cw / 2), W_ - cw); y0 = min(max(0, cy - ch * 0.45), H_ - ch)
    return img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))


# ------------------------------------------------------------------ keep text off faces
FACE_HITS = []          # (style, overlap px) when no face-free spot existed — reported by make()

def face_boxes(img, pad=0.22):
    """Faces (Apple Vision) in a composed thumbnail background, as pixel boxes padded to cover hair and chin.
    Tiny faces (crowds in the background) are ignored: only faces a viewer would notice matter."""
    import Vision
    from Foundation import NSURL
    tmp = P('tmp', 'thumb_faces.jpg'); img.convert('RGB').save(tmp, quality=90)
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(tmp), None)
    rq = Vision.VNDetectFaceRectanglesRequest.alloc().init(); h.performRequests_error_([rq], None)
    W_, H_ = img.size; out = []
    for o in rq.results() or []:
        b = o.boundingBox(); w, hh = b.size.width * W_, b.size.height * H_
        if hh < H_ * 0.07: continue
        x, y = b.origin.x * W_, (1 - b.origin.y - b.size.height) * H_
        out.append((x - w * pad, y - hh * (pad + 0.3), x + w * (1 + pad), y + hh * (1 + pad)))
    return out

def overlap(box, faces):
    return sum(max(0, min(box[2], f[2]) - max(box[0], f[0])) * max(0, min(box[3], f[3]) - max(box[1], f[1])) for f in faces)

def choose_spot(cands, faces, style):
    """cands: [(box, layout), ...] in order of preference → the first that covers no face, else the least bad."""
    for box, lay in cands:
        if overlap(box, faces) == 0: return lay
    box, lay = min(cands, key=lambda c: overlap(c[0], faces))
    core = [(f[0] + (f[2] - f[0]) * 0.18, f[1] + (f[3] - f[1]) * 0.25, f[2] - (f[2] - f[0]) * 0.18, f[3] - (f[3] - f[1]) * 0.18) for f in faces]
    if overlap(box, core): FACE_HITS.append((style, int(overlap(box, core))))   # only text on the face itself is a problem
    return lay


# ------------------------------------------------------------------ photo fix for thumbnail frames
def horizon_angle(img):
    """Camera roll in degrees from Apple Vision's horizon detector (None if no horizon found)."""
    import Vision
    from Foundation import NSURL
    tmp = P('tmp', 'thumb_hz.jpg'); img.convert('RGB').resize((1280, 720)).save(tmp, quality=90)
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(tmp), None)
    rq = Vision.VNDetectHorizonRequest.alloc().init(); h.performRequests_error_([rq], None)
    r = rq.results()
    return float(np.degrees(r[0].angle())) if r else None

def enhance(img, level=True):
    """Make a frame thumbnail-ready: level the horizon (0.7–8°), auto levels from the luminance histogram
    (1st→99.5th percentile, no clipping of highlights), gentle midtone lift for dark frames, light sharpening."""
    import math
    img = img.convert('RGB'); W_, H_ = img.size
    if level:
        a = horizon_angle(img)
        if a is not None and 0.7 <= abs(a) <= 8:
            r = math.radians(abs(a)); k = math.cos(r) + (W_ / H_) * math.sin(r)
            big = img.resize((int(W_ * k) + 2, int(H_ * k) + 2), Image.LANCZOS).rotate(-a, resample=Image.BICUBIC)
            L = (big.width - W_) // 2; T = (big.height - H_) // 2; img = big.crop((L, T, L + W_, T + H_))
    arr = np.asarray(img).astype(np.float32) / 255
    lum = arr @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lo, hi = np.percentile(lum, 1), np.percentile(lum, 99.5)
    if hi - lo > 0.15:
        arr = np.clip((arr - lo * 0.85) / max(hi - lo * 0.85, 1e-3), 0, 1)
    m = float((arr @ np.array([0.2126, 0.7152, 0.0722], np.float32)).mean())
    if m < 0.38: arr = arr ** (math.log(0.42) / math.log(max(m, 0.05)) * 0.6 + 0.4)   # lift dark frames, partly
    img = Image.fromarray((arr * 255).astype(np.uint8))
    return img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=55, threshold=2))

# ------------------------------------------------------------------ candidates
def pick(n=16):
    V = jload('meta/vision.json', {}); E, edl = edl_shots()
    L = jload('locations.json', {}); pip = set(L.get('dual_selfie', []))
    cands = []
    for i, e in enumerate(edl):
        if e.get('tag') in ('dual-selfie', 'teaser') or e['file'] in pip or e.get('portrait'): continue      # picture-in-picture inset clutters thumbnails
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
    S.save(os.path.join(OUT, 'candidates.jpg'), quality=85); print(f'{len(chosen)} candidates → {os.path.relpath(OUT, P())}/candidates.jpg')

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
ACC = set(CFG.get('thumbnail_accents', ['yellow_bar']))   # 'flag_badge' / 'route_dots' only on request
ROUTE = CFG.get('thumbnail_route', [])

def route_dots(img, xy, width, light=True):
    """Thin map line with dots and city names (accent 'route_dots')."""
    if 'route_dots' not in ACC or len(ROUTE) < 2: return
    d = ImageDraw.Draw(img); x0, y = xy; n = len(ROUTE); step = width / (n - 1); f = sf(26, 'Semibold')
    col = (255, 255, 255) if light else (20, 20, 20)
    for k in range(n - 1):
        for xx in range(int(x0 + k * step + 14), int(x0 + (k + 1) * step - 14), 14):
            d.line((xx, y, xx + 7, y), fill=col + (230,), width=4)
    for k, name in enumerate(ROUTE):
        cx = x0 + k * step
        d.ellipse((cx - 11, y - 11, cx + 11, y + 11), fill=YELLOW, outline=(20, 20, 20), width=3)
        tw = d.textlength(name, font=f)
        d.text((cx - tw / 2 + 2, y + 20 + 2), name, font=f, fill=(0, 0, 0, 160)); d.text((cx - tw / 2, y + 20), name, font=f, fill=col)

def boxed_text(d, x, y, text, font, bg, fg, padx=None, pady=None, radius=0, center=False):
    """Text on a box whose padding is measured from the real glyph outlines (equal on all sides), so the text is
    optically centred. (x, y) = top-left of the box, or top-centre when center=True. Returns the box."""
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    padx = font.size * 0.28 if padx is None else padx; pady = font.size * 0.16 if pady is None else pady
    w, h = (r - l) + 2 * padx, (b - t) + 2 * pady
    bx = x - w / 2 if center else x
    box = (bx, y, bx + w, y + h)
    if radius: d.rounded_rectangle(box, radius, fill=bg)
    else: d.rectangle(box, fill=bg)
    d.text((bx + padx - l, y + pady - t), text, font=font, fill=fg)
    return box

def second_line(d, x0, y2, w2, f2, bar=True):
    if bar and 'yellow_bar' in ACC:
        boxed_text(d, x0 - f2.size * 0.28, y2 + f2.size * 0.08, w2, f2, YELLOW, (10, 10, 10))
    else:
        text_stroke(d, (x0, y2), w2, f2, fill=YELLOW, sw=7)

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

def focus_crop(big, zoom_max=1.7, x_target=0.64, fill=0.72):
    """Zoom a 16:9 crop of the 4K frame onto its main salient object (Apple Vision objectness saliency), so a wide
    shot becomes one clear focal point: the object fills ~`fill` of the height and sits at `x_target` (text goes left).
    Zoom is bounded (≤ zoom_max, so a 4K frame stays sharp at 1280 px). Unchanged when nothing stands out."""
    import Vision
    from Foundation import NSURL
    small = big.resize((TW, TH), Image.LANCZOS); tmp = P('tmp', 'thumb_sal.jpg'); small.save(tmp, quality=90)
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(tmp), None)
    rq = Vision.VNGenerateObjectnessBasedSaliencyImageRequest.alloc().init(); h.performRequests_error_([rq], None)
    objs = (rq.results() or [None])[0]; objs = list(objs.salientObjects() or []) if objs else []
    if not objs: return small
    b = max(objs, key=lambda o: o.boundingBox().size.width * o.boundingBox().size.height * o.confidence()).boundingBox()
    W_, H_ = big.size
    x0, x1 = b.origin.x * W_, (b.origin.x + b.size.width) * W_
    y0, y1 = (1 - b.origin.y - b.size.height) * H_, (1 - b.origin.y) * H_
    ch = min(H_, max(H_ / zoom_max, (y1 - y0) / fill)); cw = ch * 16 / 9
    L = min(max(0, (x0 + x1) / 2 - cw * x_target), W_ - cw); T = min(max(0, (y0 + y1) / 2 - ch * 0.48), H_ - ch)
    return big.crop((int(L), int(T), int(L + cw), int(T + ch))).resize((TW, TH), Image.LANCZOS)

def style_pop(big, words, badge_text):
    """Subject focus: Apple Vision lifts the subject; it stays sharp and bright while the background is dimmed and
    softly blurred (no outline or glow). Zoomed in on the right, huge 2-line text on the left."""
    src, m = subject_crop(big)
    if src is None: return None
    img = grade(src, 1.1, 1.05, 0.72).filter(ImageFilter.GaussianBlur(2.5)).convert('RGBA')
    subj = grade(src, 1.25, 1.1, 1.08).convert('RGBA')
    subj.putalpha(m.filter(ImageFilter.GaussianBlur(2)))      # soft edge, no outline/glow (keeps it natural)
    img.alpha_composite(subj)
    d = ImageDraw.Draw(img)
    w1, w2 = (words + [''])[:2]
    faces = face_boxes(img); cands = []                  # top-left, bottom-left, top-right, bottom-right — off the face;
    for mw in (0.46, 0.34):                              # then the same corners with smaller text
        f1 = fit_font(d, w1, condensed, TW * mw, 230); f2 = fit_font(d, w2, condensed, TW * mw, 120) if w2 else None
        tw = max(d.textlength(w1, font=f1), d.textlength(w2, font=f2) if f2 else 0)
        hgt = f1.size * 0.95 + max(30, f1.size * 0.16) + (f2.size * 1.15 if f2 else 0)
        for x0, y1 in ((48, 130), (48, TH - 60 - hgt), (TW - 48 - tw, 130), (TW - 48 - tw, TH - 60 - hgt)):
            cands.append(((x0, y1, x0 + tw, y1 + hgt), (x0, y1, f1, f2)))
    x0, y1, f1, f2 = choose_spot(cands, faces, 'pop')
    text_stroke(d, (x0, y1), w1, f1, fill=(255, 255, 255), sw=10)
    y2 = y1 + f1.size * 0.95 + max(30, f1.size * 0.16)   # breathing room between headline and sub-line
    if f2: second_line(d, x0, y2, w2, f2); y2 += f2.size * 1.15
    if y1 < TH / 2: route_dots(img, (x0 + 20, min(TH - 120, y2 + 60)), TW * 0.38)
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (48, 44))      # top-left; headline starts below it
    return img

def style_cinematic(src, words, badge_text):
    """Full-bleed hero landscape, filmic grade, one giant word, journey line under it."""
    img = grade(src, 1.18, 1.15, 1.0).convert('RGBA')
    faces = face_boxes(img); d = ImageDraw.Draw(img); w = words[0]; cands = []
    for maxw, xs in ((0.86, (0.5,)), (0.46, (0.27, 0.73))):      # centred and big first; beside a face if needed
        f = fit_font(d, w, lambda s: sf(s, 'Black'), TW * maxw, 260)
        fs = fit_font(d, words[1].upper(), lambda s_: sf(s_, 'Heavy'), TW * maxw * 0.8, 64) if len(words) > 1 else None
        tw = max(d.textlength(w, font=f), d.textlength(words[1].upper(), font=fs) if fs else 0)
        for xc in xs:
            for by in (0.70, 0.36):
                y0, y1 = TH * by - f.size * 0.78, TH * by + (52 + fs.size * 1.45 if fs else 10)
                cands.append(((TW * xc - tw / 2 - 20, y0, TW * xc + tw / 2 + 20, y1), (f, fs, TW * xc, TH * by)))
    f, fs, xc, base = choose_spot(cands, faces, 'cinematic')
    vg = Image.new('L', (TW, TH), 0); ImageDraw.Draw(vg).rectangle((0, int(max(0, base - TH * 0.25)), TW, int(min(TH, base + TH * 0.3))), fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(120)); sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(vg.point(lambda v: v * 0.8)); img.alpha_composite(sh)
    d = ImageDraw.Draw(img)
    shadow_text(img, (xc, base), w, f, anchor='ms', blur=16, alpha=200)
    if fs:
        if 'yellow_bar' in ACC:
            boxed_text(d, xc, base + 52, words[1].upper(), fs, YELLOW, (10, 10, 10), center=True)
        else:
            shadow_text(img, (xc, base + 64), words[1].upper(), fs, fill=YELLOW, anchor='ms', blur=8)
    route_dots(img, (TW * 0.3, 70), TW * 0.4)
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (40, 36))
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
    _title_block(img, words, TH * 0.40, size=190, style='collage')
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (40, 36))
    return img

ACCENTS = [(255, 214, 10), (0, 229, 255), (255, 255, 255), (255, 92, 138), (124, 255, 107)]   # yellow, cyan, white, pink, lime

def pick_accent(img, box):
    """Accent colour for small text, chosen from the image under it: must contrast in brightness AND hue with the
    region (so it pops), and is drawn from a small modern palette (so it never looks random)."""
    import colorsys
    reg = np.asarray(img.convert('RGB').crop(tuple(int(v) for v in box)).resize((64, 32))).reshape(-1, 3) / 255.0
    lum = float((reg @ [0.2126, 0.7152, 0.0722]).mean())
    h, s_, v = colorsys.rgb_to_hsv(*reg.mean(0))
    best, score = None, -1
    for c in ACCENTS:
        ch, cs, cv = colorsys.rgb_to_hsv(*(np.array(c) / 255.0))
        cl = (np.array(c) / 255.0) @ [0.2126, 0.7152, 0.0722]
        hue_gap = min(abs(ch - h), 1 - abs(ch - h)) * (s_ > 0.15) * (cs > 0.1)   # only matters if both are coloured
        sc = abs(cl - lum) * 1.5 + hue_gap + (0.25 if c == ACCENTS[0] else 0)   # slight preference for classic yellow
        if sc > score: best, score = c, sc
    return best

def style_minimal(src, words, badge_text, face_big=None, vivid=False):
    """Calm 'aesthetic vlog' look: soft grade, big lowercase headline bottom-left, a readable small line above it.
    Both lines have a dark outline + soft shadow (readable on any background); the small line's colour adapts to the image.
    vivid: brighter, more saturated grade (bright saturated thumbnails out-click muted ones).
    face_big: a 4K frame of the creator — the face is cut out (no outline) and stands large on the right."""
    if vivid:                                          # adaptive: muted frames get more colour, already-saturated ones (blue sky) none
        sat_now = float(np.asarray(src.convert('HSV'))[..., 1].mean()) / 255
        img = grade(src, float(np.clip(1.0 + (0.42 - sat_now) * 1.2, 1.0, 1.22)), 1.06, 1.04).convert('RGBA')
    else:
        img = grade(src, 1.05, 1.02, 1.04).convert('RGBA')
    g = Image.new('L', (TW, TH), 0); ImageDraw.Draw(g).rectangle((0, int(TH * 0.50), int(TW * 0.75), TH), fill=255)
    g = g.filter(ImageFilter.GaussianBlur(140)); sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(g.point(lambda v: int(v * 0.72))); img.alpha_composite(sh)
    if face_big is not None:
        fsrc, m = subject_crop(face_big)
        if fsrc is not None and m.getbbox():
            img = Image.alpha_composite(img.filter(ImageFilter.GaussianBlur(4)), Image.new('RGBA', (TW, TH), (0, 0, 0, 38)))   # soft depth: face pops
            cut = grade(fsrc, 1.12, 1.04, 1.06).convert('RGBA'); cut.putalpha(m.filter(ImageFilter.GaussianBlur(2)))
            cut = cut.crop(m.getbbox()); k = TH * 0.88 / cut.height; cut = cut.resize((int(cut.width * k), int(cut.height * k)), Image.LANCZOS)
            img.alpha_composite(cut, (TW - cut.width + int(cut.width * 0.08), TH - cut.height))
    d = ImageDraw.Draw(img)
    fh = fit_font(d, words[0].lower(), lambda s_: sf(s_, 'Bold'), TW * 0.6, 170)
    l, t, r, b = d.textbbox((0, 0), words[0].lower(), font=fh); hx, hy = 50, TH - 46 - (b - t) - t
    blk = (hx, hy + t - (110 if len(words) > 1 else 0), hx + max(r - l, TW * 0.5), hy + b)
    faces = face_boxes(img) if face_big is None else []
    if overlap(blk, faces):                            # a face sits bottom-left: lift both lines to the top-left
        lift = (blk[1] - (104 + (110 if len(words) > 1 else 0)) + (110 if len(words) > 1 else 0))
        hy -= lift if overlap((blk[0], blk[1] - lift, blk[2], blk[3] - lift), faces) == 0 else 0
        if overlap((blk[0], blk[1] - lift, blk[2], blk[3] - lift), faces): FACE_HITS.append(('minimal', 1))
    if len(words) > 1:
        fsub = fit_font(d, words[1].upper(), lambda s_: sf(s_, 'Heavy'), TW * 0.62, 64)
        sl, st, sr, sb = d.textbbox((0, 0), words[1].upper(), font=fsub)
        sy = hy + t - 30 - (sb - st) - st
        acc = pick_accent(src, (54, sy + st, 54 + sr - sl, sy + sb))
        shd = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); ImageDraw.Draw(shd).text((56, sy + 5), words[1].upper(), font=fsub, fill=(0, 0, 0, 170))
        img.alpha_composite(shd.filter(ImageFilter.GaussianBlur(6)))
        ImageDraw.Draw(img).text((54, sy), words[1].upper(), font=fsub, fill=acc, stroke_width=5, stroke_fill=(10, 10, 10))
    shd = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); ImageDraw.Draw(shd).text((hx + 3, hy + 8), words[0].lower(), font=fh, fill=(0, 0, 0, 170))
    img.alpha_composite(shd.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(img).text((hx, hy), words[0].lower(), font=fh, fill=(255, 255, 255), stroke_width=6, stroke_fill=(10, 10, 10))
    return img

def _title_block(img, words, cy=None, yellow=True, max_w=0.8, size=190, band=False, style='title'):
    """Headline on a yellow (or dark) rounded block + white second line. Used by the collages. Faces in the
    composed background are detected first and the block moves (up, down, then smaller beside the face) so it never
    covers one. band=True draws a dark band behind it (strips style)."""
    d = ImageDraw.Draw(img); w = words[0]; cy = TH * 0.42 if cy is None else cy
    faces = face_boxes(img); cands = []
    for mw, xs in ((max_w, (0.5,)), (0.44, (0.26, 0.74))):
        f = fit_font(d, w, condensed, TW * mw, size); tw = d.textlength(w, font=f)
        f2 = fit_font(d, words[1].upper(), lambda s_: sf(s_, 'Heavy'), TW * mw * 0.94, 58) if len(words) > 1 else None
        l_, t_, r_, b_ = d.textbbox((0, 0), w, font=f); bh = (b_ - t_) + 2 * f.size * 0.16
        tot = bh + (50 + f2.size * 1.2 if f2 else 0); ww = max(tw + f.size * 0.6, d.textlength(words[1].upper(), font=f2) if f2 else 0)
        for c in dict.fromkeys((cy, TH * 0.24, TH * 0.74, TH * 0.5)):
            top = min(max(c - tot / 2, 96), TH - 24 - tot)          # below the badge, inside the frame
            cands.append(((TW * xs[0] - ww / 2, top, TW * xs[0] + ww / 2, top + tot), (f, f2, TW * xs[0], top, bh)) if len(xs) == 1 else
                         ((TW * xs[0] - ww / 2, top, TW * xs[0] + ww / 2, top + tot), (f, f2, TW * xs[0], top, bh)))
            if len(xs) > 1:
                cands.append(((TW * xs[1] - ww / 2, top, TW * xs[1] + ww / 2, top + tot), (f, f2, TW * xs[1], top, bh)))
    f, f2, xc, top, bh = choose_spot(cands, faces, style)
    if band:
        b = Image.new('RGBA', (TW, int(bh + (50 + f2.size * 1.2 if f2 else 0) + 60)), (0, 0, 0, 150)); img.alpha_composite(b, (0, int(top - 30)))
        d = ImageDraw.Draw(img)
    yb = yellow and 'yellow_bar' in ACC
    box = boxed_text(d, xc, top, w, f, YELLOW if yb else (15, 15, 18), (10, 10, 10) if yb else (255, 255, 255), radius=18, center=True)
    if f2:
        text_stroke(d, (xc, box[3] + 50), words[1].upper(), f2, fill=(255, 255, 255), sw=7, anchor='mt')

def _panel(img, src, box, border=10):
    x0, y0, x1, y1 = [int(v) for v in box]
    img.paste(grade(cover(src, x1 - x0, y1 - y0), 1.22, 1.1).convert('RGBA'), (x0, y0))
    if border: ImageDraw.Draw(img).rectangle((x0, y0, x1 - 1, y1 - 1), outline=(255, 255, 255), width=border)

def style_grid4(srcs, words, badge_text):
    """2x2 grid of four places, title block over the centre."""
    img = Image.new('RGBA', (TW, TH), (255, 255, 255, 255))
    for k, s in enumerate(srcs[:4]): _panel(img, s, ((k % 2) * TW / 2, (k // 2) * TH / 2, (k % 2 + 1) * TW / 2, (k // 2 + 1) * TH / 2), 6)
    _title_block(img, words, TH * 0.47, size=170, style='grid4')
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (30, 26))
    return img

def style_split(srcs, words, badge_text):
    """Two halves split by a white diagonal, headline across the seam."""
    img = Image.new('RGBA', (TW, TH)); a, b = srcs[:2]
    img.paste(grade(cover(a), 1.22, 1.1).convert('RGBA'))
    m = Image.new('L', (TW, TH), 0); ImageDraw.Draw(m).polygon([(TW * 0.58, 0), (TW, 0), (TW, TH), (TW * 0.42, TH)], fill=255)
    img.paste(grade(cover(b), 1.22, 1.1).convert('RGBA'), (0, 0), m)
    ImageDraw.Draw(img).line([(TW * 0.58, 0), (TW * 0.42, TH)], fill=(255, 255, 255), width=14)
    _title_block(img, words, TH * 0.70, size=170, style='split')
    route_dots(img, (TW * 0.3, 70), TW * 0.4)
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (40, 36))
    return img

def style_strips(srcs, words, badge_text):
    """Four tall vertical strips (film-strip look), title band across the middle."""
    img = Image.new('RGBA', (TW, TH), (255, 255, 255, 255)); n = min(4, len(srcs)); w = TW / n
    for k, s in enumerate(srcs[:n]): _panel(img, s, (k * w, 0, (k + 1) * w, TH), 6)
    _title_block(img, words, TH * 0.44, size=170, band=True, style='strips')
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (30, 26))
    return img

def _hero_text(img, words, x0, w, faces, style):
    """Headline + second line on a hero panel x0..x0+w: at its bottom, else its top — wherever no face is.
    Returns False when both would cover a face (the caller then moves the face to a small panel)."""
    d = ImageDraw.Draw(img)
    f1 = fit_font(d, words[0], condensed, w * 0.85, 200)
    f2 = fit_font(d, words[1].upper(), condensed, w * 0.8, 100) if len(words) > 1 else None
    tw = max(d.textlength(words[0], font=f1), d.textlength(words[1].upper(), font=f2) if f2 else 0)
    hgt = f1.size * 1.05 + (f2.size * 1.25 + 30 if f2 else 0)
    spots = [(TH - 120 - hgt, 'bottom'), (104, 'top')]
    free = [(y, k) for y, k in spots if overlap((x0, y, x0 + tw, y + hgt), faces) == 0]
    if not free: return False
    y, k = free[0]
    vg = Image.new('L', (TW, TH), 0)
    ImageDraw.Draw(vg).rectangle((int(x0 - 48), int(TH * 0.5) if k == 'bottom' else 0, int(x0 - 48 + w), TH if k == 'bottom' else int(TH * 0.5)), fill=255)
    sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(vg.filter(ImageFilter.GaussianBlur(90)).point(lambda v: int(v * 0.75))); img.alpha_composite(sh)
    d = ImageDraw.Draw(img); text_stroke(d, (x0, y), words[0], f1, sw=9)
    if f2: second_line(d, x0, y + f1.size * 1.0 + 30, words[1].upper(), f2)
    return True

def style_mosaic(srcs, words, badge_text, mirror=False):
    """One big hero panel + two stacked panels, title on the hero (mirror: hero on the right). The title goes at the
    bottom or top of the hero, whichever is free of faces; if neither is, the face frame moves to a small panel."""
    L = TW * (0.38 if mirror else 0.62)
    for order in (srcs[:3], [srcs[1], srcs[0], srcs[2]]):
        img = Image.new('RGBA', (TW, TH), (255, 255, 255, 255))
        hero = (L, 0, TW, TH) if mirror else (0, 0, L, TH)
        small = [(0, 0, L, TH / 2), (0, TH / 2, L, TH)] if mirror else [(L, 0, TW, TH / 2), (L, TH / 2, TW, TH)]
        _panel(img, order[0], hero, 6); _panel(img, order[1], small[0], 6); _panel(img, order[2], small[1], 6)
        x0 = int(hero[0] + 48); w = hero[2] - hero[0]
        if _hero_text(img, words, x0, w, face_boxes(img), 'mosaic'): break
    else:
        FACE_HITS.append(('mosaic', 1)); _hero_text(img, words, x0, w, [], 'mosaic')
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (int(hero[0]) + 40, 36))
    return img

def style_polaroid(srcs, words, badge_text):
    """Blurred hero background with 3 tilted photo cards, title below."""
    img = grade(cover(srcs[0]), 1.1, 1.0, 0.8).filter(ImageFilter.GaussianBlur(14)).convert('RGBA')
    for k, (s, ang, cx) in enumerate(zip(srcs[1:4], (-8, 3, 9), (0.24, 0.5, 0.76))):
        cw, ch = 360, 250; card = Image.new('RGBA', (cw + 24, ch + 64), (250, 250, 248, 255))
        card.paste(grade(cover(s, cw, ch), 1.22, 1.1).convert('RGBA'), (12, 12))
        card = card.rotate(ang, expand=True, resample=Image.BICUBIC)
        shd = Image.new('RGBA', card.size, (0, 0, 0, 0)); shd.putalpha(card.getchannel('A').point(lambda v: int(v * 0.5)))
        x, y = int(TW * cx - card.width / 2), int(TH * 0.12)
        img.alpha_composite(shd.filter(ImageFilter.GaussianBlur(8)), (x + 8, y + 12)); img.alpha_composite(card, (x, y))
    _title_block(img, words, TH * 0.72, size=130, style='polaroid')
    if badge_text and 'flag_badge' in ACC: badge(img, badge_text, (40, 36))
    return img

def style_mosaic_r(srcs, words, badge_text):
    """Mirror of mosaic: two stacked panels left, big hero right, title on the hero."""
    return style_mosaic(srcs, words, badge_text, mirror=True)


# ------------------------------------------------------------------ 2026 trend styles
# Findings (creator guides 2025–26): cleaner compositions with one focal point and negative space are replacing busy
# collages; a close-up genuine face + a recognisable location "hero" is the classic travel combo; 1–2 huge words max,
# readable on a phone; strong light/dark contrast; and a text-free variant is worth A/B testing (YouTube Test & Compare).

def style_face_hero(face_big, hero, words, badge_text, glow=False, neon=None):
    """Location hero full-bleed, the creator's face cut out (no outline) large in the lower corner, one huge word."""
    img = grade(cover(hero), 1.2, 1.12).convert('RGBA')
    g = Image.new('L', (TW, TH), 0); ImageDraw.Draw(g).rectangle((0, 0, int(TW * 0.6), TH), fill=255)
    sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(g.filter(ImageFilter.GaussianBlur(160)).point(lambda v: int(v * 0.55))); img.alpha_composite(sh)
    src, m = subject_crop(face_big)
    if src is not None:
        cut = grade(src, 1.15, 1.05, 1.06).convert('RGBA'); cut.putalpha(m.filter(ImageFilter.GaussianBlur(2)))
        bb = m.getbbox()
        if bb:
            cut = cut.crop(bb); k = TH * 0.92 / cut.height; cut = cut.resize((int(cut.width * k), int(cut.height * k)), Image.LANCZOS)
            pos = (TW - cut.width + int(cut.width * 0.06), TH - cut.height)
            if glow:                                   # soft light halo (on request) — no hard outline
                a = Image.new('L', (TW, TH), 0); a.paste(cut.getchannel('A'), pos)
                halo = a.filter(ImageFilter.MaxFilter(21)).filter(ImageFilter.GaussianBlur(28)).point(lambda v: min(255, int(v * 1.1)))
                hl = Image.new('RGBA', (TW, TH), (255, 245, 225, 0)); hl.putalpha(halo); img.alpha_composite(hl)
            if neon:                                   # neon tube outline: wide coloured bloom + bright thin core
                a = Image.new('L', (TW, TH), 0); a.paste(cut.getchannel('A').point(lambda v: 255 if v > 128 else 0), pos)
                edge = Image.fromarray((np.asarray(a.filter(ImageFilter.MaxFilter(11))).astype(int) - np.asarray(a.filter(ImageFilter.MaxFilter(3))).astype(int)).clip(0, 255).astype(np.uint8))
                for blur, gain in ((40, 1.0), (16, 1.6), (5, 2.2)):
                    lay = Image.new('RGBA', (TW, TH), tuple(neon) + (0,)); lay.putalpha(edge.filter(ImageFilter.GaussianBlur(blur)).point(lambda v, g=gain: min(255, int(v * g))))
                    img.alpha_composite(lay)
                core = Image.new('RGBA', (TW, TH), (255, 255, 255, 0)); core.putalpha(edge.filter(ImageFilter.GaussianBlur(1)).point(lambda v: int(v * 0.85)))
                img.alpha_composite(core)
            img.alpha_composite(cut, pos)
    d = ImageDraw.Draw(img)
    f = fit_font(d, words[0], condensed, TW * 0.5, 260); text_stroke(d, (56, TH * 0.5 - f.size * 0.6), words[0], f, sw=10)
    if len(words) > 1: second_line(d, 60, TH * 0.5 + f.size * 0.45 + 40, words[1].upper(), fit_font(d, words[1].upper(), condensed, TW * 0.45, 90))
    return img

def style_clean(hero, words, badge_text):
    """Minimal: one iconic image, lots of space, a single huge word, nothing else."""
    img = grade(cover(hero), 1.15, 1.12).convert('RGBA')
    g = Image.new('L', (TW, TH), 0); ImageDraw.Draw(g).rectangle((0, int(TH * 0.55), TW, TH), fill=255)
    sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(g.filter(ImageFilter.GaussianBlur(120)).point(lambda v: int(v * 0.6))); img.alpha_composite(sh)
    d = ImageDraw.Draw(img); f = fit_font(d, words[0], lambda s_: sf(s_, 'Black'), TW * 0.8, 280)
    shadow_text(img, (TW / 2, TH * 0.9), words[0], f, anchor='ms', blur=18, alpha=180)
    return img

def style_versus(a, b, la, lb, words, badge_text):
    """Two-city contrast: left vs right halves, each labelled, headline across the seam."""
    img = Image.new('RGBA', (TW, TH)); img.paste(grade(cover(a, TW // 2, TH), 1.2, 1.1).convert('RGBA'), (0, 0))
    img.paste(grade(cover(b, TW // 2, TH), 1.2, 1.1).convert('RGBA'), (TW // 2, 0))
    d = ImageDraw.Draw(img); d.rectangle((TW // 2 - 5, 0, TW // 2 + 5, TH), fill=(255, 255, 255))
    for txt, cx in ((la, TW / 4), (lb, TW * 3 / 4)):
        boxed_text(d, cx, TH - 120, txt, sf(56, 'Heavy'), (15, 15, 18), (255, 255, 255), radius=14, center=True)
    boxed_text(d, TW / 2, 60, words[0], condensed(150), YELLOW, (10, 10, 10), radius=18, center=True)
    return img

def style_textfree(hero, words, badge_text):
    """No text at all (the title does the talking) — strong grade + vignette. Good A/B test partner."""
    img = grade(cover(hero), 1.25, 1.15).convert('RGBA')
    v = Image.new('L', (TW, TH), 255); ImageDraw.Draw(v).ellipse((-TW * 0.15, -TH * 0.2, TW * 1.15, TH * 1.2), fill=0)
    sh = Image.new('RGBA', (TW, TH), (0, 0, 0, 0)); sh.putalpha(v.filter(ImageFilter.GaussianBlur(140)).point(lambda v_: int(v_ * 0.55))); img.alpha_composite(sh)
    return img

STYLE_FUNCS = {'mosaic_r': style_mosaic_r, 'pop': None, 'cinematic': None, 'collage': None, 'minimal': None, 'grid4': style_grid4, 'split': style_split,
               'strips': style_strips, 'mosaic': style_mosaic, 'polaroid': style_polaroid}

def make(nums=None):
    """Render every text variant in every style. project.json:
      "thumbnail_styles": ["cinematic", "collage", "grid4", "split", "strips", "mosaic", "polaroid", "minimal", "pop"]
      "thumbnail_cutout": false     → no subject cut-out ('pop') — e.g. when the user doesn't want people highlighted
      "thumbnail_face_frames": [N…] → candidate numbers showing the creator; they appear in ~"thumbnail_face_share"
                                       (default 1/3) of the thumbnails — never all of them
    Frame order (candidate numbers): 1st = hero scenery; the rest feed the collages (more = more variety)."""
    cands = json.load(open(os.path.join(OUT, 'candidates.json')))
    nums = nums or [c['n'] for c in cands[:6]]
    variants = PCFG.get('variants') or CFG.get('thumbnail_variants') or [CFG.get('thumbnail_text') or [CFG.get('output_name', 'MY TRIP').replace('_', ' ').upper()]]
    btxt = PCFG.get('badge', CFG.get('thumbnail_badge', ''))
    styles = CFG.get('thumbnail_styles') or ['cinematic', 'collage', 'grid4', 'split', 'strips', 'mosaic', 'polaroid', 'minimal', 'pop']
    if CFG.get('thumbnail_cutout', True) is False: styles = [s for s in styles if s != 'pop']
    big = {c['n']: grab(c['file'], c['t'], 3840, 2160) for c in cands if c['n'] in nums}
    fr = [big[n].resize((TW, TH), Image.LANCZOS) for n in nums]
    outs = []
    def save(im, name):
        if im is None: print(f'skipped {name}: no clear subject'); return
        p = os.path.join(DELIVER, name); im.convert('RGB').save(p, quality=92, optimize=True)
        if os.path.getsize(p) > 2_000_000: im.convert('RGB').save(p, quality=82, optimize=True)
        outs.append(p)
    for f in glob.glob(os.path.join(DELIVER, 'thumb_*.jpg')): os.remove(f)
    FACE_HITS.clear()
    faces = [n for n in PCFG.get('face_frames', CFG.get('thumbnail_face_frames', [])) if n in nums]   # frames showing the creator
    scen = [n for n in nums if n not in faces]
    fr = [big[n].resize((TW, TH), Image.LANCZOS) for n in scen]
    ffr = {n: face_centered(big[n].resize((TW, TH), Image.LANCZOS), 0.9) for n in faces}   # face stays in narrow panels
    share = float(CFG.get('thumbnail_face_share', 0.33)); fk = 0
    k = 0
    for v, words in enumerate(variants, 1):
        for si, st in enumerate(styles):
            r = fr[k % len(fr):] + fr[:k % len(fr)]; k += 1            # rotate frames so every thumbnail looks different
            use_face = faces and ((k * share) % 1 + share > 1 - 1e-9 or st == 'pop')
            if use_face:                                                 # creator's face in ~share of thumbnails:
                fn_ = faces[fk % len(faces)]; fk += 1                    # hero for single-image styles, a panel in collages
                full = big[fn_].resize((TW, TH), Image.LANCZOS)
                r = [full] + r if st in ('cinematic', 'minimal', 'mosaic', 'split') else (
                    [ffr[fn_]] + r if st in ('collage', 'strips') else r[:1] + [ffr[fn_]] + r[1:])
            if st == 'pop':
                if not use_face: continue                                # subject focus is only used on the creator
                im = style_pop(big[fn_], words, btxt)
            elif st == 'cinematic': im = style_cinematic(r[0], words, btxt)
            elif st == 'minimal': im = style_minimal(r[0], words, btxt)
            elif st == 'collage': im = style_collage(r[:3], words, btxt)
            else: im = STYLE_FUNCS[st](r, words, btxt)
            save(im, f'thumb_{v}_{st}.jpg')
        for j in range(int(CFG.get('thumbnail_extra_mosaics', 0))):     # more of the favourite layout, new frames
            r = fr[(k + 3 * j + 5) % len(fr):] + fr[:(k + 3 * j + 5) % len(fr)]
            save((style_mosaic if j % 2 == 0 else style_mosaic_r)(r, words, btxt), f'thumb_{v}_mosaic_x{j + 1}.jpg')
    ims = [Image.open(p).resize((640, 360)) for p in outs]
    S = Image.new('RGB', (1280, 360 * ((len(ims) + 1) // 2)), (20, 20, 20)); Fn = sf(28, 'Bold')
    for k, (p, im) in enumerate(zip(outs, ims)):
        ImageDraw.Draw(im).text((10, 320), os.path.basename(p)[6:-4], font=Fn, fill=(255, 255, 0), stroke_width=3, stroke_fill=(0, 0, 0))
        S.paste(im, ((k % 2) * 640, (k // 2) * 360))
    S.save(os.path.join(DELIVER, 'all_thumbnails.jpg'), quality=85)
    print(f'{len(outs)} thumbnails → {os.path.relpath(DELIVER, P())}/  (overview: all_thumbnails.jpg)')
    if FACE_HITS: print('WARNING: text could not avoid a face in: ' + ', '.join(f'{s}' for s, _ in FACE_HITS) + ' — check them')

def add_frames(specs):
    """Add hand-picked frames as candidates: thumbnails.py add CLIP@SECONDS ..."""
    p = os.path.join(OUT, 'candidates.json'); cands = json.load(open(p)) if os.path.exists(p) else []
    for sp in specs:
        f, t = sp.rsplit('@', 1); cands.append(dict(n=max([c['n'] for c in cands] + [-1]) + 1, file=f, t=float(t), seg='', score=0, people=0, shot=-1))
        print(cands[-1]['n'], f, t)
    json.dump(cands, open(p, 'w'), indent=1)

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'pick': pick()
    elif cmd == 'make': make([int(x) for x in sys.argv[2:]] or None)
    elif cmd == 'add': add_frames(sys.argv[2:])
    else: sys.exit(__doc__)
