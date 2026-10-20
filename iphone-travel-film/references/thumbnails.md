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
