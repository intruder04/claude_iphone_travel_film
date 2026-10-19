"""Step 4 — content understanding on Apple hardware, two passes over the 1 fps analysis frames:

  clip   OpenCLIP ViT-B/16 on the GPU (PyTorch MPS): per-frame embeddings (near-duplicate detection, "repeating
         forest shots") + zero-shot scene tags from templates/tags.json (or the project's own tags.json)
  vision Apple Vision framework (Neural Engine) via pyobjc: aesthetics score, "utility" (receipts, screenshots),
         cats/dogs, people, scene labels, saliency boxes — one process per CPU core

Usage: understand.py [clip|vision|all]      Outputs: meta/clip/*.npy, meta/clip_tags.json, meta/vision.json"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import P, SKILL, jload, jsave
from tqdm import tqdm

def clip_pass():
    import torch, open_clip
    from PIL import Image
    from concurrent.futures import ThreadPoolExecutor
    dev = 'mps' if torch.backends.mps.is_available() else 'cpu'
    model, _, pre = open_clip.create_model_and_transforms('ViT-B-16-quickgelu', pretrained='openai', device=dev)
    model.eval(); model = model.half() if dev == 'mps' else model
    tok = open_clip.get_tokenizer('ViT-B-16-quickgelu')
    tp = P('tags.json') if os.path.exists(P('tags.json')) else os.path.join(SKILL, 'templates', 'tags.json')
    TAGS = json.load(open(tp))
    dt = torch.float16 if dev == 'mps' else torch.float32
    with torch.no_grad():
        te = model.encode_text(tok([f'a photo of {t}' for t in TAGS]).to(dev)); te = te / te.norm(dim=-1, keepdim=True)
    out = {}; pool = ThreadPoolExecutor(8)
    for r in tqdm(jload('meta/index.json'), desc=f'CLIP tagging ({dev.upper()})', unit='clip'):
        fs = sorted(glob.glob(P('frames', r['file'], '*.jpg')))[::2]
        if not fs: continue
        ims = list(pool.map(lambda f: pre(Image.open(f).convert('RGB')), fs)); embs = []
        with torch.no_grad():
            for i in range(0, len(ims), 128):
                e = model.encode_image(torch.stack(ims[i:i + 128]).to(dev).to(dt))
                embs.append((e / e.norm(dim=-1, keepdim=True)).float().cpu())
        e = torch.cat(embs); probs = (100 * (e.to(dev).to(dt) @ te.T).float()).softmax(-1).cpu().numpy()
        import numpy as np
        np.save(P('meta/clip', r['file'] + '.npy'), e.numpy())
        m = probs.mean(0); top = m.argsort()[::-1][:5]
        out[r['file']] = dict(tags=[(TAGS[i], round(float(m[i]), 3)) for i in top],
                              per_frame=[[TAGS[i] for i in p.argsort()[::-1][:2]] for p in probs])
    jsave('meta/clip_tags.json', out, None)

def _vision_clip(clip):
    import Vision
    from Foundation import NSURL
    out = []
    for p in sorted(glob.glob(P('frames', clip, '*.jpg')))[::2]:
        h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(p), None)
        a = Vision.VNCalculateImageAestheticsScoresRequest.alloc().init()
        an = Vision.VNRecognizeAnimalsRequest.alloc().init()
        hu = Vision.VNDetectHumanRectanglesRequest.alloc().init()
        cl = Vision.VNClassifyImageRequest.alloc().init()
        sal = Vision.VNGenerateAttentionBasedSaliencyImageRequest.alloc().init()
        h.performRequests_error_([a, an, hu, cl, sal], None)
        r = a.results()[0] if a.results() else None
        sb = [(o.boundingBox().origin.x, o.boundingBox().origin.y, o.boundingBox().size.width, o.boundingBox().size.height)
              for o in (sal.results()[0].salientObjects() or [])] if sal.results() else []
        out.append(dict(aes=round(r.overallScore(), 3) if r else None, util=bool(r.isUtility()) if r else None,
                        animals=[x.labels()[0].identifier() for x in (an.results() or [])],
                        humans=[round(o.boundingBox().size.width * o.boundingBox().size.height, 3) for o in (hu.results() or [])],
                        cls=[(c.identifier(), round(c.confidence(), 2)) for c in (cl.results() or []) if c.confidence() > 0.3][:12],
                        sal=[tuple(round(v, 3) for v in b) for b in sb]))
    return clip, out

def vision_pass():
    from multiprocessing import Pool
    clips = [r['file'] for r in jload('meta/index.json')]; res = {}
    with Pool(os.cpu_count()) as p:
        for c, o in tqdm(p.imap_unordered(_vision_clip, clips), total=len(clips), desc='Apple Vision (Neural Engine)', unit='clip'):
            res[c] = o
    jsave('meta/vision.json', res, None)

if __name__ == '__main__':
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if what in ('clip', 'all'): clip_pass()
    if what in ('vision', 'all'): vision_pass()
    print('done')
