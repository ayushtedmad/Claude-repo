const statusEl         = document.getElementById("status");
const statusTextEl     = document.getElementById("statusText");
const btn              = document.getElementById("go");
const langSelect       = document.getElementById("lang");
const fullPageCheckbox = document.getElementById("fullPage");
const inPageCheckbox   = document.getElementById("inPage");
const ocrCheckbox      = document.getElementById("ocrImages");
const textSizeInput    = document.getElementById("textSize");
const sizeValueEl      = document.getElementById("sizeValue");
const sizeAutoBtn      = document.getElementById("sizeAuto");

document.getElementById("openOptions").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

function setStatus(msg, { error = false, busy = false } = {}) {
  statusTextEl.textContent = msg;
  statusEl.classList.toggle("error", error);
  statusEl.classList.toggle("busy", busy);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function sendTabMessage(tabId, msg, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error('Timed out waiting for "' + msg.type + '" response.')),
      timeoutMs
    );
    chrome.tabs.sendMessage(tabId, msg, (response) => {
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (response && response.ok === false && response.error) {
        reject(new Error(response.error));
      } else {
        resolve(response);
      }
    });
  });
}

async function ensureContentScript(tabId, url) {
  if (/^(chrome|edge|about|chrome-extension):/.test(url || "")) {
    throw new Error("This page can't be captured (browser/extension pages are not accessible).");
  }
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  } catch (err) {
    throw new Error("Couldn't access this page: " + err.message);
  }
}

// ── OCR helpers ──────────────────────────────────────────────────────────────

function convertOcrCoords(rawBlocks, dpr, scrollX, scrollY) {
  return rawBlocks.map((b, i) => ({
    ...b,
    id:       "ocr_" + Date.now() + "_" + i,
    x:        b.x      / dpr + scrollX,
    y:        b.y      / dpr + scrollY,
    width:    b.width  / dpr,
    height:   b.height / dpr,
    fontSize: Math.max(10, (b.height / dpr) * 0.72),
  }));
}

function filterOcrBlocks(ocrBlocks, domBlocks) {
  if (!domBlocks.length) return ocrBlocks;
  return ocrBlocks.filter((ocr) => {
    const cx = ocr.x + ocr.width  / 2;
    const cy = ocr.y + ocr.height / 2;
    return !domBlocks.some(
      (dom) => cx >= dom.x && cx <= dom.x + dom.width &&
               cy >= dom.y && cy <= dom.y + dom.height
    );
  });
}

async function captureAndOcr(windowId, dpr, scrollX, scrollY) {
  const shot = await chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT", windowId });
  if (!shot.ok) throw new Error(shot.error);
  const res = await chrome.runtime.sendMessage({ type: "OCR_SCREENSHOT", dataUrl: shot.dataUrl });
  if (!res.ok) throw new Error(res.error);
  return convertOcrCoords(res.blocks, dpr, scrollX, scrollY);
}

async function ocrExistingShot(dataUrl, dpr, scrollX, scrollY) {
  const res = await chrome.runtime.sendMessage({ type: "OCR_SCREENSHOT", dataUrl });
  if (!res.ok) throw new Error(res.error);
  return convertOcrCoords(res.blocks, dpr, scrollX, scrollY);
}

// ── In-page extraction (no screenshots) ──────────────────────────────────────

async function extractSingleViewBlocks(tabId) {
  const e = await sendTabMessage(tabId, { type: "EXTRACT_TEXT_BLOCKS", onlyNew: false });
  if (!e || !e.blocks) throw new Error("Could not read page content. Try reloading the tab.");
  return {
    blocks:           e.blocks,
    pageWidth:        e.viewportWidth,
    pageHeight:       e.viewportHeight,
    pageUrl:          e.pageUrl,
    pageTitle:        e.pageTitle,
    scrollX:          e.scrollX,
    scrollY:          e.scrollY,
    devicePixelRatio: e.devicePixelRatio,
  };
}

async function extractFullPageBlocks(tabId, windowId, withOcr) {
  const dims = await sendTabMessage(tabId, { type: "GET_PAGE_DIMENSIONS" });
  const { scrollHeight, viewportWidth, viewportHeight, devicePixelRatio } = dims;

  await sendTabMessage(tabId, { type: "RESET_EXTRACTION" });
  await sendTabMessage(tabId, { type: "SCROLL_TO", y: 0 });
  await sleep(200);

  const allBlocks = [];
  let pageUrl = "", pageTitle = "";
  let y = 0, lastActualY = -1, step = 1;
  const estimatedSteps = Math.max(1, Math.ceil(scrollHeight / viewportHeight));

  while (true) {
    const scrollResult = await sendTabMessage(tabId, { type: "SCROLL_TO", y });
    const actualY = scrollResult.scrollY;
    if (actualY === lastActualY && allBlocks.length > 0) break;

    setStatus("Reading section " + step + " of ~" + estimatedSteps + "...", { busy: true });
    await sleep(withOcr ? 300 : 150);

    const extraction = await sendTabMessage(tabId, { type: "EXTRACT_TEXT_BLOCKS", onlyNew: true });
    if (!pageUrl) { pageUrl = extraction.pageUrl || ""; pageTitle = extraction.pageTitle || ""; }

    const domSlice = extraction.blocks;

    if (withOcr && windowId) {
      try {
        const ocrSlice = await captureAndOcr(windowId, devicePixelRatio, 0, actualY);
        const newOcr   = filterOcrBlocks(ocrSlice, [...allBlocks, ...domSlice]);
        allBlocks.push(...domSlice, ...newOcr);
      } catch (_) {
        allBlocks.push(...domSlice);
      }
    } else {
      allBlocks.push(...domSlice);
    }

    if (actualY + viewportHeight >= scrollHeight) break;
    lastActualY = actualY;
    y += viewportHeight;
    step++;
  }

  await sendTabMessage(tabId, { type: "SCROLL_TO", y: 0 });

  return {
    blocks:           allBlocks,
    pageWidth:        viewportWidth,
    pageHeight:       scrollHeight,
    pageUrl,
    pageTitle,
    devicePixelRatio,
    scrollX:          0,
    scrollY:          0,
  };
}

// ── Viewer mode (screenshot-based) ───────────────────────────────────────────

async function captureSingleView(tabId, windowId, withOcr) {
  const extraction = await sendTabMessage(tabId, { type: "EXTRACT_TEXT_BLOCKS", onlyNew: false });
  if (!extraction || !extraction.blocks) throw new Error("Could not read page content. Try reloading the tab.");

  setStatus("Capturing screenshot...", { busy: true });
  const shot = await chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT", windowId });
  if (!shot.ok) throw new Error(shot.error);

  let blocks = extraction.blocks.map((b) => ({
    ...b,
    x: b.x - extraction.scrollX,
    y: b.y - extraction.scrollY,
  }));

  if (withOcr) {
    try {
      setStatus("Scanning image text...", { busy: true });
      const ocrBlocks = await ocrExistingShot(shot.dataUrl, extraction.devicePixelRatio, 0, 0);
      blocks = [...blocks, ...filterOcrBlocks(ocrBlocks, blocks)];
    } catch (_) {}
  }

  return {
    screenshot: shot.dataUrl,
    pageWidth:  extraction.viewportWidth,
    pageHeight: extraction.viewportHeight,
    pageUrl:    extraction.pageUrl,
    pageTitle:  extraction.pageTitle,
    blocks,
  };
}

async function captureFullPage(tabId, windowId, withOcr) {
  const dims = await sendTabMessage(tabId, { type: "GET_PAGE_DIMENSIONS" });
  const { scrollHeight, viewportWidth, viewportHeight, devicePixelRatio } = dims;

  await sendTabMessage(tabId, { type: "RESET_EXTRACTION" });
  await sendTabMessage(tabId, { type: "SCROLL_TO", y: 0 });
  await sleep(200);

  const slices = [], allBlocks = [];
  let pageUrl = "", pageTitle = "";
  let y = 0, lastActualY = -1, step = 1;
  const estimatedSteps = Math.max(1, Math.ceil(scrollHeight / viewportHeight));

  while (true) {
    const scrollResult = await sendTabMessage(tabId, { type: "SCROLL_TO", y });
    const actualY = scrollResult.scrollY;
    if (actualY === lastActualY && slices.length > 0) break;

    setStatus("Capturing section " + step + " of ~" + estimatedSteps + "...", { busy: true });
    await sleep(300);

    const shot = await chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT", windowId });
    if (!shot.ok) throw new Error(shot.error);

    const extraction = await sendTabMessage(tabId, { type: "EXTRACT_TEXT_BLOCKS", onlyNew: true });
    if (!pageUrl) { pageUrl = extraction.pageUrl || ""; pageTitle = extraction.pageTitle || ""; }

    const domSlice = extraction.blocks;

    if (withOcr) {
      try {
        const ocrSlice = await ocrExistingShot(shot.dataUrl, devicePixelRatio, 0, actualY);
        const newOcr   = filterOcrBlocks(ocrSlice, [...allBlocks, ...domSlice]);
        allBlocks.push(...domSlice, ...newOcr);
      } catch (_) {
        allBlocks.push(...domSlice);
      }
    } else {
      allBlocks.push(...domSlice);
    }

    slices.push({ dataUrl: shot.dataUrl, scrollY: actualY });

    if (actualY + viewportHeight >= scrollHeight) break;
    lastActualY = actualY;
    y += viewportHeight;
    step++;
  }

  setStatus("Stitching screenshot...", { busy: true });
  const stitched = await stitchSlices(slices, viewportWidth, scrollHeight, devicePixelRatio);

  await sendTabMessage(tabId, { type: "SCROLL_TO", y: 0 });
  const pageInfo = await sendTabMessage(tabId, { type: "GET_PAGE_DIMENSIONS" });

  return {
    screenshot: stitched,
    pageWidth:  viewportWidth,
    pageHeight: scrollHeight,
    pageUrl,
    pageTitle,
    blocks:     allBlocks,
    _dims:      pageInfo,
  };
}

function stitchSlices(slices, viewportWidth, scrollHeight, dpr) {
  return new Promise((resolve, reject) => {
    if (slices.length === 0) { reject(new Error("No screenshot sections were captured.")); return; }
    const canvas  = document.createElement("canvas");
    canvas.width  = Math.round(viewportWidth * dpr);
    canvas.height = Math.round(scrollHeight  * dpr);
    const ctx     = canvas.getContext("2d");

    const imagePromises = slices.map((slice) =>
      new Promise((res, rej) => {
        const img   = new Image();
        img.onload  = () => res({ img, scrollY: slice.scrollY });
        img.onerror = () => rej(new Error("Failed to load a screenshot section."));
        img.src = slice.dataUrl;
      })
    );

    Promise.all(imagePromises)
      .then((loaded) => {
        loaded.sort((a, b) => a.scrollY - b.scrollY);
        for (const { img, scrollY } of loaded) ctx.drawImage(img, 0, Math.round(scrollY * dpr));
        resolve(canvas.toDataURL("image/png"));
      })
      .catch(reject);
  });
}

// ── Font size control ─────────────────────────────────────────────────────────

let isAutoSize = true;

function getFontSizeOverride() {
  return isAutoSize ? 0 : parseInt(textSizeInput.value, 10);
}

function updateSizeDisplay() {
  const val = parseInt(textSizeInput.value, 10);
  const pct = ((val - 8) / (22 - 8)) * 100;
  textSizeInput.style.setProperty("--pct", pct + "%");

  if (isAutoSize) {
    sizeValueEl.textContent     = "Auto";
    sizeValueEl.style.opacity   = "0.5";
    textSizeInput.style.opacity = "0.45";
    sizeAutoBtn.classList.add("active");
  } else {
    sizeValueEl.textContent     = val + "px";
    sizeValueEl.style.opacity   = "1";
    textSizeInput.style.opacity = "1";
    sizeAutoBtn.classList.remove("active");
  }
}

textSizeInput.addEventListener("input", () => { isAutoSize = false; updateSizeDisplay(); });
sizeAutoBtn.addEventListener("click",   () => { isAutoSize = true;  updateSizeDisplay(); });
updateSizeDisplay();

// ── Button label ──────────────────────────────────────────────────────────────

function updateButtonLabel() {
  btn.textContent = inPageCheckbox.checked
    ? "Translate in Page"
    : "Capture & Translate";
}

inPageCheckbox.addEventListener("change", updateButtonLabel);
updateButtonLabel();

// ── Main flow ─────────────────────────────────────────────────────────────────

btn.addEventListener("click", async () => {
  btn.disabled = true;
  try {
    const [tab]      = await chrome.tabs.query({ active: true, currentWindow: true });
    const targetLang = langSelect.value;
    const fullPage   = fullPageCheckbox.checked;
    const inPage     = inPageCheckbox.checked;
    const withOcr    = ocrCheckbox.checked;

    setStatus("Preparing page...", { busy: true });
    await ensureContentScript(tab.id, tab.url);

    setStatus("Reading page...", { busy: true });

    let result;
    if (inPage) {
      if (fullPage) {
        result = await extractFullPageBlocks(tab.id, withOcr ? tab.windowId : null, withOcr);
      } else {
        result = await extractSingleViewBlocks(tab.id);

        if (withOcr) {
          setStatus("Scanning image text...", { busy: true });
          let ocrError = null;
          try {
            const ocrBlocks = await captureAndOcr(
              tab.windowId,
              result.devicePixelRatio || window.devicePixelRatio || 1,
              result.scrollX || 0,
              result.scrollY || 0
            );
            const newOcr = filterOcrBlocks(ocrBlocks, result.blocks);
            result.blocks = [...result.blocks, ...newOcr];
          } catch (err) {
            ocrError = err;
          }

          if (ocrError) {
            if (result.blocks.length === 0) throw ocrError;
            setStatus("Image scan failed: " + ocrError.message, { error: true });
            await sleep(2500);
          }
        }
      }
    } else {
      result = fullPage
        ? await captureFullPage(tab.id, tab.windowId, withOcr)
        : await captureSingleView(tab.id, tab.windowId, withOcr);
    }

    if (!result.pageTitle) result.pageTitle = tab.title || "";

    if (result.blocks.length === 0) {
      throw new Error(
        withOcr
          ? "No text found even after image scanning. The page may have no readable text."
          : "No text found on this page. Try enabling the Scan image text (OCR) toggle."
      );
    }

    const ocrCount = result.blocks.filter((b) => b.isOcr).length;
    setStatus(
      "Translating " + result.blocks.length + " blocks" + (ocrCount ? " (" + ocrCount + " from images)" : "") + "...",
      { busy: true }
    );

    const texts = result.blocks.map((b) => b.text);
    const translations = [];
    for (let i = 0; i < texts.length; i += 100) {
      const chunk = texts.slice(i, i + 100);
      const res = await chrome.runtime.sendMessage({ type: "TRANSLATE_BATCH", texts: chunk, targetLang });
      if (!res.ok) throw new Error(res.error);
      translations.push(...res.translations);
    }

    const translatedBlocks = result.blocks.map((b, i) => ({ ...b, translated: translations[i] }));

    if (inPage) {
      const resp = await sendTabMessage(tab.id, {
        type:             "APPLY_TRANSLATION",
        blocks:           translatedBlocks,
        fontSizeOverride: getFontSizeOverride(),
      });
      if (!resp || !resp.ok) throw new Error("Failed to apply translation overlay.");
      setStatus("Done! " + translatedBlocks.length + " blocks translated.", { busy: false });
      setTimeout(() => window.close(), 1200);
    } else {
      const payload = {
        screenshot:       result.screenshot,
        pageWidth:        result.pageWidth,
        pageHeight:       result.pageHeight,
        pageUrl:          result.pageUrl,
        pageTitle:        result.pageTitle,
        fontSizeOverride: getFontSizeOverride(),
        blocks:           translatedBlocks,
      };
      await chrome.storage.local.set({ lastCapture: payload });
      setStatus("Opening viewer...", { busy: true });
      chrome.tabs.create({ url: chrome.runtime.getURL("viewer.html") });
      window.close();
    }
  } catch (err) {
    setStatus(err.message, { error: true });
    btn.disabled = false;
  }
});
