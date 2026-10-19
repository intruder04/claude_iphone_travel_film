# Quality checklist

## Content and edit
- [ ] Every segment name matches what is on screen (check the sheets, not only GPS).
- [ ] The opening is strong. Arrival or aerial clips go first when the user asked for them.
- [ ] No two near-identical shots back to back. Repetitive places (forest paths, rows of gates, aquariums)
      get `dedupe` ≈ 0.86 and a low weight.
- [ ] No shot starts or ends on the record-button wobble, a blur, or a pocket/floor frame.
- [ ] Dual-camera selfies are kept at a reasonable length, and cut points avoid mid-word speech
      (`select_shots.py` snaps cuts to quiet audio).
- [ ] Animals appear only when they do something; each species is labelled once.
- [ ] Vertical clips: centred sharp image on a blurred, darkened fill of themselves (no black bars).
- [ ] Total length is within ±5 % of the target. Adjust weights rather than cutting good moments.

## Titles
- [ ] Shown only when the location changes; never on every clip.
- [ ] City change → cinematic chapter card (style B by default, configurable).
- [ ] Places get the user's chosen style; a title is shown only if the segment's first shot is ≥ 3.5 s long.
- [ ] Local-script line only when `local_language` is set and the name has been verified.

## Graphics design and accessibility
- Text is always on a dark scrim or pill, ≥ 7:1 contrast (WCAG AAA) on any footage.
- Text colour is 75 % HLG (reference white, ~203 nits): comfortable in HDR and normal white in SDR. Never
  use 100 % white text in HDR, because it glares.
- Minimum text height ~3 % of the frame for labels, ~7 % for titles. 5 % title-safe margins.
- Colour never carries meaning on its own; the accent colour is decorative only.
- Motion: ease-out entrances of 0.4–0.8 s, no flashing, labels glide instead of jumping.
- System fonts only (San Francisco + the macOS font for the local script), so no font licences to ship.

## Technical
- [ ] `horizon.py measure` → `sheet` → look → `fix` only confirmed shots (eye-level, real roll, ≤ 6°).
- [ ] `landmarks.py check` and `animals.py check` sheets reviewed.
- [ ] `verify.py` prints READY.
- [ ] Spot-check the SDR preview at each title, each callout clip and each animal label.
