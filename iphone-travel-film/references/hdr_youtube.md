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
