// content.js
// Walks the DOM and extracts "text blocks" (leaf elements that directly
// contain text) along with their position, in DOCUMENT coordinates
// (rect + current scroll offset) so blocks captured at different scroll
// positions can all be placed correctly on a stitched full-page image.
// Also handles scrolling the page, reporting page dimensions, and
// injecting in-page translation overlays directly onto the live page.

// Injected on-demand (possibly more than once per page), so guard
// against redeclaring everything the second time around.
if (!window.__pageTranslatorInjected) {
  window.__pageTranslatorInjected = true;


let seenElements = new WeakSet();

function resetExtraction() {
  seenElements = new WeakSet();
}

function isVisible(el) {
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
    return false;
  }
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return false;
  // Only keep elements currently within the viewport - we extract once
  // per scroll position, so anything off-screen right now will be
  // picked up on a later (or earlier) scroll step.
  if (rect.bottom < 0 || rect.top > window.innerHeight) return false;
  if (rect.right < 0 || rect.left > window.innerWidth) return false;
  return true;
}

function hasDirectText(el) {
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {
      return true;
    }
  }
  return false;
}

function extractTextBlocks(onlyNew) {
  const blocks = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
    acceptNode(el) {
      const tag = el.tagName;
      if (["SCRIPT", "STYLE", "NOSCRIPT", "SVG", "IFRAME"].includes(tag)) {
        return NodeFilter.FILTER_REJECT;
      }
      // Skip our own injected overlay elements.
      if (el.id === "__pt_root__" || el.id === "__pt_toolbar__") {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    }
  });

  let node;
  let id = 0;
  while ((node = walker.nextNode())) {
    if (!hasDirectText(node)) continue;
    if (!isVisible(node)) continue;
    if (onlyNew) {
      if (seenElements.has(node)) continue;
      seenElements.add(node);
    }

    const text = node.textContent.trim().replace(/\s+/g, " ");
    if (!text) continue;

    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);

    blocks.push({
      id: id++,
      text,
      // Document-relative coordinates (stable across scroll position).
      x: rect.left + window.scrollX,
      y: rect.top + window.scrollY,
      width: rect.width,
      height: rect.height,
      fontSize: parseFloat(style.fontSize) || 14,
      color: style.color,
      bg: style.backgroundColor,
      fontWeight: style.fontWeight
    });
  }
  return blocks;
}

function getPageDimensions() {
  return {
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    devicePixelRatio: window.devicePixelRatio
  };
}

function scrollToY(y) {
  window.scrollTo(0, y);
  return { scrollX: window.scrollX, scrollY: window.scrollY };
}

// ── In-page translation overlay ──────────────────────────────────────────

function removeTranslationOverlay() {
  const root    = document.getElementById("__pt_root__");
  const toolbar = document.getElementById("__pt_toolbar__");
  if (root)    root.remove();
  if (toolbar) toolbar.remove();
}

function applyTranslationOverlay(blocks, fontSizeOverride) {
  removeTranslationOverlay();

  // Zero-sized container at the document origin. overflow:visible lets
  // children paint over the page without creating scrollbars or layout shifts.
  const root = document.createElement("div");
  root.id = "__pt_root__";
  Object.assign(root.style, {
    position:      "absolute",
    top:           "0",
    left:          "0",
    width:         "0",
    height:        "0",
    overflow:      "visible",
    pointerEvents: "none",
    zIndex:        "2147483646",
  });

  const validBlocks = blocks.filter((b) => b.translated && b.translated.trim());

  for (const block of validBlocks) {
    const div = document.createElement("div");
    Object.assign(div.style, {
      position:     "absolute",
      left:         block.x + "px",
      top:          block.y + "px",
      width:        block.width + "px",
      minHeight:    block.height + "px",
      // fontSizeOverride 0 = Auto: match the source element's font size.
      fontSize:     (fontSizeOverride > 0 ? fontSizeOverride : Math.max(10, block.fontSize)) + "px",
      fontWeight:   parseInt(block.fontWeight, 10) >= 600 ? "600" : "400",
      fontFamily:   "-apple-system, 'Segoe UI', system-ui, sans-serif",
      lineHeight:   "1.45",
      color:        "#e8f0fe",
      background:   "rgba(10, 20, 48, 0.94)",
      border:       "1.5px solid rgba(79, 142, 247, 0.6)",
      borderRadius: "5px",
      padding:      "2px 6px",
      whiteSpace:   "pre-wrap",
      boxSizing:    "border-box",
      boxShadow:    "0 2px 10px rgba(0,0,0,0.5)",
      overflow:     "hidden",
    });
    div.textContent = block.translated;
    root.appendChild(div);
  }

  document.body.appendChild(root);

  // ── Floating control toolbar ─────────────────────────────────────────
  const toolbar = document.createElement("div");
  toolbar.id = "__pt_toolbar__";
  Object.assign(toolbar.style, {
    position:             "fixed",
    bottom:               "20px",
    right:                "20px",
    zIndex:               "2147483647",
    display:              "flex",
    alignItems:           "center",
    gap:                  "8px",
    padding:              "8px 14px",
    background:           "rgba(13, 13, 20, 0.96)",
    backdropFilter:       "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    border:               "1px solid rgba(79, 142, 247, 0.35)",
    borderRadius:         "40px",
    boxShadow:            "0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06)",
    fontFamily:           "-apple-system, 'Segoe UI', system-ui, sans-serif",
    fontSize:             "12px",
    color:                "#e4e4f0",
    userSelect:           "none",
    pointerEvents:        "all",
    cursor:               "default",
    transition:           "opacity 0.2s",
  });

  const mkBtn = (text, title, extra = {}) => {
    const btn = document.createElement("button");
    Object.assign(btn.style, {
      background:   "none",
      border:       "none",
      cursor:       "pointer",
      fontFamily:   "inherit",
      fontSize:     "12px",
      color:        "#e4e4f0",
      padding:      "3px 8px",
      borderRadius: "6px",
      transition:   "color 0.15s, background 0.15s",
      ...extra,
    });
    btn.textContent = text;
    btn.title = title;
    btn.addEventListener("mouseenter", () => { btn.style.background = "rgba(255,255,255,0.07)"; });
    btn.addEventListener("mouseleave", () => { btn.style.background = "none"; });
    return btn;
  };

  const sep = () => {
    const d = document.createElement("div");
    d.style.cssText = "width:1px;height:14px;background:rgba(255,255,255,0.1);flex-shrink:0;";
    return d;
  };

  const globe    = document.createElement("span");
  globe.textContent  = "🌐";
  globe.style.fontSize = "15px";

  const countEl  = document.createElement("span");
  countEl.style.cssText = "font-weight:600;color:#4f8ef7;white-space:nowrap;";
  countEl.textContent = `${validBlocks.length} blocks translated`;

  const toggleBtn = mkBtn("Hide", "Toggle overlay");
  const closeBtn  = mkBtn("✕",   "Remove translation", { color: "#7b7b96", fontSize: "14px", lineHeight: "1" });

  toolbar.append(globe, countEl, sep(), toggleBtn, sep(), closeBtn);
  document.body.appendChild(toolbar);

  let visible = true;

  toggleBtn.addEventListener("click", () => {
    visible = !visible;
    root.style.display      = visible ? "" : "none";
    toggleBtn.textContent   = visible ? "Hide" : "Show";
    toggleBtn.style.color   = visible ? "#e4e4f0" : "#4f8ef7";
  });

  closeBtn.addEventListener("click", removeTranslationOverlay);
}

// ── Message listener ─────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  try {
    switch (msg.type) {
      case "EXTRACT_TEXT_BLOCKS": {
        const blocks = extractTextBlocks(!!msg.onlyNew);
        sendResponse({
          blocks,
          viewportWidth: window.innerWidth,
          viewportHeight: window.innerHeight,
          scrollX: window.scrollX,
          scrollY: window.scrollY,
          devicePixelRatio: window.devicePixelRatio,
          pageUrl: location.href,
          pageTitle: document.title
        });
        break;
      }
      case "GET_PAGE_DIMENSIONS":
        sendResponse(getPageDimensions());
        break;
      case "SCROLL_TO":
        sendResponse(scrollToY(msg.y));
        break;
      case "RESET_EXTRACTION":
        resetExtraction();
        sendResponse({ ok: true });
        break;
      case "APPLY_TRANSLATION":
        applyTranslationOverlay(msg.blocks, msg.fontSizeOverride || 0);
        sendResponse({ ok: true });
        break;
      case "REMOVE_TRANSLATION":
        removeTranslationOverlay();
        sendResponse({ ok: true });
        break;
      default:
        // Unknown message type — respond so the port isn't left hanging.
        sendResponse({ ok: false, error: `Unknown message type: ${msg.type}` });
    }
  } catch (err) {
    // Ensure sendResponse is always called even if a handler throws,
    // so the popup's sendTabMessage Promise resolves (as a rejection)
    // rather than triggering "message port closed" errors.
    try { sendResponse({ ok: false, error: err.message }); } catch (_) {}
  }
  // Return true to keep the message channel open long enough for Chrome
  // to flush the synchronous sendResponse call on all platforms/versions.
  return true;
});
}
