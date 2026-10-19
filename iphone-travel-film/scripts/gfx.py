"""Overlay graphics (4K RGBA frames): location titles (4 styles), landmark callouts (📍 pin) and animal labels.

Colours are authored as HLG signal values: diffuse white = 75% HLG (~203 nits) so text
is comfortable on HDR screens and maps to normal white on SDR. Text always sits on a
dark scrim/pill for >= 7:1 contrast (WCAG AAA) regardless of the footage behind it.
"""
import math, os, sys, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from common import CFG
except SystemExit:                      # allow importing gfx without a project (e.g. quick previews)
    CFG = {}

W, H = 3840, 2160
SAFE = 0.05                      # 5% title-safe margin
WHITE = (191, 191, 191)          # 75% HLG = reference white
SOFT = (160, 160, 160)           # secondary text (still > 7:1 on the dark pill)
ACCENT = tuple(CFG.get('accent_rgb', (200, 70, 45)))   # decorative only (never carries information)
SCRIM = (0, 0, 0)

F = '/System/Library/Fonts/'
def sf(size, weight='Semibold'):
    """San Francisco (Latin, Cyrillic, Greek) with a named weight."""
    f = ImageFont.truetype(F + 'SFNS.ttf', size)
    try: f.set_variation_by_name(weight)
    except Exception: pass
    return f

# macOS system fonts for the local script shown under place names (project.json "local_language")
_LOCAL = {
    'ja': (['ヒラギノ角ゴシック W6.ttc', 'Hiragino Sans GB.ttc'], ['ヒラギノ明朝 ProN.ttc']),
    'zh': (['PingFang.ttc', 'Hiragino Sans GB.ttc', 'STHeiti Medium.ttc'], ['Supplemental/Songti.ttc']),
    'ko': (['AppleSDGothicNeo.ttc'], ['Supplemental/AppleMyungjo.ttf']),
    'th': (['Supplemental/Thonburi.ttc', 'Thonburi.ttc'], []),
    'ar': (['SFArabic.ttf', 'GeezaPro.ttc'], []),
    'he': (['SFHebrew.ttf'], []),
    'hi': (['Kohinoor.ttc', 'Supplemental/Devanagari Sangam MN.ttc'], []),
    'el': (['SFNS.ttf'], []), 'ru': (['SFNS.ttf'], []), 'uk': (['SFNS.ttf'], []),
}
_FALLBACK = ['Supplemental/Arial Unicode.ttf', 'SFNS.ttf']
def local_font(size, serif=False):
    lang = CFG.get('local_language', '')
    sans, ser = _LOCAL.get(lang, ([], []))
    for name in (ser if serif else []) + sans + _FALLBACK:
        if os.path.exists(F + name):
            try: return ImageFont.truetype(F + name, size)
            except OSError: pass
    return sf(size)
CJK = CFG.get('local_language', '') in ('ja', 'zh', 'ko')

# ---------- easing ----------
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(t): t = clamp(t); return 1 - (1 - t) ** 3
def ease_in_out(t): t = clamp(t); return 3 * t * t - 2 * t * t * t
def back_out(t, s=1.4): t = clamp(t) - 1; return t * t * ((s + 1) * t + s) + 1
def env(t, t_in, t_out, fade=0.45):
    """0..1 visibility envelope with fades at both ends."""
    return clamp((t - t_in) / fade) * clamp((t_out - t) / fade)

def blank(): return Image.new('RGBA', (W, H), (0, 0, 0, 0))
def rgba(c, a): return (c[0], c[1], c[2], int(255 * clamp(a)))

def text_w(d, s, f, spacing=0):
    if not s: return 0
    return d.textlength(s, font=f) + spacing * (len(s) - 1)
def draw_tracked(d, xy, s, f, fill, spacing=0):
    x, y = xy
    if spacing == 0: d.text((x, y), s, font=f, fill=fill); return
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill); x += d.textlength(ch, font=f) + spacing

_SCRIMS = {}
def soft_scrim(img, box, alpha, radius=120):
    """Feathered dark area behind text (keeps footage visible but text legible).
    The blurred mask is computed once per box and cached as a cropped sprite (memory-light)."""
    key = (tuple(int(v) for v in box), radius)
    if key not in _SCRIMS:
        pad = int(radius * 2.5); x0, y0, x1, y1 = key[0]
        bx0, by0 = max(0, x0 - pad), max(0, y0 - pad); bx1, by1 = min(W, x1 + pad), min(H, y1 + pad)
        m = Image.new('L', (bx1 - bx0, by1 - by0), 0)
        ImageDraw.Draw(m).rounded_rectangle((x0 - bx0, y0 - by0, x1 - bx0, y1 - by0), radius, fill=255)
        _SCRIMS[key] = ((bx0, by0), m.filter(ImageFilter.GaussianBlur(radius * 0.8)))
    (bx0, by0), m = _SCRIMS[key]
    layer = Image.new('RGBA', m.size, SCRIM + (0,)); layer.putalpha(m.point(lambda v: int(v * clamp(alpha))))
    img.alpha_composite(layer, (bx0, by0))

# =====================================================================
# Landmark callouts
# =====================================================================
CS = float(CFG.get('callout_scale', 0.7))   # callout size (1.0 = large)
NAME_F = sf(int(100 * CS), 'Semibold'); SUB_F = sf(int(66 * CS), 'Regular')
LABEL_BLUE = (14, 40, 92)       # dark navy; white text on it ~11:1 contrast (WCAG AAA)
def _seg_x(p1, p2, p3, p4):
    def o(a, b, c): return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (o(p1, p2, p3) * o(p1, p2, p4) < 0) and (o(p3, p4, p1) * o(p3, p4, p2) < 0)
def _seg_box(p1, p2, b, m=12):
    x0, y0, x1, y1 = b[0] - m, b[1] - m, b[2] + m, b[3] + m
    if all(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in (p1, p2)): return True
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    return any(_seg_x(p1, p2, e0, e1) for e0, e1 in edges)
def _leader(x, py, gx, gy, bx, by, bw, bh, CS):
    hx, hy = x + gx, py + gy
    if by + bh <= hy: return (hx, hy), (clamp(x, bx + 40 * CS, bx + bw - 40 * CS), by + bh)
    if by >= hy: return (hx, hy), (clamp(x, bx + 40 * CS, bx + bw - 40 * CS), by)
    return (hx, hy), ((bx if bx > x else bx + bw), clamp(hy, by + 30 * CS, by + bh - 30 * CS))

_PIN_SPRITES = {}
def _pin_sprite(s):
    """The real Apple Color Emoji 📍 glyph (iOS/macOS pin), scaled so its needle is s px tall.
    Returns (RGBA sprite, needle tip (x, y), ball centre (x, y), ball radius)."""
    if s in _PIN_SPRITES: return _PIN_SPRITES[s]
    f = ImageFont.truetype('/System/Library/Fonts/Apple Color Emoji.ttc', 160)
    g = Image.new('RGBA', (200, 200), (0, 0, 0, 0)); ImageDraw.Draw(g).text((20, 20), '📍', font=f, embedded_color=True)
    a = np.array(g); ys, xs = np.nonzero(a[..., 3] > 40); g = g.crop((xs.min() - 4, ys.min() - 4, xs.max() + 5, ys.max() + 3))
    a = np.array(g); al = a[..., 3] > 40; ys, xs = np.nonzero(al)
    tip = (float(xs[ys == ys.max()].mean()), float(ys.max()))
    red = (a[..., 0] > 150) & (a[..., 1] < 100) & al; ry, rx = np.nonzero(red)
    ball = (float(rx.mean()), float(ry.mean())); r = (rx.max() - rx.min()) / 2
    k = s / (tip[1] - ys.min())
    g = g.resize((max(1, round(g.width * k)), max(1, round(g.height * k))), Image.LANCZOS)
    # soft shadow so the pin separates from busy city backgrounds
    sh = Image.new('RGBA', (g.width + 12, g.height + 12), (0, 0, 0, 0)); m = g.getchannel('A').point(lambda v: int(v * 0.45))
    sh.paste((0, 0, 0, 255), (6, 8), m); sh = sh.filter(ImageFilter.GaussianBlur(3)); sh.alpha_composite(g, (6, 6))
    _PIN_SPRITES[s] = (sh, (tip[0] * k + 6, tip[1] * k + 6), (ball[0] * k + 6, ball[1] * k + 6), r * k)
    return _PIN_SPRITES[s]

def pin_geom(s):
    im, (tx, ty), (cx, cy), r = _pin_sprite(s)
    return (cx - tx, cy - ty), r            # ball centre relative to tip, ball radius

def draw_pin(img, x, y, s, a):
    """Paste the 📍 pin so its needle tip touches (x, y)."""
    im, (tx, ty), _, _ = _pin_sprite(s)
    if a < 0.999:
        im = im.copy(); al = im.getchannel('A').point(lambda v: int(v * clamp(a))); im.putalpha(al)
    img.alpha_composite(im, (int(round(x - tx)), int(round(y - ty))))

class Callouts:
    """Map-pin callouts that stick to tracked landmarks.
    Pin tip sits exactly on the landmark; a thin stem rises to a dark-blue rounded label.
    Label position is smoothed over time so it glides instead of jittering."""
    PIN = int(150 * CS)
    def __init__(self, marker='pin'):
        self.side = {}; self.overlaps = 0; self.marker = marker
    def _geom(self):
        # leader start relative to the target point: pin ball centre, or the point itself for 'dot'
        return pin_geom(self.PIN)[0] if self.marker == 'pin' else (0.0, 0.0)
    def frame(self, items, t):
        img = blank(); d = ImageDraw.Draw(img)
        boxes = []; leaders = []; pins = [(i['x'], i['y']) for i in items if i['alpha'] > 0.01]
        zones = [(i['x'], i['y'], i.get('zone', (110 * CS, 380 * CS))) for i in items if i['alpha'] > 0.01]
        for it in sorted(items, key=lambda i: (i['y'], i['x'])):
            a = it['alpha']
            if a <= 0.01: continue
            x, y = it['x'], it['y']
            nw = text_w(d, it['name'], NAME_F); sw = text_w(d, it.get('sub', ''), SUB_F)
            bw = nw + 120 * CS; bh = 150 * CS
            # pin drops in from above
            drop = back_out(clamp(a / 0.6), 1.6); py = y - (1 - drop) * 140 * CS if self.marker == 'pin' else y
            head_top = py - (self.PIN if self.marker == 'pin' else 30 * CS)                                  # pin drawn last (on top of connector + label)
            # --- label placement solver: candidate slots, no overlaps with labels/stems/pins, stay close to last slot
            stem = y - head_top + 60 * CS
            cands = []
            for tier in range(4):
                for dx in (-bw / 2, -bw + 90 * CS, -90 * CS, -bw - 120 * CS, 120 * CS):
                    cands.append((dx, -stem - bh - tier * (bh + 34 * CS), tier))
            zw = it.get('zone', (110 * CS, 380 * CS))[0]
            for dx in (zw + 60 * CS, -bw - zw - 60 * CS):               # beside the landmark (never below: buildings hang down from the pin)
                for dy in (-self.PIN * 0.64 - bh * 0.5, -stem - bh * 0.5, -stem - bh * 1.6):
                    cands.append((dx, dy, 2))                            # below the pin as last resort
            prev = self.side.get(it['name'])
            best = None
            for dx, dy, tier in cands:
                bx = clamp(x + dx, W * SAFE, W * (1 - SAFE) - bw); by = clamp(y + dy, H * SAFE, H * (1 - SAFE) - bh)
                pen = 0.0
                for ob in boxes:
                    ox = min(bx + bw, ob[2]) - max(bx, ob[0]) + 40; oy = min(by + bh, ob[3]) - max(by, ob[1]) + 30
                    if ox > 0 and oy > 0: pen += 1e6 + ox * oy
                (gx_, gy_) = self._geom(); L0, L1 = _leader(x, y, gx_, gy_, bx, by, bw, bh, CS)
                for ob in boxes:
                    if _seg_box(L0, L1, ob): pen += 8e6                    # my line through another label
                for (M0, M1) in leaders:
                    if _seg_x(L0, L1, M0, M1): pen += 8e6                  # lines crossing
                    if _seg_box(M0, M1, (bx, by, bx + bw, by + bh)): pen += 8e6   # another line through my label
                for px, pyy in pins:                                    # never cover a pin
                    if bx - 20 < px < bx + bw + 20 and by - 20 < pyy < by + bh + self.PIN + 20: pen += 8e5
                if bx - 20 < x < bx + bw + 20 and by < y < by + bh + 40: pen += 8e5   # nor its own pin
                for px, pyy, (zw_, zh_) in zones:                       # never cover any landmark (its building extends below the pin)
                    if bx < px + zw_ + 20 and bx + bw > px - zw_ - 20 and by < pyy + zh_ and by + bh > pyy - self.PIN: pen += 4e6
                d_prev = 0 if prev is None else math.hypot(bx - (x + prev[0]), by - (y + prev[1]))
                pen += tier * 60 + d_prev * 2.0
                if best is None or pen < best[0]: best = (pen, bx, by)
            _, tbx, tby = best
            bx, by = tbx, tby
            if prev is not None:                                         # glide toward the chosen slot…
                k = 0.18
                gbx = (x + prev[0]) + (tbx - (x + prev[0])) * k; gby = (y + prev[1]) + (tby - (y + prev[1])) * k
                (gx_, gy_) = self._geom(); G0, G1 = _leader(x, y, gx_, gy_, gbx, gby, bw, bh, CS)
                clash = any(min(gbx + bw, ob[2]) - max(gbx, ob[0]) > -20 and min(gby + bh, ob[3]) - max(gby, ob[1]) > -16 for ob in boxes) \
                        or any(_seg_box(G0, G1, ob) for ob in boxes) or any(_seg_x(G0, G1, M0, M1) for M0, M1 in leaders) \
                        or any(_seg_box(M0, M1, (gbx, gby, gbx + bw, gby + bh)) for M0, M1 in leaders)
                if not clash: bx, by = gbx, gby                          # …unless the glide would overlap: then snap
            (gx_, gy_) = self._geom(); leaders.append(_leader(x, y, gx_, gy_, bx, by, bw, bh, CS))
            self.overlaps += int(best[0] >= 1e6)
            self.side[it['name']] = (bx - x, by - y)
            boxes.append((bx, by, bx + bw, by + bh, x, head_top))
            pins.append((x, y))
            la = clamp((a - 0.3) / 0.7)
            if la <= 0: continue
            # connector: solid dark-blue tab joining the pin head to the label (one piece, like a map marker)
            (gx, gy) = self._geom(); (hx, hy), (ex, ey) = _leader(x, py, gx, gy, bx, by, bw, bh, CS)
            # thin navy leader line (faint light halo keeps it visible over dark buildings)
            d.line((hx, hy, ex, ey), fill=(191, 191, 191, int(80 * la)), width=9)
            d.line((hx, hy, ex, ey), fill=rgba(LABEL_BLUE, la), width=5)
            # label: dark blue rounded rectangle, white text centred both ways
            d.rounded_rectangle((bx - 3, by - 3, bx + bw + 3, by + bh + 3), int(46 * CS) + 3, fill=(0, 0, 0, int(90 * la)))
            d.rounded_rectangle((bx, by, bx + bw, by + bh), int(44 * CS), fill=rgba(LABEL_BLUE, la))
            l_, t_, r_, b_ = d.textbbox((0, 0), it['name'], font=NAME_F)
            d.text((bx + (bw - (r_ - l_)) / 2 - l_, by + (bh - (b_ - t_)) / 2 - t_), it['name'], font=NAME_F, fill=rgba(WHITE, la))
            if self.marker == 'pin':
                draw_pin(img, x, py, self.PIN, clamp(a / 0.4)); d = ImageDraw.Draw(img)
            else:                                                        # small navy dot with white ring
                r = 9 * CS * 1.4; ra = clamp(a / 0.4)
                d.ellipse((x - r - 4, y - r - 4, x + r + 4, y + r + 4), fill=(191, 191, 191, int(230 * ra)))
                d.ellipse((x - r, y - r, x + r, y + r), fill=rgba(LABEL_BLUE, ra))
        return img

# =====================================================================
# Location titles. info = dict(city, city_local, place, place_local, country, date, coords, new_city)
# Each returns an RGBA frame for local time t (seconds since the title starts); dur = time on screen.
# *_local strings are optional (shown in the local script when present).
# =====================================================================
def _join(*xs, sep='   ·   '): return sep.join(x for x in xs if x)

def title_lower_third(info, t, dur=5.0):
    """A — lower third: small caps date line, big place name, local-script name under it."""
    img = blank(); a = env(t, 0, dur, 0.5)
    if a <= 0: return img
    d = ImageDraw.Draw(img)
    x0, y0 = int(W * 0.065), int(H * 0.70)
    soft_scrim(img, (x0 - 140, y0 - 140, x0 + (2500 if info.get('desc') else 2100), y0 + 520), (0.72 if info.get('desc') else 0.55) * a)
    bar = ease_out(t / 0.7) * clamp((dur - t) / 0.5)
    d.rectangle((x0, y0, x0 + 14, y0 + int(380 * bar)), fill=rgba(ACCENT, a))
    p = ease_out((t - 0.15) / 0.8); off = int((1 - p) * 60)
    line1 = _join((info.get('area') or info['city']).upper() if info.get('new_city') or info.get('area') else '', info['date'], sep='  ·  ')
    draw_tracked(d, (x0 + 60, y0 + off), line1, sf(58, 'Semibold'), rgba(SOFT, a * p), 10)
    d.text((x0 + 56, y0 + 80 + off), info['place'], font=sf(150, 'Bold'), fill=rgba(WHITE, a * p))
    q = ease_out((t - 0.45) / 0.8)
    if info.get('desc'):                                   # one-line description of what the place is
        fd = sf(70, 'Semibold'); desc = info['desc']
        while text_w(d, desc, fd) > W * 0.62 and fd.size > 40: fd = sf(fd.size - 4, 'Medium')
        d.text((x0 + 62, y0 + 280 + int((1 - q) * 40)), desc, font=fd, fill=rgba(SOFT, a * q))
    elif info.get('place_local'):
        d.text((x0 + 62, y0 + 270 + int((1 - q) * 40)), info['place_local'], font=local_font(78), fill=rgba(SOFT, a * q))
    return img

def title_cinematic(info, t, dur=5.0):
    """B — cinematic centre card; on a new city the CITY is the hero, otherwise the place."""
    img = blank(); a = env(t, 0, dur, 0.6)
    if a <= 0: return img
    soft_scrim(img, (W * 0.16, H * 0.26, W * 0.84, H * (0.80 if info.get('desc') else 0.74)), 0.78 * a, 200)
    d = ImageDraw.Draw(img)
    big = info['city'].upper() if info.get('new_city') else info['place']
    fbig = sf(300 if info.get('new_city') else 200, 'Bold')
    sp = int(70 * (1 - ease_out(t / 2.4)) + 24)            # tracking tightens as it appears
    bw = text_w(d, big, fbig, sp)
    if bw > W * 0.64: fbig = sf(int(fbig.size * W * 0.64 / bw), 'Bold'); bw = text_w(d, big, fbig, sp)
    cy = H * 0.43
    draw_tracked(d, ((W - bw) / 2, cy - 150), big, fbig, rgba(WHITE, a), sp)
    rule = ease_in_out((t - 0.3) / 1.0) * 900
    d.rectangle((W / 2 - rule, cy + 230, W / 2 + rule, cy + 236), fill=rgba(ACCENT, a))
    q = ease_out((t - 0.7) / 0.8)
    if info.get('desc'):                                   # place name (new city) + one-line description
        lines = ([(info['place'], sf(84, 'Semibold'))] if info.get('new_city') else []) + [(info['desc'], sf(62, 'Medium'))]
    else:
        sub = _join(info['place'], info.get('place_local'), sep='   ') if info.get('new_city') else _join(info.get('place_local'), info['city'])
        lines = [(sub, local_font(84) if info.get('place_local') else sf(84, 'Medium'))]
    yy = cy + 290
    for txt, fs in lines:
        while text_w(d, txt, fs) > W * 0.64 and fs.size > 40: fs = sf(fs.size - 4, 'Medium')
        d.text(((W - text_w(d, txt, fs)) / 2, yy + (1 - q) * 30), txt, font=fs, fill=rgba(SOFT, a * q)); yy += fs.size * 1.35
    top = info.get('city_local') or (info.get('country', '').upper() if info.get('new_city') else '')
    if top:
        fj = local_font(70) if info.get('city_local') else sf(60, 'Semibold'); jw = text_w(d, top, fj, 30)
        draw_tracked(d, ((W - jw) / 2, cy - 300), top, fj, rgba(SOFT, a * ease_out((t - 0.2) / 0.8)), 30)
    return img

def title_pin(info, t, dur=5.0):
    """C — map-pin card: a pin drops, a dark card unfolds with name + city/country + coordinates."""
    img = blank(); a = env(t, 0, dur, 0.45)
    if a <= 0: return img
    d = ImageDraw.Draw(img)
    x0, y0 = int(W * 0.07), int(H * 0.73)
    drop = back_out(t / 0.7); py = y0 - 260 + 260 * drop
    u = ease_out((t - 0.55) / 0.7)
    fname = sf(118, 'Bold'); fsub = sf(56, 'Medium')
    sub = _join(_join(info['city'], info.get('country'), sep=', '), info.get('coords')) if info.get('new_city') \
        else _join(info.get('place_local'), info['city'])
    cw = max(text_w(d, info['place'], fname), text_w(d, sub, fsub)) + 330
    d.rounded_rectangle((x0, y0 - 40, x0 + 140 + (cw - 140) * u, y0 + 300), 150, fill=(10, 10, 12, int(205 * a)))
    cx, r = x0 + 130, 66
    d.ellipse((cx - r, py - r, cx + r, py + r), fill=rgba(ACCENT, a), outline=rgba(WHITE, a), width=8)
    d.polygon([(cx - 40, py + 48), (cx + 40, py + 48), (cx, py + 140)], fill=rgba(ACCENT, a))
    d.ellipse((cx - 22, py - 22, cx + 22, py + 22), fill=rgba(WHITE, a))
    ta = a * clamp((u - 0.55) / 0.45)
    if ta > 0:
        d.text((x0 + 260, y0 - 4), info['place'], font=fname, fill=rgba(WHITE, ta))
        d.text((x0 + 264, y0 + 156), sub, font=local_font(56) if info.get('place_local') and not info.get('new_city') else fsub, fill=rgba(SOFT, ta))
    return img

def title_vertical(info, t, dur=5.0):
    """D — vertical local-script name with a seal stamp (CJK languages only; otherwise falls back to B)."""
    if not (CJK and info.get('place_local')): return title_cinematic(info, t, dur)
    img = blank(); a = env(t, 0, dur, 0.6)
    if a <= 0: return img
    xr = int(W * 0.86)
    soft_scrim(img, (xr - 1150, H * 0.14, W * 0.98, H * 0.88), 0.72 * a, 220)
    d = ImageDraw.Draw(img)
    fj = local_font(150, serif=True)
    for i, ch in enumerate(info['place_local'][:9]):        # characters ink in one by one, top to bottom
        d.text((xr, H * 0.20 + i * 168), ch, font=fj, fill=rgba(WHITE, a * ease_out((t - 0.15 - i * 0.12) / 0.5)))
    s = back_out((t - 0.5) / 0.5, 2.2) if t > 0.5 else 0
    if s > 0 and info.get('city_local'):
        sz = int(190 * s); sx, sy = xr - 290, int(H * 0.20)
        st = Image.new('RGBA', (220, 220), (0, 0, 0, 0)); sd = ImageDraw.Draw(st)
        sd.rounded_rectangle((8, 8, 212, 212), 22, fill=rgba(ACCENT, a)); fc = local_font(80, serif=True)
        for i, ch in enumerate(info['city_local'][:2]): sd.text((70, 22 + i * 86), ch, font=fc, fill=rgba(WHITE, a))
        st = st.resize((max(1, sz), max(1, sz))); img.alpha_composite(st, (sx + (190 - sz) // 2, sy + (190 - sz) // 2))
        d = ImageDraw.Draw(img)
    q = ease_out((t - 0.8) / 0.8); yy = H * 0.66
    for s_, f_, c_ in [(info['place'], sf(96, 'Semibold'), WHITE),
                       (_join(info['city'], info['date'], sep='  ·  ') if info.get('new_city') else info['date'], sf(56, 'Regular'), SOFT)]:
        d.text((xr - 120 - text_w(d, s_, f_), yy + (1 - q) * 30), s_, font=f_, fill=rgba(c_, a * q)); yy += 130
    return img

STYLES = {'A_lower_third': title_lower_third, 'B_cinematic': title_cinematic,
          'C_map_pin': title_pin, 'D_vertical': title_vertical}
