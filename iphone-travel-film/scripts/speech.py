"""Step 4c — speech with word timestamps (MLX-Whisper on the Apple GPU), so cuts never land mid-word and
Claude can read what was said ("look, the train!") when deciding what a clip is about.

Only clips whose audio looks like speech are transcribed (voice-band energy, not wind). Whisper hallucinations
over wind/noise are filtered (low avg log-prob, high no-speech prob, repeated text).
Output: meta/speech.json  {clip: {"lang": "en", "words": [[start, end, "word"], ...], "text": "..."}}
Usage: speech.py [--model mlx-community/whisper-large-v3-turbo] [CLIP ...]"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import FF, SRC, P, jload, jsave
from tqdm import tqdm

MODEL = 'mlx-community/whisper-large-v3-turbo'

def speechy(clip):
    """Cheap pre-filter: share of 0.1 s windows with voice-band energy dominating."""
    m = json.load(open(P('meta/metrics', clip + '.json')))
    rms, low = np.array(m['rms'] or [0]), np.array(m['low'] or [1])
    if len(rms) < 10: return 0.0
    loud = rms > max(0.01, np.median(rms) * 1.5)
    return float((loud & (low < 0.35)).mean())

def main():
    import mlx_whisper
    args = sys.argv[1:]; model = MODEL
    if args[:1] == ['--model']: model, args = args[1], args[2:]
    idx = jload('meta/index.json'); res = jload('meta/speech.json', {})
    todo = [r for r in idx if r.get('audio') and (not args or r['file'] in args) and r['file'] not in res and speechy(r['file']) > 0.08]
    print(f'{len(todo)} clips look like they contain speech')
    for r in tqdm(todo, desc='Transcribing (MLX-Whisper, GPU)', unit='clip'):
        wav = P('tmp', 'speech.wav')
        subprocess.run([FF, '-v', 'error', '-y', '-i', os.path.join(SRC, r['file']), '-map', '0:a:0', '-ac', '1', '-ar', '16000', wav])
        out = mlx_whisper.transcribe(wav, path_or_hf_repo=model, word_timestamps=True, condition_on_previous_text=False, verbose=None)
        words = []
        for s in out.get('segments', []):
            if s.get('no_speech_prob', 0) > 0.6 or s.get('avg_logprob', 0) < -1.0 or s.get('compression_ratio', 0) > 2.4: continue
            words += [[round(w['start'], 2), round(w['end'], 2), w['word'].strip()] for w in s.get('words', [])]
        res[r['file']] = dict(lang=out.get('language'), words=words, text=' '.join(w[2] for w in words))
        jsave('meta/speech.json', res, None)
    print(f"{sum(1 for v in res.values() if v['words'])} clips with speech")

if __name__ == '__main__':
    main()
