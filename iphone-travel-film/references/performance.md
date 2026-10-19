# Performance on Apple Silicon (measured on M4, 10 cores, 16 GB)

The test project was 402 clips, 117 minutes of 4K HDR (52 GB), turned into a 27-minute film.

| Step | Hardware | Time |
|---|---|---|
| Index (exiftool + ffprobe, 8 threads) | CPU | ~1 min |
| Reverse geocoding (1 req/s policy) | network | ~20 min for ~300 distinct spots |
| Analyse (decode + metrics, 4 clips at once) | VideoToolbox + CPU | ~25 min |
| CLIP ViT-B/16 tagging, 1 fps | GPU (MPS, fp16) | ~8 min |
| Apple Vision scoring, 1 fps, 10 processes | Neural Engine | ~2 min |
| Landmark tracking (per 30 s aerial clip, 8 processes) | CPU | ~1 min |
| Final render, 27 min of 4K60 HLG | 2× VideoToolbox HEVC | ~10–15 min |

## Encoder facts
- `hevc_videotoolbox -prio_speed 1`: ~1.6× faster at identical SSIM. Use it.
- 2 parallel encode sessions reach the encoder's ceiling (~1.7× real-time with filters). 3 or 4 sessions gave
  **no** extra speed and only added RAM (2.2 → 3.2 → 4.3 GB), so keep `JOBS=2`.
- CPU filters (fps, Lanczos scale, overlay, fade) cost almost nothing, because the encoder is the bottleneck.
- Overlays are encoded with the hardware ProRes 4444 encoder (alpha kept), 2× faster than PNG.

## Memory pitfalls (both seen in practice)
1. **Raw 4K RGBA frames piped into an ffmpeg that also decodes 4K.** When Python drew slower than ffmpeg
   decoded, the overlay filter queued decoded frames with no limit, and 4 such jobs passed 90 GB and froze the
   Mac. Fix: render overlays to their own file first (`render_overlay`), then composite two files.
2. **Audio and video from the same demuxer.** ffmpeg read video ahead to feed the fast audio path and buffered
   ~4 GB of decoded frames per job. Fix: open the source twice (`-an` for video, `-vn` for audio). Peak drops
   from 6.9 GB to 2.5 GB.

`compose.py` runs every ffmpeg under an RSS watchdog (`MEM_LIMIT_GB`, default 5) that kills a runaway job
instead of letting it freeze the machine.
