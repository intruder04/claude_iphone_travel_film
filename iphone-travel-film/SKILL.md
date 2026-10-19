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
Every heavy step runs on the Mac's media engines, GPU or Neural Engine, shows % progress, and stays well within
16 GB of RAM.

**Hard rules**
- Never modify, move, rename or re-encode the user's source files. All output goes into a new project folder.
- Before any step that sends data off the machine (reverse geocoding sends GPS coordinates to OpenStreetMap),
  ask first.
- Run long steps in a visible terminal tab with their progress bars, so the user can see % done.
- Memory: at most 2 parallel 4K render jobs (`JOBS=2`); 2 already saturate the encoder, and more only add RAM.
  `compose.py` has a per-ffmpeg RSS watchdog (`MEM_LIMIT_GB`, default 5). Never pipe raw 4K frames into an
  ffmpeg that also decodes 4K and holds audio from the same demuxer: that pattern froze a 16 GB Mac.
- Look at the footage. Contact sheets and gridded frames exist so you can verify places, landmarks, animals,
  tilt and tracking by eye. Metadata and detectors only produce candidates.

## 1. Ask before starting

Use AskUserQuestion (several questions per call) and record the answers in `project.json`:

1. **Source folder** with the iPhone videos (read-only), and where to create the project folder. Default: a new
   `<source>_edit` folder next to the source.
2. **Target length**: e.g. 5, 10, 15 or 25–30 minutes.
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
   changes. A city change gets a big cinematic chapter card. Show names in the local script too (e.g. 京都,
   Αθήνα, القاهرة)? Set `local_language` to the country's ISO code, or leave it empty.
9. **Output**: 4K HLG HDR for YouTube (default), plus a 1080p SDR preview.
10. **Thumbnail text**: propose 2–3 options (≤ 3 big words + a short line, e.g. "PORTUGAL" / "IN 15 MINUTES")
    and a badge (flag emoji + route, e.g. "🇵🇹 Lisbon · Sintra · Porto"). Thumbnails are made after the film.

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
| 4 Understand | `$PY $S/understand.py` | CLIP on GPU (tags, duplicates) + Apple Vision on Neural Engine (aesthetics, animals, people). |
| 4b Look | `$PY $S/sheets.py clips` and `compact` | **Read every sheet.** Write `locations.json` (see below). |
| 5 Title samples | `$PY $S/title_demos.py <segment>` | Show `previews/title_styles.jpg` and the animated MP4s, then ask which style. |
| 6 Select | `$PY $S/select_shots.py` | `meta/edl.json`, `EDIT_LIST.md`; tune weights until the target length and balance feel right. |
| 7 Landmarks *(optional)* | `$PY $S/landmarks.py track / check / render` | See `references/landmarks.md`. Check every drift sheet. |
| 8 Polish | `$PY $S/animals.py …`, `$PY $S/horizon.py …` | Animal labels once per species; level confirmed tilted shots. |
| 9 Render | `JOBS=2 $PY $S/render_all.py` | Shots → join → loudness −14 LUFS → final MOV → SDR preview → `verify.py`. |
| 10 Thumbnails | `$PY $S/thumbnails.py pick` then `make N N N N` | Look at `candidates.jpg` and pick: 1st = a person/animal to lift out, 2nd = hero scenery. Show `all_thumbnails.jpg` and let the user choose. |

Re-running a step is cheap: analysis results are cached, and rendered shots in `renders/shots/` are reused.
After changing one shot's overlay or rotation, delete only `renders/shots/NNN.mov` and re-run step 9.

### Writing `locations.json` (the creative core)
Template: `templates/locations.example.json`. Combine `meta/visits.json` (GPS, city, district, nearby named
places) with what you see on the sheets:
- **The name must match what is on screen.** GPS gives the street; the footage shows the temple gate, the
  beach or the market. Prefer the attraction the shots actually show. If GPS and content disagree (e.g.
  footage from inside a train, or a clip without GPS), trust the content.
- **One segment per place visit**, in time order. Short transit clips go into the neighbouring segment with
  `"title": false`.
- Set `new_city: true` on the first segment in each new city. Add `country`, `city_local`/`place_local` when
  local script is wanted, and `lat`/`lon` for the map-pin style.
- `weight` sets the share of runtime. Give big moments more, and repetitive walks (forest, endless gates)
  less, with `"dedupe": 0.86`.
- `exclude`: receipts, screenshots, pocket shots, near-black clips (Vision `util` flags and the sheets
  reveal these). `must_keep`: what the user asked for. `dual_selfie`: front+back camera clips (picture in
  picture of a face in a corner). `animals_interesting`: animals doing something, not just present.

## 3. Quality bar (verify each before rendering)
See `references/quality.md` for the full checklist. In short:
- Titles appear once per location, only when the location changes; city changes use the chapter card.
- Every landmark pin sits on its landmark across its whole on-screen window (drift sheets). The label never
  covers the landmark or another label, and lines don't cross.
- Animal labels: correct species name, short (~2.5 s), first appearance only, and the dot is on the animal.
  Also search for small creatures detectors miss (insects on gates, lizards, water striders):
  `animals.py search "a cicada on a red gate" "an insect on the water"`. Expect the user to know about some.
- No near-duplicate shots in a row; no blurry or shaky starts; dark and utility clips are gone.
- Horizons: fix only real roll on eye-level shots. Low-angle shots of tall subjects converge naturally.
- `verify.py` prints READY: HEVC 10-bit, BT.2020, HLG in both bitstream and container, about −14 LUFS.

## References
- `references/landmarks.md`: identifying landmarks from the air, anchors, tracking, callout design rules
- `references/quality.md`: review checklist and the design and accessibility rules for all graphics
- `references/hdr_youtube.md`: why HLG, how the HDR signalling is preserved, and how it uploads
- `references/thumbnails.md`: thumbnail styles and the rules behind them
- `references/performance.md`: measured speeds on Apple Silicon, memory pitfalls and how they were fixed
