# iPhone Travel Film — a Claude Code skill

**Turn hundreds of raw iPhone travel clips into a finished, YouTube-ready 4K HDR travel film on your Mac,
plus a set of thumbnails to choose from.** Claude watches the footage, works out where every clip was shot,
picks the best moments, and adds animated location titles and tracked 📍 landmark labels. It renders on
Apple Silicon's media engines and checks the HDR before you upload.

Works for any trip, in any country.

## What it does
- **Content-aware auto edit**: scores every second of every clip (sharpness, shake, exposure, Apple
  aesthetics score) and drops blurry, shaky, dark and duplicate shots. It thins out repetitive scenes (forest
  walks, endless gates), cuts on quiet audio so speech isn't chopped, and fits your target length (5–30 min).
- **Split by location from GPS metadata**: reverse geocoding (OpenStreetMap) plus Claude checking the
  footage, so a title says what's actually on screen.
- **Animated titles that appear only when the location changes**: 4 styles to choose from, rendered on your
  own footage. City changes get a cinematic chapter card. Optional local-script names (日本語, Ελληνικά,
  العربية …).
- **📍 Landmark callouts on aerial shots**: Apple-emoji pins whose labels stick to buildings as the plane
  moves, with homography tracking, drift checks and labels that never overlap.
- **Animal labels**: once per species, short, tracked. Includes a text search ("a cicada on a red gate") to
  find small creatures the detectors miss.
- **Horizon levelling** for genuinely tilted shots, **dual-camera selfies** kept, **vertical clips** on a
  blurred fill.
- **4K HLG HDR that YouTube recognises** (BT.2020 / HLG in both bitstream and container), −14 LUFS audio,
  plus a 1080p SDR preview, all verified automatically.
- **YouTube thumbnails** in trendy styles: subject cut-out with outline (Apple Vision "lift subject"), bold
  text, flag badge, collage, cinematic.

## Built for Apple Silicon
| Work | Runs on |
|---|---|
| Decode / encode 4K HEVC 10-bit | VideoToolbox media engines (`hevc_videotoolbox -prio_speed 1`, 2 sessions) |
| Scene tags, duplicate detection, text search | GPU, PyTorch MPS (OpenCLIP) |
| Aesthetics, animals, people, subject cut-outs | Neural Engine (Apple Vision framework) |
| HDR → SDR previews | GPU, libplacebo on Vulkan/MoltenVK/Metal |
| Tracking, analysis | all CPU cores |

Memory-safe on a 16 GB Mac: bounded pipelines plus an RSS watchdog per ffmpeg. Every long step shows
% progress. Measured: 117 minutes of 4K HDR became a 27-minute film in about an hour of processing on an M4
(see `iphone-travel-film/references/performance.md`).

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
(PyTorch, OpenCV, OpenCLIP, pyobjc) inside the skill folder.

## Use
In Claude Code, say something like:

> Make a travel film from the iPhone videos in ~/Movies/Portugal2026, about 15 minutes, no music.

Claude asks a few questions first (source folder, length, music, whether online location lookups are OK,
must-keep moments, landmark labels, animals, selfies, titles, thumbnail text). It then runs the pipeline and
shows you title samples, check sheets and thumbnails along the way. Your original files are never modified;
everything goes into a new project folder.

## Privacy
- Your videos stay on your Mac. All analysis runs locally.
- The only network use is optional: GPS coordinates are sent to OpenStreetMap (Nominatim / Overpass) to look
  up place names, after you agree. Model weights are downloaded once by `setup.sh` / OpenCLIP.

## Keywords
iPhone video editor · travel vlog · travel film · trip video · vacation video · holiday video · highlight
reel · automatic video editing · AI video editor · Claude Code skill · ffmpeg · 4K HDR · HLG · Dolby Vision ·
YouTube HDR · GPS location titles · geotag · lower third · map pin · landmark labels · motion tracking ·
YouTube thumbnail generator · Apple Silicon · M1 M2 M3 M4 · VideoToolbox · Metal · Neural Engine · Apple
Vision · CLIP · macOS

Suggested GitHub topics: `claude-code`, `claude-skill`, `video-editing`, `travel-vlog`, `iphone`, `hdr`,
`ffmpeg`, `apple-silicon`, `youtube`, `thumbnail-generator`.

## License
MIT
