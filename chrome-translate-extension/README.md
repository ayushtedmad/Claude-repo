# Screenshot & Translate — Chrome Extension

Captures a screenshot of the current page and shows it side-by-side:
**left = original**, **right = same screenshot with translated text
overlaid** in boxes positioned where the original text was.

## Load it in Chrome

1. Go to `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked** and select this folder
4. Click the extension icon → the puzzle-piece icon may hide it, so pin it

## Set up translation

This uses the Google Cloud Translation API (has a free monthly quota).

1. Go to console.cloud.google.com → create/select a project
2. Enable **Cloud Translation API**
3. Create an API key under **APIs & Services → Credentials**
4. Right-click the extension icon → **Options**, paste the key, Save

## Use it

1. Open any webpage
2. Click the extension icon, pick a target language
3. Check **Capture full scrollable page** if you want the whole page
   (not just what's currently visible) — this takes longer since it
   scrolls and screenshots in sections
4. Click **Capture & Translate**
5. A new tab opens with the side-by-side comparison

## How it works

- `content.js` walks the visible DOM and records each text block's
  content plus its exact `x/y/width/height` on screen
- `background.js` takes the actual screenshot (`captureVisibleTab`) and
  calls the Translation API
- `viewer.js` draws the translated strings as absolutely-positioned
  boxes on top of a copy of the screenshot, scaled to match

## How full-page capture works

Chrome's `captureVisibleTab` API only ever captures the visible
viewport, so full-page mode:
1. Scrolls the page down by one viewport height at a time
2. Screenshots + extracts new text at each stop (already-seen elements
   are skipped so text isn't duplicated across overlapping sections)
3. Stitches all the screenshot sections into one tall canvas image
4. Remaps every text block's coordinates to that stitched image's
   coordinate space

This is slower than a single capture (a few hundred ms per section,
plus a backoff if Chrome's screenshot rate limit is hit) and restores
your original scroll position when done.

## Known limitations (worth knowing before you extend this)

- Full-page capture assumes **vertical scrolling only** — pages with
  significant horizontal overflow won't be captured correctly.
- Pages with infinite scroll or scroll-triggered lazy loading may keep
  growing `scrollHeight` as you go, or show different content on a
  second pass; capture will still stop once it stops finding new
  document height to descend.
- Sticky/fixed-position headers or footers will get re-captured in
  every section (since they're visible at every scroll position) and
  will appear to repeat down the stitched image.
- Overlay boxes use the *live page's* font metrics, so translated text
  that's much longer than the original may overflow its box — you may
  want to add auto-shrinking font size or wrapping logic.
- The Google Translate API key is stored in `chrome.storage.sync` —
  fine for personal/dev use, but for a public extension you'd want to
  proxy translation calls through your own backend instead of shipping
  a key-entry UI.
- No OCR is involved — this reads text from the DOM, which is more
  accurate and cheaper than OCR, but it won't translate text that's
  baked into images.
