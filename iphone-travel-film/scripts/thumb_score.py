"""Score finished thumbnails against what is measured to get clicks, so the strongest ones can be picked
(and weak ones remade) before anything is uploaded.

  thumb_score.py [DIR]       scores every .jpg in DIR (default renders/thumbnails), writes thumb_scores.md there

Each check maps to a published finding (see references/thumbnails.md, "What the data says"):
  focus      one clear focal point — share of Apple Vision attention saliency in its strongest region
             (busy collages spread attention over many panels and score low)
  contrast   luminance RMS contrast; colour  Hasler–Süsstrunk colourfulness (bright, saturated > muted, dark)
  face       largest face height / frame height (breakout thumbnails: a clear face, roughly ¼–⅓ of the frame)
  text       the headline is still read by Vision OCR at phone-feed size (320 px wide); words on the thumbnail
             (3–5 at most), and the bottom-right duration corner stays clear
  clutter    edge density at phone size (fine detail everywhere = noise when small)
The total is a heuristic ranking, not a CTR prediction: confirm with YouTube Test & Compare."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageFilter
from common import P

def _handler(img, name):
    import Vision
    from Foundation import NSURL
    tmp = P('tmp', name); img.convert('RGB').save(tmp, quality=92)
    return Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(tmp), None)

def saliency_focus(img):
    """Share of the attention heat map inside its strongest 3×3-cell window (68×68 map → ~1/25 of the frame)."""
    import Vision, Quartz
    h = _handler(img, 'score_sal.jpg'); rq = Vision.VNGenerateAttentionBasedSaliencyImageRequest.alloc().init()
    h.performRequests_error_([rq], None); r = rq.results()
    if not r: return 0.0
    pb = r[0].pixelBuffer(); Quartz.CVPixelBufferLockBaseAddress(pb, 1)
    w, hh, bpr = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb), Quartz.CVPixelBufferGetBytesPerRow(pb)
    m = np.frombuffer(bytes(Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * hh)), np.float32).reshape(hh, bpr // 4)[:, :w].copy()
    Quartz.CVPixelBufferUnlockBaseAddress(pb, 1)
    m = np.clip(m, 0, None); tot = m.sum() or 1.0
    k = max(2, w // 5); c = np.cumsum(np.cumsum(np.pad(m, ((1, 0), (1, 0))), 0), 1)
    win = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return float(win.max() / tot)

def face_height(img):
    import Vision
    h = _handler(img, 'score_face.jpg'); rq = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    h.performRequests_error_([rq], None); fs = rq.results() or []
    return max((float(o.boundingBox().size.height) for o in fs), default=0.0)

def ocr(img):
    import Vision
    h = _handler(img, 'score_ocr.jpg'); rq = Vision.VNRecognizeTextRequest.alloc().init()
    rq.setRecognitionLevel_(0); rq.setUsesLanguageCorrection_(False)
    h.performRequests_error_([rq], None)
    out = []
    for o in rq.results() or []:
        b = o.boundingBox(); out.append((str(o.topCandidates_(1)[0].string()), b.origin.x, b.origin.y, b.size.width, b.size.height))
    return out

def colourfulness(a):
    rg = a[..., 0] - a[..., 1]; yb = 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    return float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))

def score(path):
    im = Image.open(path).convert('RGB').resize((1280, 720), Image.LANCZOS)
    a = np.asarray(im, np.float32); lum = a @ [0.2126, 0.7152, 0.0722]
    small = im.resize((320, 180), Image.LANCZOS)
    edges = np.asarray(small.convert('L').filter(ImageFilter.FIND_EDGES), np.float32)
    full, phone = ocr(im), ocr(small.resize((1280, 720), Image.BICUBIC))   # phone: what survives a 320 px feed
    words_full = sum(len(t.split()) for t, *_ in full)
    big = max(full, key=lambda r: r[4], default=None)
    head_ok = bool(big) and any(big[0].lower().replace(' ', '') in t.lower().replace(' ', '') for t, *_ in phone)
    corner = any(x + w > 0.80 and y < 0.18 for _, x, y, w, _h in full)   # Vision y is bottom-up
    m = dict(focus=saliency_focus(im), contrast=float(lum.std() / 255), colour=colourfulness(a) / 100,
             face=face_height(im), words=words_full, headline=big[0] if big else '', head_ok=head_ok,
             corner=corner, clutter=float((edges > 40).mean()))
    f = m['face']
    s = (40 * min(m['focus'] / 0.45, 1)                    # one focal point
         + 15 * min(m['contrast'] / 0.28, 1)               # light/dark contrast
         + 15 * min(m['colour'] / 0.60, 1)                 # saturated colour
         + 15 * (1.0 if 0.18 <= f <= 0.6 else 0.6 if f > 0.08 else 0.0)   # clear face, big enough to read
         + 10 * (1.0 if (head_ok and m['words'] <= 5) or m['words'] == 0 else 0.4 if head_ok else 0.0)
         + 5 * (1 - min(m['clutter'] / 0.35, 1))
         - (5 if corner else 0))
    m['score'] = round(s, 1)
    return m

def main():
    d = sys.argv[1] if len(sys.argv) > 1 else P('renders', 'thumbnails')
    fs = sorted(f for f in glob.glob(os.path.join(d, '*.jpg')) if not os.path.basename(f).startswith('all_'))
    try:
        from tqdm import tqdm; it = tqdm(fs, desc='scoring', unit='thumb')
    except ImportError:
        it = fs
    rows = [(os.path.basename(f), score(f)) for f in it]
    rows.sort(key=lambda r: -r[1]['score'])
    L = ['# Thumbnail scores', '', 'Heuristic (focus 40, contrast 15, colour 15, face 15, phone-readable text 10, '
         'clutter 5, −5 if text sits in the duration corner). Confirm the top picks with YouTube Test & Compare.', '',
         '| # | file | score | focus | contrast | colour | face h | words | headline readable at 320 px | clutter |',
         '|---|---|---|---|---|---|---|---|---|---|']
    for k, (n, m) in enumerate(rows, 1):
        L.append(f"| {k} | {n} | {m['score']} | {m['focus']:.2f} | {m['contrast']:.2f} | {m['colour']:.2f} | {m['face']:.2f} | "
                 f"{m['words']} | {'yes' if m['head_ok'] else 'NO'} {m['headline'][:18]} | {m['clutter']:.2f} |")
    open(os.path.join(d, 'thumb_scores.md'), 'w').write('\n'.join(L) + '\n')
    for n, m in rows[:10]: print(f"{m['score']:5.1f}  {n}")
    print(f'{len(rows)} scored → {os.path.join(d, "thumb_scores.md")}')

if __name__ == '__main__':
    main()
