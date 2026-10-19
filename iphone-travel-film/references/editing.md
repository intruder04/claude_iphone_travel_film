# How shots are chosen, cut and ordered

## Understanding a clip
For every clip, Claude looks at six frames across its length (`sheets.py intent`), plus:
- text Apple Vision read in the picture (shop names, station signs, temple boards)
- speech (MLX-Whisper, word timestamps)
- camera motion and in-frame activity (`shots.py`)
- scene changes (PySceneDetect)

From these it writes the clip's **intent**: what it was filmed for, and the seconds where that happens.

## One shot per intent
Clips with the same subject compete. The winner has the highest grade, then the best measured quality inside
its window: sharpness, little shake, good exposure, and a high Apple aesthetics score. Repeats are where most
travel edits drag: five takes of the same view become one.

## Where to cut
- **Camera calm**: in and out points move (within ±1.5 s) to moments where the camera is still or slow. A
  cut during a fast pan or zoom feels jarring.
- **Words**: a cut never splits a spoken word. The in-point goes before the word and the out-point goes about
  0.25 s after it.
- **Events**: when a clip's point is an event (a train passing, a wave breaking), the window must contain it.
  `meta/shots` `events` (in-frame motion while the camera is calm) help find it.
- **Length follows content**: highlights up to ~12 s, selfies with talking up to ~18 s, good shots ~7 s. A
  shot is only trimmed when its moment is longer than that; the target film length is never forced.
- Sub-2-second flashes are dropped.

## Order and rhythm
- Chronological: a trip is a story, and the viewer follows the days.
- Each city opens with its widest, most establishing shot, under the chapter card.
- City changes fade to black with the sound fading out. The new city fades in from black, with the sound
  fading in, under its card.
- Inside a place, chronological order alternates naturally between wide and close and still and moving. If
  three similar static shots end up in a row, drop or move the weakest one.

## Aerial openings
Use only steady holds: establishing wide shot first, then the landmarks, each with tracked 📍 callouts. Never
use the zoom-in or zoom-out parts.
