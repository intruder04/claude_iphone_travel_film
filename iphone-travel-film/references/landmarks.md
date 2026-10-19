# Landmark callouts (📍 pins that follow buildings)

This is for aerial shots (airplane window, observation deck, drone-like hilltop views) where the user wants the
famous buildings named, with each label sticking to its building as the camera moves.

## 1. Identify landmarks by looking
1. `sheets.py grid CLIP T CLIP T …` for frames every ~3–5 s of each aerial clip. Read them at full size, and
   crop and zoom (PIL) into dense areas when something is ambiguous.
2. Use the clip's GPS, altitude and direction of travel (the city slides past the window) to work out which
   part of the city is in view, then match distinctive silhouettes: twin towers, spires, stadium rings,
   bridges, parks, palaces, rivers.
3. **Label only what you are sure of.** A wrong label is worse than no label. If two candidates look alike,
   leave it out.
4. Use the name people know, on one line ("Docomo Tower", not the official long name). No second line:
   repeating the name or adding a district under it was judged useless.

## 2. Anchors (`landmarks/anchors.json`)
```json
{"IMG_0001.MOV": [
  {"name": "Eiffel Tower", "anchors": [[2.0, 1490, 560], [8.0, 900, 310]], "zone": [90, 500], "lift": 0}
]}
```
- `anchors`: `[clip_time, x, y]` in 1920×1080 space, read off the gridded frames. Put the point **in the
  middle of the building's body**, not at its top or beside it, so the pin marks the building and leaves its
  upper part visible.
- Add an anchor every 2–5 s, more during zooms or turns. Each anchor is exact; tracking fills the gaps.
- `zone`: `[half_width, height_below_point]` keep-out area in 4K px. Labels never cover it.
- `show.json`: `{"IMG_0001.MOV": {"Eiffel Tower": [t_in, t_out]}}`. Show each label only while the landmark
  is clearly visible and the track is verified.

## 3. Track and verify (never skip the check)
```
landmarks.py track [CLIP]           # homography tracking, all cores, % progress
landmarks.py check [CLIP [NAME]]    # landmarks/drift/*.jpg — crops every 1.5 s with the tracked point
```
Open every drift sheet. Where the cross leaves the building, add an anchor at that time, then re-track and
re-check. If the landmark leaves the frame, goes behind the wing or turns to haze, shorten its `show` window.
Black cells mean the point left the frame.

## 4. Callout design (what users asked for, keep it)
- Marker: the real **Apple Color Emoji 📍** glyph (iOS/macOS look), with the needle tip exactly on the point.
  It drops in with a small bounce.
- Label: **dark-blue rounded rectangle, white text, centred** horizontally and vertically. San Francisco
  Semibold, about 3 % of frame height at the default `callout_scale` 0.7. Lowering the scale was requested
  after a too-big first version.
- **A thin line** (5 px at 4K) connects the pin's head to the label. The label is attached to the pin.
- Placement solver: candidate slots above, beside, or stacked above the pin. It penalises overlap with other
  labels, lines crossing, lines through labels, covering any pin or landmark zone, and jumping. Labels glide
  between slots and snap only when gliding would overlap. `landmarks.py render` prints any frames where
  overlap was unavoidable; it should be 0.
- Labels fade out near frame edges.

## 5. Render
`landmarks.py render` writes `landmarks/<clip>_callouts.mov` (4K HLG) plus an SDR preview. Put these clips in
a segment with `"keep_whole": true` and `render_all.py` uses them as they are.

## Animal labels (same renderer, `Callouts(marker='dot')`)
Same label style, but with a small navy dot instead of the pin. Show it once per species, at its first
appearance in the edit, for about 2.5 s. Use the common English name ("Grey Heron", "Water Strider"). Look for
small animals yourself: insects on water, lizards and birds in foliage are often missed by Vision. Keyframe
tiny or fast animals (`keys`); larger ones are tracked by local optical flow.
