# iPhone Travel Film — a Claude Code skill

**Turn a folder of raw iPhone travel clips into a finished, YouTube-ready 4K HDR travel film on your Mac,
plus a set of thumbnails to choose from.** Claude looks at every clip, works out what it was filmed for and
where, keeps the best take of each moment, and adds animated location titles and tracked 📍 landmark labels.
It renders on Apple Silicon's media engines and checks the HDR before you upload.

Works for any trip, in any country.

## What it does
- **Understands every clip**: Claude reviews sheets of frames across each clip, together with the signs Apple
  Vision reads in the picture and what was said (on-device Whisper). It decides what each clip is for (a
  passing train, a rainbow, a shop interior) and which seconds hold that moment.
- **Keeps the best take**: when several clips show the same thing with the same intent, only the smoothest,
  sharpest, best-framed one stays.
- **Cuts like an editor**: cuts land when the camera is steady, never in the middle of a fast pan or zoom, and
  never in the middle of a spoken word. Shot length follows the content; your target length is a guide, not a
  quota.
- **Split by location from GPS metadata**: OpenStreetMap place lookups, checked against what's actually on
  screen.
- **Animated titles, only when the location changes**: 4 styles to choose from, rendered on your own
  footage. A city change fades to black and back in on a cinematic chapter card. Optional local-script names
  (日本語, Ελληνικά, العربية …).
- **📍 Landmark callouts on aerial shots**: Apple-emoji pins whose labels stick to the buildings as the plane
  moves. Only the steady holds are used, not the zooms. Includes drift checks and overlap-free label placement.
- **Animal labels**: shown once per species, the moment it first appears in the film, and tracked. Includes a
  text search ("a cicada on a red gate") to find small creatures the detectors miss.
- **Fixes**: levels tilted horizons, turns sideways-tagged clips back to landscape, and puts vertical clips on
  a blurred fill. Keeps dual-camera selfies.
- **4K HLG HDR that YouTube recognises** (BT.2020 / HLG signalled in both the bitstream and the container), −14
  LUFS audio, plus a 1080p SDR preview, all verified automatically.
- **YouTube thumbnails**: proposes text and graphic options first, then renders at least 10 thumbnails in
  current styles (subject cut-out with outline, bold text, flag badge, collage, cinematic).

## Built for Apple Silicon
| Work | Runs on |
|---|---|
| Decode / encode 4K HEVC 10-bit | VideoToolbox media engines |
| Scene tags, duplicate detection, text search | GPU, PyTorch MPS (OpenCLIP) |
| Speech with word timestamps | GPU, MLX (Whisper) |
| Aesthetics, signs and text, horizon, faces, animals, subject cut-outs | Neural Engine (Apple Vision) |
| HDR → SDR previews | GPU, libplacebo on Vulkan/MoltenVK/Metal |
| Camera motion, scene cuts (PySceneDetect), tracking | all CPU cores |

Every long step shows % progress. Memory use is bounded, and each ffmpeg runs under a watchdog, so a 16 GB
Mac stays responsive.

## Install
Requirements: macOS 14+ on Apple Silicon, [Homebrew](https://brew.sh), Python 3.11+,
[Claude Code](https://claude.com/claude-code).

```bash
git clone https://github.com/intruder04/claude_iphone_travel_film.git
```

```bash
cp -R claude_iphone_travel_film/iphone-travel-film ~/.claude/skills/
```

```bash
~/.claude/skills/iphone-travel-film/setup.sh
```

`setup.sh` installs `ffmpeg-full`, `exiftool` and `molten-vk` with Homebrew, and creates a Python venv
(PyTorch, MLX-Whisper, OpenCV, OpenCLIP, PySceneDetect, pyobjc) inside the skill folder.

## Use
In Claude Code, say something like:

> Make a travel film from the iPhone videos in ~/Movies/MyTrip, about 15 minutes, no music.

Claude asks a few questions first:
- where the clips are and how long the film should be
- music
- whether online location lookups are OK
- must-keep moments, landmark labels, animals and selfies
- title style
- thumbnail text

Then it runs the pipeline, showing you title samples, check sheets and thumbnail options along the way. Your
original files are never modified; everything goes into a new project folder.

## Privacy
- Your videos stay on your Mac. All analysis runs locally.
- The only network use is optional: GPS coordinates are sent to OpenStreetMap (Nominatim / Overpass) to look
  up place names, after you agree. Model weights are downloaded once.

## Keywords
iPhone video editor · travel vlog · travel film · trip video · vacation video · holiday video · highlight
reel · automatic video editing · AI video editor · Claude Code skill · ffmpeg · 4K HDR · HLG · Dolby Vision ·
YouTube HDR · GPS location titles · geotag · lower third · map pin · landmark labels · motion tracking ·
scene detection · YouTube thumbnail generator · Apple Silicon · VideoToolbox · Metal · Neural Engine ·
Apple Vision · MLX · Whisper · CLIP · macOS

Suggested GitHub topics: `claude-code`, `claude-skill`, `video-editing`, `travel-vlog`, `iphone`, `hdr`,
`ffmpeg`, `apple-silicon`, `youtube`, `thumbnail-generator`.

## License
MIT
