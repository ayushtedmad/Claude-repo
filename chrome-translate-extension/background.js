// background.js

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function captureScreenshot(windowId, retries = 4) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await new Promise((resolve, reject) => {
        chrome.tabs.captureVisibleTab(windowId, { format: "png" }, (dataUrl) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(dataUrl);
          }
        });
      });
    } catch (err) {
      if (/MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND/i.test(err.message) && attempt < retries) {
        await sleep(500);
        continue;
      }
      throw err;
    }
  }
}

async function translateBatch(texts, targetLang) {
  const { apiKey } = await chrome.storage.sync.get("apiKey");
  if (!apiKey) {
    throw new Error("No Google Translate API key set. Open the extension options page to add one.");
  }
  const url = `https://translation.googleapis.com/language/translate/v2?key=${apiKey}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ q: texts, target: targetLang, format: "text" })
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Translation API error (${res.status}): ${errText}`);
  }
  const data = await res.json();
  return data.data.translations.map((t) => t.translatedText);
}

// ── Bounding-box helper ───────────────────────────────────────────────────────
// Use nullish coalescing instead of || so that x=0 or y=0 (left/top edge of
// the image) are not incorrectly treated as missing values.
function vertBounds(vertices) {
  const xs = vertices.map((v) => (v.x != null ? v.x : 0));
  const ys = vertices.map((v) => (v.y != null ? v.y : 0));
  const x  = Math.min(...xs);
  const y  = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

// ── Google Cloud Vision OCR ───────────────────────────────────────────────────
// Strategy:
//   1. Request DOCUMENT_TEXT_DETECTION which returns fullTextAnnotation (paragraphs)
//      AND textAnnotations (word-level, same as TEXT_DETECTION).
//   2. Parse fullTextAnnotation paragraphs first — best for overlay boxes.
//   3. If that yields nothing, fall back to grouping textAnnotations words into
//      lines by Y-proximity — works for simpler images where paragraph detection
//      is skipped.
// Returns blocks in IMAGE PIXEL coordinates; callers convert to CSS/doc coords.
async function ocrScreenshot(dataUrl) {
  const { apiKey } = await chrome.storage.sync.get("apiKey");
  if (!apiKey) {
    throw new Error("No Google API key set. Open the extension options page to add one.");
  }

  const base64 = dataUrl.replace(/^data:[^;]+;base64,/, "");
  const url = `https://vision.googleapis.com/v1/images:annotate?key=${apiKey}`;

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      requests: [{
        image: { content: base64 },
        // DOCUMENT_TEXT_DETECTION gives both fullTextAnnotation (paragraphs)
        // AND textAnnotations (words) in one call.
        features: [{ type: "DOCUMENT_TEXT_DETECTION" }],
      }],
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    // Try to surface a human-readable message from the error JSON.
    let humanMsg = errText;
    try {
      const parsed = JSON.parse(errText);
      humanMsg = (parsed.error && parsed.error.message) ? parsed.error.message : errText;
    } catch (_) {}
    throw new Error(`Vision API error (${res.status}): ${humanMsg}`);
  }

  const data = await res.json();
  const resp = data.responses && data.responses[0];

  // A per-image error (e.g. billing not enabled, API not enabled) lands here.
  if (resp && resp.error) {
    throw new Error(`Vision API: ${resp.error.message}`);
  }
  if (!resp) throw new Error("Vision API returned an empty response.");

  const blocks = [];
  let id = 0;

  // ── Pass 1: paragraph-level blocks from fullTextAnnotation ─────────────────
  if (resp.fullTextAnnotation) {
    for (const page of resp.fullTextAnnotation.pages || []) {
      for (const block of page.blocks || []) {
        for (const para of block.paragraphs || []) {
          // Rebuild text from symbols. detectedBreak is AFTER the symbol.
          let text = "";
          for (const word of para.words || []) {
            for (const sym of word.symbols || []) {
              text += sym.text || "";
              const br = sym.property && sym.property.detectedBreak;
              if (br) {
                if (br.type === "SPACE" || br.type === "SURE_SPACE") text += " ";
                if (br.type === "LINE_BREAK" || br.type === "EOL_SURE_SPACE") text += " ";
              }
            }
            text += " "; // word separator
          }
          text = text.replace(/\s+/g, " ").trim();
          if (!text) continue;

          const verts = (para.boundingBox && para.boundingBox.vertices) || [];
          if (verts.length < 4) continue;

          const { x, y, w, h } = vertBounds(verts);
          if (w < 4 || h < 4) continue;

          blocks.push({
            id: id++, text,
            x, y, width: w, height: h,
            fontSize:   Math.max(10, Math.round(h * 0.72)),
            color:      "#000000",
            bg:         "transparent",
            fontWeight: "400",
            isOcr:      true,
          });
        }
      }
    }
  }

  // ── Pass 2 (fallback): group textAnnotations words into lines ───────────────
  // Used when fullTextAnnotation returned no paragraphs (common for some image
  // types like screenshots of printed text or low-resolution images).
  if (blocks.length === 0 && resp.textAnnotations && resp.textAnnotations.length > 1) {
    // textAnnotations[0] = entire-page bounding box + all text; skip it.
    // Subsequent entries are individual words in reading order.
    const words = resp.textAnnotations.slice(1).filter((a) => {
      return a.description && a.boundingPoly && (a.boundingPoly.vertices || []).length >= 4;
    });

    // Group words into lines: two words are on the same line if their vertical
    // centres are within half the average word height of each other.
    const lines = [];  // each line = { words: [{text, bounds}], yCenter }

    for (const ann of words) {
      const verts = ann.boundingPoly.vertices;
      const bounds = vertBounds(verts);
      const yCenter = bounds.y + bounds.h / 2;

      let placed = false;
      for (const line of lines) {
        if (Math.abs(line.yCenter - yCenter) <= line.avgH / 2 + 4) {
          line.words.push({ text: ann.description, bounds });
          // Running average of word heights to adapt the merge threshold.
          line.avgH = (line.avgH + bounds.h) / 2;
          line.yCenter = (line.yCenter + yCenter) / 2;
          placed = true;
          break;
        }
      }
      if (!placed) {
        lines.push({ words: [{ text: ann.description, bounds }], yCenter, avgH: bounds.h });
      }
    }

    // Emit one block per line.
    for (const line of lines) {
      // Sort words left-to-right before joining.
      line.words.sort((a, b) => a.bounds.x - b.bounds.x);
      const text = line.words.map((w) => w.text).join(" ").trim();
      if (!text) continue;

      const allBounds = line.words.map((w) => w.bounds);
      const x  = Math.min(...allBounds.map((b) => b.x));
      const y  = Math.min(...allBounds.map((b) => b.y));
      const x2 = Math.max(...allBounds.map((b) => b.x + b.w));
      const y2 = Math.max(...allBounds.map((b) => b.y + b.h));
      const w  = x2 - x;
      const h  = y2 - y;
      if (w < 4 || h < 4) continue;

      blocks.push({
        id: id++, text,
        x, y, width: w, height: h,
        fontSize:   Math.max(10, Math.round(h * 0.72)),
        color:      "#000000",
        bg:         "transparent",
        fontWeight: "400",
        isOcr:      true,
      });
    }
  }

  return blocks;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "CAPTURE_SCREENSHOT") {
    captureScreenshot(sender.tab ? sender.tab.windowId : msg.windowId)
      .then((dataUrl) => sendResponse({ ok: true, dataUrl }))
      .catch((err)   => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.type === "TRANSLATE_BATCH") {
    translateBatch(msg.texts, msg.targetLang)
      .then((translations) => sendResponse({ ok: true, translations }))
      .catch((err)         => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.type === "OCR_SCREENSHOT") {
    ocrScreenshot(msg.dataUrl)
      .then((blocks) => sendResponse({ ok: true, blocks }))
      .catch((err)   => sendResponse({ ok: false, error: err.message }));
    return true;
  }
});
