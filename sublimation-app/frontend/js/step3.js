import { state } from './state.js';
import { apiFetch } from './api.js';
import { toast, setStep, _pieceDisplayName } from './ui.js';
import { runGrading } from './step4.js';

// ── Önizleme thumbnail SVG içeriği ───────────────────────────────────────────

export function _thumbSvgContent(type, pdata, imgSrc, deg, W = 200, H = 130) {
  if (!pdata?.points_preview?.length) {
    return `<rect width="${W}" height="${H}" fill="#f8fafc"/>
            <text x="${W/2}" y="${H/2+4}" text-anchor="middle" fill="#94a3b8" font-size="11">Önizleme yok</text>`;
  }
  const pts = pdata.points_preview;
  const bb  = pdata.bbox;
  const pad = 10;
  const scale = Math.min((W - 2*pad) / bb.w, (H - 2*pad) / bb.h);
  const dw = bb.w * scale, dh = bb.h * scale;
  const ox = (W - dw) / 2, oy = (H - dh) / 2;
  const poly = pts.map(([x,y]) =>
    `${((x - bb.x)*scale + ox).toFixed(1)},${((y - bb.y)*scale + oy).toFixed(1)}`
  ).join(" ");
  const clipId = `cp-${type}`;
  const cx = W/2, cy = H/2;
  let imgEl = "";
  if (imgSrc) {
    const tx   = state.designTransforms[type] || { offsetX: 0, offsetY: 0, scale: 1.0 };
    const scl  = Math.max(tx.scale, 0.01);
    const d    = Math.max(dw, dh) * scl;
    const ix   = (cx - d/2 + tx.offsetX * dw).toFixed(1);
    const iy   = (cy - d/2 + tx.offsetY * dh).toFixed(1);
    const tr   = deg ? ` transform="rotate(${deg} ${cx} ${cy})"` : "";
    imgEl = `<g clip-path="url(#${clipId})">
      <image href="${imgSrc}" x="${ix}" y="${iy}"
             width="${d.toFixed(1)}" height="${d.toFixed(1)}"
             preserveAspectRatio="xMidYMid slice"${tr}/>
    </g>`;
  }
  const fill   = imgSrc ? "none" : "#dbeafe";
  const stroke = imgSrc ? "rgba(0,0,0,0.3)" : "#2563eb";
  return `<defs><clipPath id="${clipId}"><polygon points="${poly}"/></clipPath></defs>
          <rect width="${W}" height="${H}" fill="${imgSrc ? "white" : "#f8fafc"}"/>
          <polygon points="${poly}" fill="${fill}" stroke-width="0"/>
          ${imgEl}
          <polygon points="${poly}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round"/>`;
}

export function updateThumbDesign(type) {
  const safeId = `design-${type}`;
  const svgEl  = document.getElementById(`thumb-${safeId}`);
  if (!svgEl) return;
  const pdata  = state.piecePreview[type];
  const imgSrc = state.designDataUrls[type] || null;
  const deg    = state.designRotations[type] ?? 0;

  let W = 200, H = 130;
  if (pdata?.bbox && pdata.bbox.w > 0 && pdata.bbox.h > 0) {
    const pad = 10;
    const maxSide = 200;
    const scaleToFit = Math.min((maxSide - 2*pad) / pdata.bbox.w, (maxSide - 2*pad) / pdata.bbox.h);
    W = Math.round(pdata.bbox.w * scaleToFit + 2*pad);
    H = Math.round(pdata.bbox.h * scaleToFit + 2*pad);
    svgEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const drawScale = Math.min((W - 2*pad) / pdata.bbox.w, (H - 2*pad) / pdata.bbox.h);
    svgEl.dataset.dw = (pdata.bbox.w * drawScale).toFixed(2);
    svgEl.dataset.dh = (pdata.bbox.h * drawScale).toFixed(2);
  }
  svgEl.innerHTML = _thumbSvgContent(type, pdata, imgSrc, deg, W, H);
}

function _refreshAdaptBtn() {
  const btn  = document.getElementById("adapt-btn");
  const hint = document.getElementById("adapt-hint");
  if (!btn) return;
  const hasDesign = Object.keys(state.designFiles).length > 0;
  btn.disabled = !hasDesign;
  if (hasDesign) {
    hint.textContent = `${Object.keys(state.designFiles).length} parçaya tasarım yüklendi — hazır`;
    hint.style.color = "var(--green, #15803d)";
  } else {
    hint.textContent = "En az bir parçaya tasarım yükleyin";
    hint.style.color = "";
  }
}

export function renderDesignSection(types, previewData) {
  const grid = document.getElementById("design-grid");
  grid.innerHTML = "";
  if (!types.length) return;

  const banner     = document.getElementById("ref-size-banner");
  const adaptRow   = document.getElementById("adapt-btn-row");
  const step3Desc  = document.getElementById("step3-desc");

  if (state.pltMode === "graded") {
    const totalSizes = Object.keys(state.allPieces).length;

    const sel = document.getElementById("ref-size-select-step3");
    if (sel) {
      sel.innerHTML = Object.keys(state.allPieces).map(sKey => {
        const lbl = state.sizeLabels?.[sKey] || sKey;
        return `<option value="${sKey}" ${sKey === state.referenceSize ? "selected" : ""}>${lbl}</option>`;
      }).join("");

      sel.onchange = () => {
        state.referenceSize = sel.value;
        // Import at top of module — need to update from step2
        const hint = document.getElementById("ref-size-hint-text");
        if (hint) hint.textContent =
          `${state.sizeLabels?.[state.referenceSize] || state.referenceSize} — diğer ${totalSizes - 1} beden otomatik ölçeklendirilecek`;
        const group = state.allPieces[state.referenceSize] || {};
        state.piecePreview = {};
        for (const [ptype, pdata] of Object.entries(group)) {
          state.piecePreview[ptype] = pdata;
        }
        renderDesignSection(Object.keys(state.allPieces[state.referenceSize] || {}), state.piecePreview);
      };
    }

    const hint = document.getElementById("ref-size-hint-text");
    if (hint) hint.textContent =
      `${state.sizeLabels?.[state.referenceSize] || state.referenceSize} — diğer ${totalSizes - 1} beden otomatik ölçeklendirilecek`;

    banner?.classList.remove("hidden");

    if (adaptRow) {
      adaptRow.classList.remove("hidden");
      const adaptBtnText = document.getElementById("adapt-btn-text");
      if (adaptBtnText) adaptBtnText.textContent =
        `Tüm ${totalSizes} Bedene Uyarla & PDF Üret`;
      _refreshAdaptBtn();

      const adaptBtn = document.getElementById("adapt-btn");
      adaptBtn?.removeEventListener("click", runGrading);
      adaptBtn?.addEventListener("click", runGrading);
    }

    if (step3Desc) step3Desc.innerHTML =
      `Seçtiğiniz bedene ait parçalar için tasarım yükleyin. ` +
      `<em>Tüm Bedenlere Uyarla</em> butonu ile tasarım ${totalSizes} bedene otomatik ölçeklenir.`;
  } else {
    banner?.classList.add("hidden");
    adaptRow?.classList.add("hidden");
    if (step3Desc) step3Desc.innerHTML =
      `Seçtiğiniz her parça için tasarım görselini yükleyin. ` +
      `<strong>Tümüne Uygula</strong> ile aynı deseni bütün parçalara atayabilirsiniz.`;
  }

  const DISPLAY = {
    front:        { icon: "👕", label: "Ön Panel"    },
    back:         { icon: "🔄", label: "Arka Panel"  },
    left_sleeve:  { icon: "💪", label: "Sol Kol"     },
    right_sleeve: { icon: "💪", label: "Sağ Kol"     },
  };

  types.forEach(type => {
    const d = DISPLAY[type] || { icon: "▪", label: type.replace(/_/g," ") };
    const safeId = `design-${type}`;
    const pdata  = previewData?.[type];

    let dimsHtml = "";
    if (pdata?.bbox) {
      const wCm = (pdata.bbox.w / 10).toFixed(0);
      const hCm = (pdata.bbox.h / 10).toFixed(0);
      dimsHtml = `<span class="piece-dims">${wCm}×${hCm} cm</span>`;
    }

    const card = document.createElement("div");
    card.className = "design-card";
    card.innerHTML = `
      <div class="design-card-header">
        <span class="piece-icon">${d.icon}</span>
        <div class="piece-title">
          <span>${d.label}</span>
          ${dimsHtml}
        </div>
        <button type="button" class="btn-preview" id="preview-${safeId}" data-type="${type}" title="Önizle">
          <svg viewBox="0 0 20 20" fill="currentColor" width="16"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/></svg>
        </button>
        <button type="button" class="btn-rotate hidden" id="rotate-${safeId}" data-type="${type}">
          <span class="rotate-icon">↻</span> <span class="rotate-deg">0°</span>
        </button>
      </div>
      <input type="file" id="input-${safeId}" class="design-input" data-type="${type}"
             accept=".png,.jpg,.jpeg,.svg,.webp,.tif,.tiff" style="display:none">
      <div class="design-drop" data-type="${type}">
        <svg id="thumb-${safeId}" class="piece-thumb-svg"
             viewBox="0 0 200 130" xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink"
             data-type="${type}" data-dw="0" data-dh="0">
          ${_thumbSvgContent(type, pdata, null, 0)}
        </svg>
        <div class="thumb-upload-hint" id="hint-${safeId}">
          <svg viewBox="0 0 48 48" fill="none" width="26">
            <path d="M24 8L24 32M14 22L24 32L34 22" stroke="#94a3b8" stroke-width="3" stroke-linecap="round"/>
            <path d="M8 40L40 40" stroke="#94a3b8" stroke-width="2.5" stroke-linecap="round"/>
          </svg>
          <span>Tıkla veya sürükle</span>
        </div>
        <button type="button" class="btn-remove hidden" data-type="${type}" id="remove-${safeId}">✕</button>
        <label for="input-${safeId}" class="design-click-overlay" id="label-${safeId}"></label>
      </div>
      <div class="tx-controls hidden" id="txctrls-${safeId}">
        <span class="tx-label">Konum</span>
        <input type="range" class="tx-slider" id="scale-slider-${safeId}"
               data-type="${type}" min="0.8" max="3.0" step="0.05" value="1.0">
        <span class="tx-scale-val" id="scale-val-${safeId}">1.0×</span>
        <button type="button" class="btn-tx-reset" data-type="${type}" id="tx-reset-${safeId}">⟲</button>
      </div>`;
    grid.appendChild(card);

    const inp     = card.querySelector(".design-input");
    const drop    = card.querySelector(".design-drop");
    const btnR    = card.querySelector(".btn-remove");
    const btnRot  = card.querySelector(".btn-rotate");
    const btnPrev = card.querySelector(".btn-preview");

    inp.addEventListener("change", () => { if (inp.files[0]) handleDesign(type, inp.files[0]); });
    drop.addEventListener("dragover",  e => { e.preventDefault(); drop.classList.add("drag-over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
    drop.addEventListener("drop", e => {
      e.preventDefault(); drop.classList.remove("drag-over");
      const f = e.dataTransfer.files[0]; if (f) handleDesign(type, f);
    });
    btnR.addEventListener("click",    e => { e.stopPropagation(); removeDesign(type); });
    btnRot.addEventListener("click",  e => { e.stopPropagation(); rotateDesign(type); });
    btnPrev.addEventListener("click", e => { e.stopPropagation(); openPreviewModal(type, pdata); });

    const svgThumb = card.querySelector(".piece-thumb-svg");
    _initDragTransform(svgThumb, type);

    const scaleSlider = card.querySelector(".tx-slider");
    scaleSlider.addEventListener("input", function() {
      if (!state.designTransforms[type]) state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
      state.designTransforms[type].scale = parseFloat(this.value);
      document.getElementById(`scale-val-${safeId}`).textContent = parseFloat(this.value).toFixed(2) + "×";
      updateThumbDesign(type);
    });

    card.querySelector(".btn-tx-reset").addEventListener("click", e => {
      e.stopPropagation();
      state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
      scaleSlider.value = "1.0";
      document.getElementById(`scale-val-${safeId}`).textContent = "1.0×";
      updateThumbDesign(type);
    });
  });

  const inputAll = document.getElementById("input-all");
  const inputAllClone = inputAll.cloneNode(true);
  inputAll.parentNode.replaceChild(inputAllClone, inputAll);
  inputAllClone.id = "input-all";
  inputAllClone.addEventListener("change", () => {
    if (!inputAllClone.files[0]) return;
    const f = inputAllClone.files[0];
    types.forEach(t => handleDesign(t, f));
    document.getElementById("apply-all-hint").textContent =
      `✓ ${types.length} parçaya "${f.name}" atandı`;
    inputAllClone.value = "";
  });
}

export function handleDesign(type, file) {
  const isTiff = file.name.toLowerCase().endsWith(".tif") || file.name.toLowerCase().endsWith(".tiff");
  const maxMB  = isTiff ? 150 : 30;
  if (file.size > maxMB * 1024 * 1024) {
    toast(`Tasarım ${maxMB}MB'den büyük olamaz`, "error"); return;
  }
  state.designFiles[type] = file;
  if (!(type in state.designRotations)) state.designRotations[type] = 0;
  if (Object.keys(state.designFiles).length === 1) setStep(3);

  const safeId = `design-${type}`;
  const reader = new FileReader();
  reader.onload = ev => {
    state.designDataUrls[type] = ev.target.result;
    if (!state.designTransforms[type]) {
      state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
    }
    updateThumbDesign(type);
    document.getElementById(`hint-${safeId}`)?.classList.add("hidden");
    document.getElementById(`remove-${safeId}`)?.classList.remove("hidden");
    document.getElementById(`txctrls-${safeId}`)?.classList.remove("hidden");
    const svgEl = document.getElementById(`thumb-${safeId}`);
    if (svgEl) svgEl.classList.add("has-design");
    const btnRot = document.getElementById(`rotate-${safeId}`);
    if (btnRot) {
      btnRot.classList.remove("hidden");
      const degEl = btnRot.querySelector(".rotate-deg");
      if (degEl) degEl.textContent = `${state.designRotations[type]}°`;
    }
    _refreshAdaptBtn();
  };
  reader.readAsDataURL(file);
}

export function rotateDesign(type) {
  state.designRotations[type] = ((state.designRotations[type] ?? 0) + 90) % 360;
  if (state.designDataUrls[type]) updateThumbDesign(type);
  const safeId = `design-${type}`;
  const degEl  = document.querySelector(`#rotate-${safeId} .rotate-deg`);
  if (degEl) degEl.textContent = `${state.designRotations[type]}°`;
}

export function removeDesign(type) {
  delete state.designFiles[type];
  delete state.designRotations[type];
  delete state.designTransforms[type];
  delete state.designDataUrls[type];
  updateThumbDesign(type);
  _refreshAdaptBtn();
  const safeId = `design-${type}`;
  document.getElementById(`hint-${safeId}`)?.classList.remove("hidden");
  document.getElementById(`remove-${safeId}`)?.classList.add("hidden");
  document.getElementById(`txctrls-${safeId}`)?.classList.add("hidden");
  document.getElementById(`thumb-${safeId}`)?.classList.remove("has-design");
  const sliderEl = document.getElementById(`scale-slider-${safeId}`);
  if (sliderEl) sliderEl.value = "1.0";
  const valEl = document.getElementById(`scale-val-${safeId}`);
  if (valEl) valEl.textContent = "1.0×";
  const btnRot = document.getElementById(`rotate-${safeId}`);
  if (btnRot) {
    btnRot.classList.add("hidden");
    const degEl = btnRot.querySelector(".rotate-deg");
    if (degEl) degEl.textContent = "0°";
  }
}

export function _initDragTransform(svgEl, type) {
  if (!svgEl) return;
  let dragging = false;
  let startClientX, startClientY, startOffX, startOffY;

  const getDims = () => ({
    dw: parseFloat(svgEl.dataset.dw) || 100,
    dh: parseFloat(svgEl.dataset.dh) || 80,
  });

  svgEl.addEventListener("mousedown", e => {
    if (!state.designDataUrls[type]) return;
    e.preventDefault();
    dragging = true;
    startClientX = e.clientX;
    startClientY = e.clientY;
    const tx = state.designTransforms[type] || { offsetX: 0, offsetY: 0, scale: 1.0 };
    startOffX = tx.offsetX;
    startOffY = tx.offsetY;
    svgEl.style.cursor = "grabbing";
  });

  window.addEventListener("mousemove", e => {
    if (!dragging) return;
    const rect  = svgEl.getBoundingClientRect();
    const vbW   = parseFloat(svgEl.getAttribute("viewBox")?.split(" ")[2]) || 200;
    const domW  = rect.width;
    const { dw, dh } = getDims();
    const dxSvg = (e.clientX - startClientX) * (vbW / domW);
    const dySvg = (e.clientY - startClientY) * (vbW / domW);
    const newOffX = startOffX + dxSvg / dw;
    const newOffY = startOffY + dySvg / dh;

    if (!state.designTransforms[type]) state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
    state.designTransforms[type].offsetX = newOffX;
    state.designTransforms[type].offsetY = newOffY;
    updateThumbDesign(type);
  });

  window.addEventListener("mouseup", () => {
    if (dragging) {
      dragging = false;
      svgEl.style.cursor = state.designDataUrls[type] ? "grab" : "default";
    }
  });

  svgEl.addEventListener("touchstart", e => {
    if (!state.designDataUrls[type]) return;
    const t = e.touches[0];
    dragging = true;
    startClientX = t.clientX; startClientY = t.clientY;
    const tx = state.designTransforms[type] || { offsetX: 0, offsetY: 0, scale: 1.0 };
    startOffX = tx.offsetX; startOffY = tx.offsetY;
  }, { passive: true });

  svgEl.addEventListener("touchmove", e => {
    if (!dragging) return;
    e.preventDefault();
    const t = e.touches[0];
    const rect = svgEl.getBoundingClientRect();
    const { dw, dh } = getDims();
    const vbW = parseFloat(svgEl.getAttribute("viewBox")?.split(" ")[2]) || 200;
    const dxSvg = (t.clientX - startClientX) * (vbW / rect.width);
    const dySvg = (t.clientY - startClientY) * (vbW / rect.width);
    if (!state.designTransforms[type]) state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
    state.designTransforms[type].offsetX = startOffX + dxSvg / dw;
    state.designTransforms[type].offsetY = startOffY + dySvg / dh;
    updateThumbDesign(type);
  }, { passive: false });

  svgEl.addEventListener("touchend", () => { dragging = false; });
}

export function openPreviewModal(type, pdata) {
  document.getElementById("preview-modal")?.remove();

  const W = 480, H = 340;
  const imgSrc = state.designDataUrls[type] || null;
  const deg    = state.designRotations[type] ?? 0;
  const svgInner = _thumbSvgContent(type, pdata, imgSrc, deg);

  const modal = document.createElement("div");
  modal.id = "preview-modal";
  modal.innerHTML = `
    <div class="pm-backdrop"></div>
    <div class="pm-panel">
      <div class="pm-header">
        <span>${_pieceDisplayName(type)} — Önizleme</span>
        <button class="pm-close" id="pm-close-btn">✕</button>
      </div>
      <div class="pm-body">
        <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink"
             style="width:100%;height:auto;display:block">
          ${svgInner}
        </svg>
        ${!imgSrc ? '<p class="pm-hint">Tasarım yüklendikten sonra desen görünür.</p>' : ''}
      </div>
    </div>`;
  document.body.appendChild(modal);

  const close = () => document.getElementById("preview-modal")?.remove();
  modal.querySelector(".pm-backdrop").addEventListener("click", close);
  modal.querySelector("#pm-close-btn").addEventListener("click", close);
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
  });
}

export async function uploadDesigns() {
  for (const [type, file] of Object.entries(state.designFiles)) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await apiFetch(`/session/${state.sessionId}/design/${type}`, { method: "POST", body: fd });
    } catch (err) {
      console.warn(`Tasarım yükleme uyarısı (${type}):`, err.message);
    }
  }
}
