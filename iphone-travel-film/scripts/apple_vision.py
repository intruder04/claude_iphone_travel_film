"""Step 4b — extra Apple Vision passes on the Neural Engine (1 fps analysis frames, one process per core):

  text      VNRecognizeTextRequest — signs, shop names, station names ("Starbucks", "京都駅") → what a shot is OF
  horizon   VNDetectHorizonRequest — camera roll angle (more reliable than line detection)
  faces     VNDetectFaceRectanglesRequest roll — faces lying at ±90° reveal a clip recorded sideways
  print     VNGenerateImageFeaturePrintRequest — image fingerprints for "same subject, same intent" grouping
  upright   for vertical clips: classification confidence of the frame at 0/90/-90° → which way is up

Outputs: meta/apple_vision.json, meta/fprint/<clip>.npy      Usage: apple_vision.py [CLIP ...]"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import P, jload, jsave, LANG
from tqdm import tqdm

def _req_handler(path):
    import Vision
    from Foundation import NSURL
    return Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)

def _fprint_vec(obs):
    d = bytes(obs.data()); n = obs.elementCount()
    return np.frombuffer(d, np.float32 if obs.elementType() == 1 else np.float64)[:n].astype(np.float32)

def _clip(args):
    import Vision
    from PIL import Image
    clip, portrait = args
    fs = sorted(glob.glob(P('frames', clip, '*.jpg')))[::2]
    out = dict(text=[], horizon=[], face_roll=[], upright=None); vecs = []
    langs = ['en-US'] + ({'ja': ['ja-JP'], 'zh': ['zh-Hans', 'zh-Hant'], 'ko': ['ko-KR']}.get(LANG, []))
    for k, p in enumerate(fs):
        h = _req_handler(p)
        tx = Vision.VNRecognizeTextRequest.alloc().init(); tx.setRecognitionLanguages_(langs); tx.setRecognitionLevel_(0)
        hz = Vision.VNDetectHorizonRequest.alloc().init()
        fc = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        fp = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
        h.performRequests_error_([tx, hz, fc, fp], None)
        for o in (tx.results() or []):
            c = o.topCandidates_(1)[0]
            if c.confidence() > 0.5 and len(c.string().strip()) > 2: out['text'].append([k, c.string()])
        out['horizon'].append(round(float(np.degrees(hz.results()[0].angle())), 2) if hz.results() else None)
        rolls = [o.roll() for o in (fc.results() or []) if o.roll() is not None]
        out['face_roll'].append([round(float(np.degrees(r)), 0) for r in rolls])
        if fp.results(): vecs.append(_fprint_vec(fp.results()[0]))
    if vecs: np.save(P('meta/fprint', clip + '.npy'), np.stack(vecs))
    if portrait and fs:                       # which rotation looks most like a normal photo?
        im = Image.open(fs[len(fs) // 2]).convert('RGB'); sc = {}
        for ang in (0, 90, -90):
            q = P('tmp', f'up_{os.getpid()}.jpg'); im.rotate(ang, expand=True).save(q)
            h = _req_handler(q); cl = Vision.VNClassifyImageRequest.alloc().init(); fc = Vision.VNDetectFaceRectanglesRequest.alloc().init()
            h.performRequests_error_([cl, fc], None)
            top = sorted([c.confidence() for c in (cl.results() or [])], reverse=True)[:5]
            upright_faces = sum(1 for o in (fc.results() or []) if o.roll() is not None and abs(float(np.degrees(o.roll()))) < 30)
            sc[ang] = round(float(sum(top)) + 0.8 * upright_faces, 3)
        out['upright'] = sc
    return clip, out

if __name__ == '__main__':
    from multiprocessing import Pool
    idx = jload('meta/index.json'); os.makedirs(P('meta/fprint'), exist_ok=True)
    res = jload('meta/apple_vision.json', {})
    todo = [(r['file'], r['portrait']) for r in idx if (not sys.argv[1:] or r['file'] in sys.argv[1:]) and r['file'] not in res]
    with Pool(os.cpu_count()) as p:
        for c, o in tqdm(p.imap_unordered(_clip, todo), total=len(todo), desc='Apple Vision: text, horizon, faces, fingerprints', unit='clip'):
            res[c] = o
            if len(res) % 25 == 0: jsave('meta/apple_vision.json', res, None)
    jsave('meta/apple_vision.json', res, None); print('done')
