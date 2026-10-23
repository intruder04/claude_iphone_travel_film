"""Step 4c — speech with word timestamps on the Apple GPU (MLX), so cuts never land mid-word, Claude can read what
was said ("look, the train!") when deciding what a clip is about, and the burned-in subtitles (subtitles.py) have
accurate timing. Sentence boundaries are kept too.

Engines (project.json "speech_engine"):
  parakeet (default)  NVIDIA Parakeet TDT 0.6B v3 via parakeet-mlx (CC BY 4.0, runs locally). Fast, few
                      hallucinations, per-sentence confidence. 25 European languages incl. English, Russian, Ukrainian,
                      German, French, Spanish — NOT Japanese/Chinese/Korean: their speech comes out as low-confidence
                      noise and is dropped (sentence confidence < "speech_min_conf", default 0.55).
  whisper             MLX-Whisper large-v3-turbo: 99 languages incl. CJK; use it when the filmmaker speaks one of those.
Only clips whose audio looks like speech are transcribed (voice-band energy, not wind).
project.json "speech_language" (e.g. "en", "ru") is recorded as the clip language (Whisper is also forced to it).
Output: meta/speech.json  {clip: {"lang": "en", "engine": "parakeet", "words": [[start, end, "word"], ...],
                                  "segs": [[start, end, "sentence"], ...], "text": "..."}}
Usage: speech.py [--engine parakeet|whisper] [--redo] [CLIP ...]"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import FF, SRC, P, CFG, jload, jsave
from tqdm import tqdm

MODELS = {'parakeet': 'mlx-community/parakeet-tdt-0.6b-v3', 'whisper': 'mlx-community/whisper-large-v3-turbo'}

def speechy(clip):
    """Cheap pre-filter: share of 0.1 s windows with voice-band energy dominating."""
    m = json.load(open(P('meta/metrics', clip + '.json')))
    rms, low = np.array(m['rms'] or [0]), np.array(m['low'] or [1])
    if len(rms) < 10: return 0.0
    loud = rms > max(0.01, np.median(rms) * 1.5)
    return float((loud & (low < 0.35)).mean())

def _script_lang(text):
    """Language guess from the alphabet when none is configured (only used to pick fonts and spacing)."""
    cyr = len(re.findall('[Ѐ-ӿ]', text)); lat = len(re.findall('[A-Za-z]', text))
    return 'ru' if cyr > lat else ('en' if lat else None)

def parakeet_engine():
    from parakeet_mlx import from_pretrained
    model = from_pretrained(MODELS['parakeet']); min_conf = float(CFG.get('speech_min_conf', 0.55))
    def run(wav):
        res = model.transcribe(wav, chunk_duration=120.0, overlap_duration=15.0)
        words, segs = [], []
        for s in res.sentences:
            if s.confidence < min_conf or not s.text.strip(): continue
            ws = []
            for tk in s.tokens:                          # sub-word tokens → words (a leading space starts a word)
                if not ws or tk.text.startswith(' '): ws.append([tk.start, tk.end, tk.text.strip()])
                else:
                    ws[-1][2] += tk.text
                    # punctuation tokens often carry the whole following silence: they never extend a word
                    if any(c.isalnum() for c in tk.text): ws[-1][1] = tk.end
            ws = [[round(a, 2), round(b, 2), w] for a, b, w in ws if w and '<unk>' not in w]   # untranscribable audio
            if ws: words += ws; segs.append([ws[0][0], ws[-1][1], s.text.strip()])
        text = ' '.join(w[2] for w in words)
        return dict(lang=CFG.get('speech_language') or _script_lang(text), engine='parakeet', words=words, segs=segs, text=text)
    return run

def whisper_engine():
    import mlx_whisper
    def run(wav):
        out = mlx_whisper.transcribe(wav, path_or_hf_repo=MODELS['whisper'], word_timestamps=True, condition_on_previous_text=False,
                                     verbose=None, language=CFG.get('speech_language') or None)
        words, segs = [], []
        for s in out.get('segments', []):               # drop hallucinations over wind/noise
            if s.get('no_speech_prob', 0) > 0.6 or s.get('avg_logprob', 0) < -1.0 or s.get('compression_ratio', 0) > 2.4: continue
            ws = [[round(w['start'], 2), round(w['end'], 2), w['word'].strip()] for w in s.get('words', [])]
            if ws: words += ws; segs.append([ws[0][0], ws[-1][1], s['text'].strip()])
        return dict(lang=out.get('language'), engine='whisper', words=words, segs=segs, text=' '.join(w[2] for w in words))
    return run

def main():
    args = sys.argv[1:]; engine = CFG.get('speech_engine', 'parakeet'); redo = False
    while args[:1] and args[0].startswith('--'):
        if args[0] == '--engine': engine, args = args[1], args[2:]
        elif args[0] == '--redo': redo, args = True, args[1:]
        else: sys.exit(__doc__)
    idx = jload('meta/index.json'); res = jload('meta/speech.json', {})
    todo = [r for r in idx if r.get('audio') and (not args or r['file'] in args) and (redo or r['file'] not in res)
            and (args or speechy(r['file']) > float(CFG.get('speech_threshold', 0.03)))]
    print(f'{len(todo)} clips look like they contain speech')
    run = parakeet_engine() if engine == 'parakeet' else whisper_engine()
    for r in tqdm(todo, desc=f'Transcribing ({engine}, MLX GPU)', unit='clip'):
        wav = P('tmp', 'speech.wav')
        subprocess.run([FF, '-v', 'error', '-y', '-i', os.path.join(SRC, r['file']), '-map', '0:a:0', '-ac', '1', '-ar', '16000', wav])
        res[r['file']] = run(wav)
        jsave('meta/speech.json', res, None)
    print(f"{sum(1 for v in res.values() if v['words'])} clips with speech")

if __name__ == '__main__':
    main()
