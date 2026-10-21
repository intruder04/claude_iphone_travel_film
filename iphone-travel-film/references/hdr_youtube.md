# HDR for YouTube

iPhone HDR video is **HLG (ARIB STD-B67), BT.2020, 10-bit HEVC** with a Dolby Vision 8.4 layer on top.
The pipeline keeps HLG end to end:

- **Decode:** VideoToolbox, 10-bit (`p010`). All filters run in `yuv420p10le`.
- **Overlays:** authored as HLG signal values. Pure RGB 255 would map to the 1000-nit peak, so text uses 75 %
  (191), the HLG reference white. Overlays are converted with the BT.2020 matrix before compositing.
- **SDR source clips** (screen recordings, messenger videos) are converted into HLG with `zscale`, so they
  sit correctly between HDR shots.
- **Encode:** `hevc_videotoolbox -profile:v main10 -pix_fmt p010le` at ~70 Mb/s. Colour tags are written to
  both the bitstream VUI (primaries 9 / transfer 18 / matrix 9) and the MOV `colr` atom.
- **Join** with the concat demuxer and stream copy (no re-encode). Audio is loudness-normalised to −14 LUFS,
  true peak −1.5 dBTP (YouTube's reference), AAC 320 kb/s.
- **Dolby Vision:** the DV RPU metadata cannot survive editing with ffmpeg. The output is plain HLG, which
  YouTube, iPhone/iPad/Mac, Android and HDR TVs play as HDR.

`verify.py` checks all of this. On YouTube, HDR processing can take a few hours after the upload. An "HDR"
badge appears in the quality menu once it's done; SDR viewers get YouTube's own tone-mapped version.

The SDR preview is made with libplacebo BT.2390 tone-mapping on the GPU (Vulkan → MoltenVK → Metal).

## Lesson learned: container + level (tested with 60 s uploads)
A film encoded by VideoToolbox with its default very short GOP (a keyframe every 0.2 s) and 120 Mb/s peaks was
labelled HEVC level 6.1. YouTube accepted the upload but only ever offered up to 1440p, with no HDR. The same footage
re-encoded at level 5.1/5.2 (keyframe every 2 s, ≤ 80 Mb/s peaks) got 4K HDR. The renderer now uses `-g 120 -maxrate 80M`,
and `verify.py` fails any file above level 5.2 or with more than one keyframe per second. If an upload doesn't get HDR,
upload a 60-second excerpt first: short clips process in minutes.

**Result of the A/B uploads:** same HEVC stream, MOV → no HDR; MP4 → HDR. The QuickTime `colr` box in MOV is type
`nclc`; MP4 gets `nclx`, which YouTube reads. The x265 MP4 also worked. So: **always deliver MP4**. VideoToolbox's
level follows the requested bitrate: ≤ 60 Mb/s (with `-maxrate 80M -g 120`) gives level 5.2; higher requests give 6.1,
which is untested on YouTube, so the renderer stays at 60M. Render once, straight from the source clips: a second
encode costs more quality than any upload-bitrate gain.

## Strip the iPhone's Dolby Vision metadata
iPhone HDR clips are Dolby Vision Profile 8.4: an HLG picture plus a per-frame Dolby Vision RPU. ffmpeg carries
that RPU into a new encode (VideoToolbox included), where it no longer matches the edited picture (titles,
fades, grading). Seen in practice: YouTube then made only AV1 HDR versions, and a Google TV Streamer (a
Dolby Vision device) showed a black screen with greyed-out controls. The same footage without the RPU got VP9
HDR and played in 4K HDR. `compose.py` and the final mux in `render_all.py` strip it (`-bsf:v dovi_rpu=strip=1`);
`verify.py` fails if any RPU is left. An already-rendered film can be fixed without re-encoding:
`ffmpeg -i film.mp4 -map 0 -c copy -bsf:v dovi_rpu=strip=1 -movflags +faststart film_fixed.mp4`.

## New upload plays everywhere except a TV device (black screen, greyed-out controls)
Seen with a Google TV Streamer: phone and browser played the new 4K60 HLG upload in HDR, but the TV app sat
at 0:00 with `Current Res 0x0` while buffering data (Stats for nerds). Other channels' videos uploaded the
same day failed the same way, so it is YouTube's first processing of new uploads, not the file. Re-uploading
doesn't help (creators report the same for 4K being capped at 1080p on TVs). What works: in YouTube Studio →
Editor → Trim & cut, remove the last frame and save. YouTube re-processes the video (keeping its link, views
and HDR) and the new versions play on the TV. Try it on a short unlisted test clip first if unsure.
Diagnose with `yt-dlp -F <url>`: HDR versions are formats 330–337 (VP9) and 694–701 (AV1).
