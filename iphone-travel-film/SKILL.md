---
name: iphone-travel-film
description: >-
  Turn a folder of raw iPhone travel videos (4K HDR / Dolby Vision HLG .MOV) into a finished, YouTube-ready
  travel film on an Apple Silicon Mac (M1/M2/M3/M4), fully automatic and content-aware. Use when the user wants
  to make a travel video, trip vlog, holiday / vacation movie, highlight reel or montage from iPhone footage;
  auto-edit or summarize hours of clips into a 5–30 minute film; split a video by location using GPS metadata;
  add animated location titles, city chapter cards, or map-pin landmark callouts that track buildings (e.g. from
  an airplane window); label animals; remove shaky, blurry and duplicate shots; level tilted horizons; keep
  dual-camera selfies; export 4K HLG HDR that YouTube recognises, with an SDR preview; and generate several
  trendy YouTube thumbnails (subject cut-out, bold text, flag badge) to choose from. Works for any country.
  Keywords: iPhone video editor, travel vlog, travel film, trip video, vacation video, holiday video, highlight
  reel, auto edit, automatic video editing, AI video editor, YouTube thumbnail maker, thumbnail generator,
  ffmpeg, HDR, HLG, Dolby Vision, 4K, YouTube HDR,
  GPS, geotag, location titles, lower third, map pin, landmark labels, motion tracking, Apple Silicon,
  VideoToolbox, Metal, Neural Engine, Apple Vision, CLIP, macOS.
---

# iPhone travel film

Builds a travel film from a folder of iPhone clips: it reads where and when each clip was shot, looks at the
footage, picks the best moments, adds titles and tracked labels, renders 4K HLG HDR, and checks the result.
Every heavy step runs on the Mac's media engines, GPU or Neural Engine, shows % progress, and keeps memory
bounded.

**Hard rules**
- Never modify, move, rename or re-encode the user's source files. All output goes into a new project folder.
- Before any step that sends data off the machine (reverse geocoding sends GPS coordinates to OpenStreetMap),
  ask first.
- Run long steps in a visible terminal tab with their progress bars, so the user can see % done.
- Memory: at most 2 parallel 4K render jobs (`JOBS=2`); 2 already saturate the encoder, and more only add RAM.
  `compose.py` has a per-ffmpeg RSS watchdog (`MEM_LIMIT_GB`, default 5). Never pipe raw 4K frames into an
  ffmpeg that also decodes 4K, and don't take audio from the same demuxer: both can exhaust RAM.
- Look at the footage. Contact sheets and gridded frames exist so you can verify places, landmarks, animals,
  tilt and tracking by eye. Metadata and detectors only produce candidates.

## 1. Ask before starting

Use AskUserQuestion (several questions per call) and record the answers in `project.json`:

1. **Source folder** with the iPhone videos (read-only), and where to create the project folder. Default: a new
   `<source>_edit` folder next to the source.
2. **Target length**: e.g. 5, 10, 15 or 25–30 minutes. Treat it as a guide: the content decides the final length.
3. **Music**: the skill keeps the original sound, loudness-normalised, and adds no music. Confirm that's
   wanted for now.
4. **Location lookups online**: OK to send GPS coordinates to OpenStreetMap (Nominatim/Overpass) for place
   names? If not, titles use only the names Claude can read from signs and landmarks, plus user input.
5. **Installing tools**: OK to install Homebrew packages (`ffmpeg-full`, `exiftool`, `molten-vk`) and a
   Python venv (~2 GB including PyTorch)? Run `setup.sh`.
6. **Must-keep moments**: e.g. the arrival flight, a specific event or person. Should aerial or skyline
   shots get **landmark callouts** (📍 pins whose labels follow the buildings)?
7. **People and animals**: keep dual-camera (front + back) selfies? Keep animals only when they do something
   interesting, and label each species once?
8. **Location titles**: neighbourhood/attraction names plus city names, shown only when the location
   changes. A city change gets a big cinematic chapter card. Under the name: a one-line description of what the
   place is (default, `"desc"` per segment, written by Claude and checked for facts), or the name in the local
   script (`local_language` + `place_local`). Render a still example and confirm the format before the film.
9. **Output**: 4K HLG HDR **MP4** for YouTube only (MOV loses HDR on YouTube). Never make an SDR preview unless the user asks (`"sdr_preview": true`).
10. **Thumbnails** come after the film. First propose several text and graphic options (≤ 3 big words + a
    short line, never the video's length; a badge such as a flag emoji + route), let the user pick, then render
    at least 10 thumbnails.

The title style is chosen later, from samples rendered on the user's own footage (step 5).

## 2. Pipeline

```
setup.sh                              # once per machine
export TRAVEL_FILM_WORK=<project folder>   # contains project.json (copy templates/project.json)
S=<skill>/scripts; PY=<skill>/venv/bin/python
```

| Step | Command | What you do with the output |
|---|---|---|
| 1 Index | `$PY $S/index.py` | Read the summary: dates, clip count, how many vertical/SDR clips, GPS gaps. |
| 2 Places *(online, asked)* | `$PY $S/places.py` | `meta/visits.json`: clusters with city/district and nearby attractions. |
| 3 Analyse | `$PY $S/analyze.py` | Frames + sharpness/shake/exposure/audio metrics (VideoToolbox decode). |
| 3b Motion | `$PY $S/shots.py` | Camera pan/zoom speed, in-frame activity (a train passing), PySceneDetect cuts → where cuts are allowed. |
| 4 Understand | `$PY $S/understand.py` | CLIP on GPU (tags, duplicates) + Apple Vision on Neural Engine (aesthetics, animals, people). |
| 4b Vision+ | `$PY $S/apple_vision.py` | Text in the picture (signs, shop names), horizon angle, face roll, fingerprints, which way is up. |
| 4c Speech | `$PY $S/speech.py` | MLX-Whisper word timestamps (only clips that contain speech). |
| 4d Look | `$PY $S/sheets.py intent` | **Read every intent sheet** (6 frames across each clip + text + speech). Write `intents.json` and `locations.json`. |
| 5 Title samples | `$PY $S/title_demos.py <segment>` | Show `previews/title_styles.jpg` and the animated MP4s, then ask which style. |
| 6 Plan | `$PY $S/edit_plan.py` | One best shot per subject, cut on calm camera + outside words → `meta/edl.json`, `EDIT_LIST.md`. (`select_shots.py` = automatic fallback without intents.) |
| 7 Landmarks *(optional)* | `$PY $S/landmarks.py track / check / render` | See `references/landmarks.md`. Check every drift sheet. |
| 8 Polish | `$PY $S/animals.py …`, `$PY $S/horizon.py …` | Animal labels once per species; level confirmed tilted shots. |
| 9 Render | `JOBS=2 $PY $S/render_all.py` | Shots → join → loudness −14 LUFS → final HDR MP4 → `verify.py` (SDR preview only if asked). |
| 11 YouTube text | `$PY $S/youtube_meta.py` | Exact chapters from the edit → `renders/YOUTUBE.md`. Write 3 title options, a short description, 3 hashtags and tags (≤ 500 chars); show them to the user. |
| 10 Thumbnails | `$PY $S/thumbnails.py pick` → propose text options → `make N N N …` | ≥ 10 thumbnails from the chosen frames and text. Then `$PY $S/thumb_score.py` ranks them against the measured click factors (focal point, face, phone-readable text, contrast, colour) → `thumb_scores.md`; remake weak ones (see `references/thumbnails.md`), show `all_thumbnails.jpg` with the top picks and let the user choose. |

Re-running a step is cheap: analysis results are cached. `render_all.py` rebuilds the edit list itself when
`intents.json` / `locations.json` are newer than it, and re-renders exactly the shots whose inputs changed (each
shot stores a fingerprint of clip window, title text, fades, rotation, labels, style). Never delete shots by hand.
**Before telling the user a change is in the film, grab a frame of the re-rendered shot and look at it.**

### Writing `intents.json` (what every clip is FOR)
Read `review/intent_*.jpg`. For every clip write one entry (more if a clip holds two different moments):
`{"file", "seg", "subject", "q", "win", "note"}`.
- **subject** is the intent in a few words (`enoden_tram_crossing`, `rainbow_in_mist`). Clips that show the same
  thing with the same intent share a subject, and only the best one is used. Example: five takes of the same
  shrine with the tower behind it become one shot.
- **win** is the moment: the seconds where the point of the clip happens. A railway crossing is worthless
  without the train, so the window must contain the train passing (`meta/shots` events help find it).
- **q**: 3 highlight, 2 good, 1 filler (not used), 0 drop (pocket shots, screens, blur, hotel rooms).
- Use the text Vision read (shop signs, station names) and the speech to name things correctly, e.g. a
  Starbucks Reserve Roastery, not just "a canal".
- For a clip tagged vertical that was filmed horizontally (`apple_vision.json` `upright` prefers 90/-90, or
  the frames look sideways), add it to `ignore_rotation_tag` in `project.json`.

### Aerial / plane opening
Start with an establishing shot of the whole area (widest steady hold) carrying the city card, then the
landmarks. Use only steady holds: list `"plane": [[clip, start, end, note], …]` windows on the segment, taken
from `meta/shots/<clip>.json`, never the zoom-in/out parts.

### Writing `locations.json` (the creative core)
Template: `templates/locations.example.json`. Combine `meta/visits.json` (GPS, city, district, nearby named
places) with what you see on the sheets:
- **The name must match what is on screen.** GPS gives the street; the footage shows the temple gate, the
  beach or the market. Prefer the attraction the shots actually show. If GPS and content disagree (e.g.
  footage from inside a train, or a clip without GPS), trust the content.
- **One segment per place visit**, in time order. Short transit clips go into the neighbouring segment with
  `"title": false`.
- Give every titled segment a `desc`: one short line (≈ 40–65 characters) saying what the place IS, e.g.
  "Temple founded in 778, its wooden stage built without nails". Facts only, no superlatives you can't back up.
- `title_shot: "IMG_….MOV"` puts the segment's title on the shot where the place is actually recognisable
  (the first torii, the river) instead of on an approach/transit shot.
- Set `new_city: true` on the first segment in each new city. Add `country`, `city_local`/`place_local` when
  local script is wanted, and `lat`/`lon` for the map-pin style.
- `weight` sets the share of runtime. Give big moments more, and repetitive walks (forest, endless gates)
  less, with `"dedupe": 0.86`.
- `exclude`: receipts, screenshots, pocket shots, near-black clips (Vision `util` flags and the sheets
  reveal these). `must_keep`: what the user asked for. `dual_selfie`: front+back camera clips (picture in
  picture of a face in a corner). `animals_interesting`: animals doing something, not just present.

## 3. Quality bar (verify each before rendering)
See `references/quality.md` for the full checklist. In short:
- Titles appear once per location, only when the location changes. City changes fade to black (sound out),
  then fade in on the new city's chapter card.
- Every landmark pin sits on its landmark across its whole on-screen window (drift sheets). The label never
  covers the landmark or another label, and lines don't cross.
- Animal labels: correct species name, short (~2.5 s), appearing at the animal's first appearance in the film,
  with the dot on the animal.
  Also search for small creatures detectors miss (insects on gates, lizards, water striders):
  `animals.py search "a cicada on a red gate" "an insect on the water"`. Expect the user to know about some.
- No near-duplicate shots in a row; no blurry or shaky starts; dark and utility clips are gone.
- Horizons: fix only real roll on eye-level shots. Low-angle shots of tall subjects converge naturally.
- `verify.py` prints READY: HEVC 10-bit, BT.2020, HLG in both bitstream and container, about −14 LUFS.

## References
- `references/landmarks.md`: identifying landmarks from the air, anchors, tracking, callout design rules
- `references/quality.md`: review checklist and the design and accessibility rules for all graphics
- `references/hdr_youtube.md`: why HLG, how the HDR signalling is preserved, and how it uploads
- Everything for upload ends up together in `renders/`: the HDR film, `thumbnails/`, `YOUTUBE.md`.
- Final deliverables: the HDR film, the SDR preview, the chosen thumbnail, and `renders/YOUTUBE.md` (titles, description
  with chapters, hashtags, tags). Re-run `youtube_meta.py` after any change to the edit so chapter times stay exact.
- `references/thumbnails.md`: thumbnail styles and the rules behind them
- `references/performance.md`: encoder facts and memory pitfalls on Apple Silicon
- `references/editing.md`: how shots are chosen, cut and ordered
