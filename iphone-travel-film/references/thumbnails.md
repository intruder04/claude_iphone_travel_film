# YouTube thumbnails

`thumbnails.py` renders 1280×720 JPGs under 2 MB (YouTube's limits) in four styles, for the user to choose from:

| File | Style | Best source frame |
|---|---|---|
| `thumb_1_pop.jpg` | **Subject pop**: the subject is lifted out (Apple Vision foreground mask, the same tech as iOS "lift subject"), zoomed in, given a white outline and soft glow over a darkened, blurred background, with huge condensed 2-line text and a yellow highlight bar | a person or animal with clear edges |
| `thumb_2_cinematic.jpg` | **Cinematic**: full-bleed hero landscape, punchy grade, one giant word, yellow sub-line | iconic scenery / landmark |
| `thumb_3_collage.jpg` | **Collage**: 3 slanted panels from different places plus a yellow title block ("whole trip in one video") | 3 contrasting places |
| `thumb_4_minimal.jpg` | **Aesthetic minimal**: soft grade, small lowercase title bottom-left | calm, beautiful wide shot |
| `thumb_5_pop_people.jpg` | Subject pop on the frame with the most prominent person (skipped if no clear subject) | |

Rules these follow (current travel-thumbnail conventions):
- ≤ 3 big words, readable at phone size (~120 px wide). No sentences.
- One clear focal point. Faces and animals get the most clicks; picture-in-picture selfie frames are excluded.
- High contrast and saturated, but natural: no oversaturated HDR look, no fake arrows or circles.
- Keep the bottom-right corner clear: YouTube puts the video duration there.
- A small rounded badge with a flag emoji gives instant "where" context. Flags are drawn with macOS CoreText,
  because Pillow can't render flag ligatures.
- Text from `project.json` (`thumbnail_text`, `thumbnail_badge`). Propose options and let the user choose.

## What the data says (checked against the thumbnails, 2026)
Sources: vidIQ's 2026 study of 500 breakout long-form videos in 30 niches; TubeAnalytics' 2025–26 CTR patterns
(videos with ≥ 10k impressions; method not fully published); Kapwing's face-expression analysis by genre. Most
"+X % CTR" figures in blogs can't be traced to a method, so treat numbers as direction, not promise.
- **A clear face wins.** 69 % of breakout thumbnails show a face, 80 % of the top 50. Only ~1 in 20 uses an
  exaggerated expression: a clear, well-lit, genuine face is what matters. Size: roughly ¼–⅓ of the frame,
  away from the text. Travel has the most happy faces of any genre (~54 %), so prefer a smiling frame when one
  exists (CIDetector `hasSmile` finds them).
- **One focal point.** Four or more distinct elements read as chaos on a phone; collages work for multi-stop
  trips only when sparse (2–3 panels). Wide landscapes with no subject score lowest: zoom in on the subject
  (`focus_crop`, Apple Vision saliency) or add the face.
- **Contrast + colour.** 89 % of breakouts have a clear face, high contrast, or both. Bright, saturated
  backgrounds beat muted or dark ones (+8–14 % reported) — but adapt: boost muted frames, leave a saturated blue
  sky alone (`style_minimal(..., vivid=True)`).
- **Text: ≤ 5 words**, bold sans-serif, readable when the thumbnail is ~120–320 px wide. Text helps more in
  search than in browse, so a text-free variant is a fair A/B partner.
- **A soft background blur behind the face** separates it (a reported mobile case: bigger face + blurred
  background + 3 bold words lifted CTR from 1.7 % to 4 %).
- **Match the video.** YouTube's Test & Compare picks winners by watch-time share, not CTR, so a thumbnail that
  over-promises loses even if it gets clicks.

`thumb_score.py` turns these into a heuristic score per thumbnail (focus 40, contrast 15, colour 15, face 15,
phone-readable text 10, clutter 5). Use it to pick the top 3 for Test & Compare and to find weak designs to
remake. It is not a CTR prediction.

## Collage layouts and options
`collage` (3 slanted panels), `grid4` (2×2), `split` (diagonal halves), `strips` (4 tall strips + title band),
`mosaic` / `mosaic_r` (big hero + 2 stacked, hero left or right), `polaroid` (tilted photo cards over a blurred
hero). `"thumbnail_extra_mosaics": N` adds N more mosaics per text with different frames. Drop any layout the user
dislikes from `thumbnail_styles`. Choose them with
`"thumbnail_styles"` in project.json; every text variant is rendered in every style.
- `pop` keeps the subject sharp and bright over a dimmed, blurred background, with **no outline or glow** (outlines
  around people or animals look cheap). Set `"thumbnail_cutout": false` to skip it entirely.
- Ask what the user does NOT want in thumbnails (e.g. a particular animal or person) and leave those frames out;
  `thumbnails.py add CLIP@SECONDS` adds hand-picked scenery the ranker missed.

## Trend styles (research, 2025–26 creator guides)
- Cleaner compositions with one focal point and negative space are replacing busy, text-heavy thumbnails.
- Travel classic: a close-up, genuine face plus a recognisable location "hero" shot.
- 1–2 huge words, readable on a phone; strong light/dark contrast.
- A text-free version is worth A/B testing with YouTube "Test & Compare" (up to 3 thumbnails).
Styles in `thumbnails.py`: `style_face_hero` (hero full-bleed + face cut-out, no outline), `style_clean` (one image,
one huge word), `style_versus` (two cities/moods side by side), `style_textfree`. Offer a few of each and suggest
testing 3 very different ones (e.g. face_hero, clean, collage) against each other.

## Video titles
Front-load searchable words (country, cities, "4K HDR") in the first ~40 characters (phones truncate). Offer 10+
options in four groups: search-first (the pattern of high-view 4K travel channels: place + format), story/feeling,
a specific hook taken from a real moment in the film, and calm/ambient when there is no narration or music.
No clickbait the film doesn't deliver. Suggest one main title and a contrasting one to A/B test.

## Minimal style text
Small line ~64 px Heavy caps, headline ~170 px; both with a dark outline (5–6 px) and a soft drop shadow so they read
over any background and on light/dark YouTube UI. The small line's colour is picked per image from a small modern
palette (yellow, cyan, white, pink, lime) for brightness + hue contrast with what's under it. Ask which kinds of
shots the user doesn't want on thumbnails (e.g. airplane window views, indoor art installations) and skip them.

## Frame preparation
`enhance(img)` before any style: auto levels from the luminance histogram (1st→99.5th percentile, no highlight
clipping), partial lift for dark frames, light unsharp mask. Horizon: automatic detectors (Vision horizon, line
detection) are fooled by perspective (looking up at gates/towers) and find nothing on most scenes, so level
by eye on a gridded sheet and only rotate frames that are truly tilted (`enhance(..., level=True)` is opt-in).
Match frames to the text: a "summer" title wants nature, sea, sky and greenery, not city or indoor shots.
