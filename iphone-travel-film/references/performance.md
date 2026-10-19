# Performance and memory on Apple Silicon

## Encoder
- Use `hevc_videotoolbox -prio_speed 1`: it's noticeably faster at the same quality (SSIM).
- About 2 parallel encode sessions saturate the media engine. More sessions add RAM but no speed, so keep
  `JOBS=2`.
- CPU filters (fps, Lanczos scale, overlay, fade) cost almost nothing, because the encoder is the bottleneck.
- Encode overlays with the hardware ProRes 4444 encoder (alpha kept); it's faster than PNG.

## Memory pitfalls (both seen in practice)
1. **Raw 4K RGBA frames piped into an ffmpeg that also decodes 4K.** If Python draws slower than ffmpeg
   decodes, the overlay filter queues decoded frames with no limit, and several such jobs can exhaust RAM and
   freeze the machine. Fix: render overlays to their own file first (`render_overlay`), then composite two
   files.
2. **Audio and video from the same demuxer.** ffmpeg reads video ahead to feed the faster audio path and
   buffers gigabytes of decoded frames per job. Fix: open the source twice (`-an` for video, `-vn` for
   audio).

`compose.py` runs every ffmpeg under an RSS watchdog (`MEM_LIMIT_GB`, default 5) that kills a runaway job
instead of letting it freeze the machine.

## Analysis jobs
- Long steps run in a visible terminal tab with tqdm progress bars.
- Decode once at low resolution and cache: frames, metrics, camera motion, Vision results, speech and CLIP
  embeddings are all reused by later steps.
- Apple Vision and tracking use one process per core. CLIP and Whisper use the GPU. Reverse geocoding is
  limited to 1 request per second by the Nominatim usage policy.

## Waiting on jobs
Match long jobs by their exact script path (`pgrep -f 'scripts/render_all.py'`), never by a bare word: a wait
loop whose own command line contains the word matches itself and never ends. Report % progress to the user
while waiting (read the tqdm line or count finished outputs) — never wait silently.
