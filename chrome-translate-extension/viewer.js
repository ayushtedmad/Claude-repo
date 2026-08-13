(async function () {
  const { lastCapture } = await chrome.storage.local.get("lastCapture");
  if (!lastCapture) {
    document.body.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;
                  font-family:-apple-system,'Segoe UI',system-ui,sans-serif;
                  background:#0d0d14;color:#7b7b96;flex-direction:column;gap:12px;text-align:center;padding:40px;">
        <div style="font-size:36px">🌐</div>
        <div style="font-size:16px;font-weight:600;color:#e4e4f0;">No capture found</div>
        <div style="font-size:13px;line-height:1.6;">
          Run the extension from a page first using the toolbar popup.<br>
          The result will appear here automatically.
        </div>
      </div>`;
    return;
  }

  const { screenshot, pageWidth, blocks, pageTitle, fontSizeOverride = 0 } = lastCapture;

  // Header title
  document.getElementById("pageTitle").textContent = pageTitle || "Untitled page";
  document.title = `Translated — ${pageTitle || "page"}`;

  // Block count badge
  document.getElementById("blockCount").textContent = `${blocks.length} blocks`;

  const originalImg    = document.getElementById("originalImg");
  const translatedImg  = document.getElementById("translatedImg");
  const stage          = document.getElementById("translatedStage");
  const toggleBtn      = document.getElementById("toggleOverlay");
  const opacitySlider  = document.getElementById("opacitySlider");
  const fontSizeSlider = document.getElementById("fontSizeSlider");

  fontSizeSlider.value = fontSizeOverride || 0;

  originalImg.src   = screenshot;
  translatedImg.src = screenshot;

  let overlayVisible = true;

  // ── Render overlay ────────────────────────────────────────────────────────
  function renderOverlay() {
    // Guard: image not yet painted — clientWidth is 0 so scale would be wrong.
    if (translatedImg.clientWidth === 0) return;

    // Remove old boxes but keep the <img>.
    stage.querySelectorAll(".overlay-box").forEach((el) => el.remove());

    if (!overlayVisible) return;

    // Scale factor: the PNG was captured at CSS pixels == pageWidth, but the
    // <img> may be rendered narrower (width:100% inside a constrained pane).
    const scale = translatedImg.clientWidth / pageWidth;
    const opacity = parseInt(opacitySlider.value, 10) / 100;

    for (const block of blocks) {
      if (!block.translated || !block.translated.trim()) continue;

      const div = document.createElement("div");
      div.className = "overlay-box";

      // Position + size — use document-relative coords from the capture.
      div.style.left      = (block.x * scale) + "px";
      div.style.top       = (block.y * scale) + "px";
      div.style.width     = (block.width * scale) + "px";
      div.style.minHeight = (block.height * scale) + "px";

      // read from fontSizeSlider
      const currentFontSizeOverride = parseInt(fontSizeSlider.value, 10);
      
      // currentFontSizeOverride 0 = Auto: scale source font with the image.
      // Otherwise use the fixed override value, still scaled so it
      // stays proportional to the displayed image width.
      const scaledFont = currentFontSizeOverride > 0
        ? Math.max(9, currentFontSizeOverride * scale)
        : Math.max(9, block.fontSize * scale);
      div.style.fontSize   = scaledFont + "px";
      div.style.fontWeight = parseInt(block.fontWeight, 10) >= 600 ? "600" : "400";

      // Override source color — the dark blue box always needs light text.
      div.style.color = "#e8f0fe";

      div.style.opacity    = opacity;
      div.textContent      = block.translated;

      stage.appendChild(div);
    }
  }

  // ── Toggle overlay visibility ─────────────────────────────────────────────
  toggleBtn.addEventListener("click", () => {
    overlayVisible = !overlayVisible;
    toggleBtn.classList.toggle("active", overlayVisible);
    toggleBtn.innerHTML = overlayVisible
      ? '<span class="dot"></span> Overlay on'
      : '<span class="dot" style="opacity:.3"></span> Overlay off';
    renderOverlay();
  });

  // ── Opacity slider ────────────────────────────────────────────────────────
  opacitySlider.addEventListener("input", renderOverlay);

  // ── Font Size slider ──────────────────────────────────────────────────────
  fontSizeSlider.addEventListener("input", renderOverlay);

  // ── Sync both panes' scroll position ─────────────────────────────────────
  const originalStage = originalImg.closest(".stage");
  let syncLock = false;

  originalStage.addEventListener("scroll", () => {
    if (syncLock) return;
    syncLock = true;
    stage.scrollTop  = originalStage.scrollTop;
    stage.scrollLeft = originalStage.scrollLeft;
    syncLock = false;
  });

  stage.addEventListener("scroll", () => {
    if (syncLock) return;
    syncLock = true;
    originalStage.scrollTop  = stage.scrollTop;
    originalStage.scrollLeft = stage.scrollLeft;
    syncLock = false;
  });

  // ── Initial render ────────────────────────────────────────────────────────
  if (translatedImg.complete) {
    renderOverlay();
  } else {
    translatedImg.onload = renderOverlay;
  }

  // Re-render when the window is resized so overlays stay aligned.
  window.addEventListener("resize", renderOverlay);
})();
