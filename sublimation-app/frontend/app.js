"use strict";

const API = "";

// ── Durum ─────────────────────────────────────────────────────────────────────
const state = {
  sessionId:      null,
  pltFile:        null,
  designFiles:    {},    // { piece_type: File }
  designRotations:{},    // { piece_type: 0|90|180|270 }
  designDataUrls: {},    // { piece_type: dataUrl }  — thumbnail için
  piecePreview:   {},    // { piece_type: {bbox, points_preview, area_cm2} }
  detectedSizes:      [],
  detectedPieceTypes: [],
  failedSizes:        [],
};

// ── Stepper ───────────────────────────────────────────────────────────────────
function setStep(n) {
  document.querySelectorAll(".step").forEach(el => {
    const s = parseInt(el.dataset.step);
    el.classList.remove("active", "done");
    if (s === n) el.classList.add("active");
    else if (s < n) el.classList.add("done");
  });
  // Mevcut adım + bir sonraki adımı aç; adım 1'de hepsi kapalı
  for (let i = 2; i <= 4; i++) {
    const card = document.getElementById(`step-${i}`);
    if (!card) continue;
    if (n >= 2 && i <= n + 1) card.classList.remove("disabled");
    else card.classList.add("disabled");
  }
}

// ── Araçlar ───────────────────────────────────────────────────────────────────
function toast(msg, type = "info") {
  let box = document.querySelector(".toast-container");
  if (!box) {
    box = document.createElement("div");
    box.className = "toast-container";
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

async function apiFetch(path, options = {}) {
  const res  = await fetch(API + path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ── Oturum ────────────────────────────────────────────────────────────────────
async function ensureSession() {
  if (state.sessionId) return;
  const fd = new FormData();
  fd.append("reference_size", "M");
  const data = await apiFetch("/session", { method: "POST", body: fd });
  state.sessionId = data.session_id;
}

// ── PLT yükleme ───────────────────────────────────────────────────────────────
const pltInput     = document.getElementById("plt-input");
const pltDrop      = document.getElementById("plt-drop");
const pltInfo      = document.getElementById("plt-info");
const pltFilename  = document.getElementById("plt-filename");
const pltUploadBtn = document.getElementById("plt-upload-btn");
const pltResult    = document.getElementById("plt-result");
const pltProgress  = document.getElementById("plt-progress");
const pltFill      = document.getElementById("plt-progress-fill");

pltInput.addEventListener("change", () => {
  if (pltInput.files[0]) setPLTFile(pltInput.files[0]);
});
pltDrop.addEventListener("dragover",  e => { e.preventDefault(); pltDrop.classList.add("drag-over"); });
pltDrop.addEventListener("dragleave", () => pltDrop.classList.remove("drag-over"));
pltDrop.addEventListener("drop", e => {
  e.preventDefault(); pltDrop.classList.remove("drag-over");
  const f = e.dataTransfer.files[0]; if (f) setPLTFile(f);
});
document.getElementById("plt-clear").addEventListener("click", e => {
  e.preventDefault();
  state.pltFile        = null;
  state.sessionId      = null;
  state.designFiles    = {};
  state.designRotations= {};
  state.designDataUrls = {};
  state.piecePreview   = {};
  pltInput.value = "";
  pltInfo.classList.add("hidden");
  pltResult.classList.add("hidden");
  // Adımları sıfırla
  setStep(1);
});

function setPLTFile(f) {
  state.pltFile = f;
  pltFilename.textContent = f.name;
  pltInfo.classList.remove("hidden");
}

pltUploadBtn.addEventListener("click", async e => {
  e.preventDefault();
  if (!state.pltFile) { toast("PLT dosyası seçilmedi", "error"); return; }
  if (state.pltFile.size > 100 * 1024 * 1024) {
    toast("Dosya 100MB'den büyük olamaz", "error"); return;
  }
  pltUploadBtn.disabled = true;
  pltProgress.classList.remove("hidden");
  pltFill.style.width = "20%";
  try {
    // Her PLT yüklemesinde taze oturum aç
    state.sessionId      = null;
    state.designFiles    = {};
    state.designRotations= {};
    state.designDataUrls = {};
    state.piecePreview   = {};
    await ensureSession();
    pltFill.style.width = "50%";
    const fd = new FormData();
    fd.append("file", state.pltFile);
    const data = await apiFetch(`/session/${state.sessionId}/plt`, { method: "POST", body: fd });
    pltFill.style.width = "100%";
    toast(`PLT analiz edildi — ${data.total_pieces} parça`, "success");
    renderPLTResult(data);
  } catch (err) {
    console.error("PLT hatası:", err);
    const msg = err.message || String(err);
    const warnEl = document.getElementById("plt-warnings");
    if (warnEl) {
      warnEl.innerHTML = `<p>❌ ${msg}</p>`;
      warnEl.classList.remove("hidden");
    }
    toast(msg, "error");
  } finally {
    pltUploadBtn.disabled = false;
    setTimeout(() => pltProgress.classList.add("hidden"), 600);
  }
});

async function renderPLTResult(data) {
  state.detectedSizes      = data.detected_sizes || [];
  state.detectedPieceTypes = data.piece_types_found || [];

  // Chips
  document.getElementById("size-chips").innerHTML =
    state.detectedSizes.map(s => `<span class="chip chip-blue">${s}</span>`).join("");
  document.getElementById("piece-chips").innerHTML =
    state.detectedPieceTypes.map(p => `<span class="chip chip-green">${p.replace(/_/g," ")}</span>`).join("")
    || '<span class="chip chip-gray">Tespit edilemedi</span>';

  const warn = document.getElementById("plt-warnings");
  if (data.warnings?.length) {
    warn.innerHTML = data.warnings.map(w => `<p>⚠ ${w}</p>`).join("");
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  // Debug link
  const debugLink = document.getElementById("debug-plt-link");
  if (debugLink) {
    debugLink.href  = `/session/${state.sessionId}/debug-plt`;
    debugLink.style.display = "inline-flex";
  }

  pltResult.classList.remove("hidden");
  setStep(2);
  renderSizeSection(state.detectedSizes);

  // Preview verisi: parça boyutları + thumbnail için
  let previewData = null;
  const assignContainer = document.getElementById("piece-assign-table");
  assignContainer.innerHTML = "<p style='color:var(--gray-500);font-size:.83rem'>Yükleniyor...</p>";
  try {
    const preview = await apiFetch(`/session/${state.sessionId}/preview`);
    // Referans beden veya ilk beden
    const refSize = state.detectedSizes[0] || Object.keys(preview)[0];
    if (refSize && preview[refSize]) {
      previewData = preview[refSize];
      state.piecePreview = previewData;
    }
    renderAssignTable(preview);
  } catch (e) {
    assignContainer.innerHTML = `<p style='color:var(--red);font-size:.83rem'>Hata: ${e.message}</p>`;
  }

  renderDesignSection(state.detectedPieceTypes, previewData);
}

// ── Beden seçici (dinamik) ────────────────────────────────────────────────────
function renderSizeSection(sizes) {
  const sizeOrder = ["XXS","XS","S","M","L","XL","XXL","XXXL"];

  // Referans beden radiolari
  const selector = document.getElementById("size-selector");
  selector.innerHTML = sizes.map((s, i) => `
    <label class="size-radio${i===0?" selected":""}">
      <input type="radio" name="ref-size" value="${s}" ${i===0?"checked":""}> ${s}
    </label>`).join("");
  selector.querySelectorAll(".size-radio").forEach(lbl => {
    lbl.addEventListener("click", () => {
      selector.querySelectorAll(".size-radio").forEach(l => l.classList.remove("selected"));
      lbl.classList.add("selected");
      lbl.querySelector("input").checked = true;
    });
  });

  // Çıktı bedenleri checkboxları
  const out = document.getElementById("output-sizes");
  out.innerHTML = sizes.map(s => `
    <label class="checkbox-label">
      <input type="checkbox" value="${s}" checked> ${s}
    </label>`).join("");

  // Listener birikmesin — butonu klonla
  const selAllBtn = document.getElementById("select-all-sizes");
  const selAllClone = selAllBtn.cloneNode(true);
  selAllBtn.parentNode.replaceChild(selAllClone, selAllBtn);
  selAllClone.addEventListener("click", () => {
    out.querySelectorAll("input[type=checkbox]").forEach(cb => cb.checked = true);
  });

}

// ── Tasarım kartları (dinamik) ─────────────────────────────────────────────────
const PIECE_DISPLAY = {
  front:         { icon: "👕", label: "Ön Panel"    },
  back:          { icon: "🔄", label: "Arka Panel"  },
  left_sleeve:   { icon: "💪", label: "Sol Kol"     },
  right_sleeve:  { icon: "💪", label: "Sağ Kol"     },
  panel_front:   { icon: "▦",  label: "Ön Panel 2"  },
  panel_back:    { icon: "▦",  label: "Arka Panel 2"},
  strip:         { icon: "▬",  label: "Şerit"       },
  collar:        { icon: "🔘", label: "Yaka"        },
  sleeve:        { icon: "💪", label: "Kol"         },
};

function pieceDisplay(type) {
  if (PIECE_DISPLAY[type]) return PIECE_DISPLAY[type];
  const base = type.replace(/_\d+$/, "");
  const d    = PIECE_DISPLAY[base];
  return { icon: d?.icon || "▪", label: d ? `${d.label} ${type.match(/\d+$/)?.[0]||""}`.trim() : type.replace(/_/g," ") };
}

// ── Parça thumbnail SVG ────────────────────────────────────────────────────────
function _thumbSvgContent(type, pdata, imgSrc, deg) {
  const W = 200, H = 130;
  if (!pdata?.points_preview?.length) {
    return `<rect width="${W}" height="${H}" fill="#f8fafc"/>
            <text x="${W/2}" y="${H/2+4}" text-anchor="middle" fill="#94a3b8" font-size="11" font-family="sans-serif">Önizleme yok</text>`;
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
    const tr = deg ? ` transform="rotate(${deg} ${cx} ${cy})"` : "";
    imgEl = `<g clip-path="url(#${clipId})">
      <image href="${imgSrc}" x="${ox.toFixed(1)}" y="${oy.toFixed(1)}"
             width="${dw.toFixed(1)}" height="${dh.toFixed(1)}"
             preserveAspectRatio="xMidYMid slice"${tr}/>
    </g>`;
  }
  const fill   = imgSrc ? "none" : "#e2e8f0";
  const stroke = imgSrc ? "rgba(0,0,0,0.35)" : "#94a3b8";
  return `<defs><clipPath id="${clipId}"><polygon points="${poly}"/></clipPath></defs>
          <rect width="${W}" height="${H}" fill="${imgSrc ? "white" : "#f8fafc"}"/>
          <polygon points="${poly}" fill="${fill}" stroke-width="0"/>
          ${imgEl}
          <polygon points="${poly}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round"/>`;
}

function updateThumbDesign(type) {
  const svgEl = document.getElementById(`thumb-design-${type}`);
  if (!svgEl) return;
  const pdata  = state.piecePreview[type];
  const imgSrc = state.designDataUrls[type] || null;
  const deg    = state.designRotations[type] ?? 0;
  svgEl.innerHTML = _thumbSvgContent(type, pdata, imgSrc, deg);
}

function renderDesignSection(types, previewData) {
  const grid = document.getElementById("design-grid");
  grid.innerHTML = "";
  state.piecePreview = previewData || {};

  if (!types.length) return;

  types.forEach(type => {
    const { icon, label } = pieceDisplay(type);
    const safeId = `design-${type}`;
    const pdata  = previewData?.[type];

    // Boyut bilgisi
    let dimsHtml = "", rotHintHtml = "";
    if (pdata) {
      const wCm = (pdata.bbox.w / 10).toFixed(0);
      const hCm = (pdata.bbox.h / 10).toFixed(0);
      dimsHtml = `<span class="piece-dims">${wCm}×${hCm} cm</span>`;
      if (pdata.bbox.w > pdata.bbox.h * 1.15) {
        rotHintHtml = `<span class="rot-hint" title="Kalıp yatay — 90° döndür önerilir">↔ 90°?</span>`;
      }
    }

    const card = document.createElement("div");
    card.className = "design-card";
    card.innerHTML = `
      <div class="design-card-header">
        <span class="piece-icon">${icon}</span>
        <div class="piece-title">
          <span>${label}</span>
          ${dimsHtml}
        </div>
        ${rotHintHtml}
        <button type="button" class="btn-rotate hidden" id="rotate-${safeId}" data-type="${type}" title="Deseni döndür">
          <span class="rotate-icon">↻</span> <span class="rotate-deg">0°</span>
        </button>
      </div>
      <input type="file" id="input-${safeId}" class="design-input" data-type="${type}"
             accept=".png,.jpg,.jpeg,.svg,.webp" style="display:none">
      <div class="design-drop" data-type="${type}">
        <svg id="thumb-${safeId}" class="piece-thumb-svg"
             viewBox="0 0 200 130" xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink">
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
      </div>`;
    grid.appendChild(card);

    // Events
    const inp    = card.querySelector(".design-input");
    const drop   = card.querySelector(".design-drop");
    const btnR   = card.querySelector(".btn-remove");
    const btnRot = card.querySelector(".btn-rotate");

    inp.addEventListener("change", () => { if (inp.files[0]) handleDesign(type, inp.files[0]); });
    drop.addEventListener("dragover",  e => { e.preventDefault(); drop.classList.add("drag-over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
    drop.addEventListener("drop", e => {
      e.preventDefault(); drop.classList.remove("drag-over");
      const f = e.dataTransfer.files[0]; if (f) handleDesign(type, f);
    });
    btnR.addEventListener("click",   e => { e.stopPropagation(); removeDesign(type); });
    btnRot.addEventListener("click", e => { e.stopPropagation(); rotateDesign(type); });
  });

  // "Tümüne uygula" — listener birikmesin
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

function handleDesign(type, file) {
  if (file.size > 30 * 1024 * 1024) {
    toast(`Tasarım dosyası 30MB'den büyük olamaz (${file.name})`, "error"); return;
  }
  state.designFiles[type] = file;
  if (!(type in state.designRotations)) state.designRotations[type] = 0;
  if (Object.keys(state.designFiles).length === 1) setStep(3);

  const safeId = `design-${type}`;
  const reader = new FileReader();
  reader.onload = ev => {
    state.designDataUrls[type] = ev.target.result;
    updateThumbDesign(type);
    // UI güncellemeleri
    document.getElementById(`hint-${safeId}`)?.classList.add("hidden");
    document.getElementById(`remove-${safeId}`)?.classList.remove("hidden");
    const btnRot = document.getElementById(`rotate-${safeId}`);
    if (btnRot) {
      btnRot.classList.remove("hidden");
      const degEl = btnRot.querySelector(".rotate-deg");
      if (degEl) degEl.textContent = `${state.designRotations[type]}°`;
    }
  };
  reader.readAsDataURL(file);
}

function rotateDesign(type) {
  const cur = state.designRotations[type] ?? 0;
  state.designRotations[type] = (cur + 90) % 360;
  _applyImgRotation(type);
  const safeId = `design-${type}`;
  const degEl  = document.querySelector(`#rotate-${safeId} .rotate-deg`);
  if (degEl) degEl.textContent = `${state.designRotations[type]}°`;
}

function _applyImgRotation(type) {
  // Thumbnail SVG'yi güncelle (tasarım varsa)
  if (state.designDataUrls[type]) updateThumbDesign(type);
}

function removeDesign(type) {
  delete state.designFiles[type];
  delete state.designRotations[type];
  delete state.designDataUrls[type];

  updateThumbDesign(type); // sadece outline'a dön

  const safeId = `design-${type}`;
  document.getElementById(`hint-${safeId}`)?.classList.remove("hidden");
  document.getElementById(`remove-${safeId}`)?.classList.add("hidden");
  const btnRot = document.getElementById(`rotate-${safeId}`);
  if (btnRot) {
    btnRot.classList.add("hidden");
    const degEl = btnRot.querySelector(".rotate-deg");
    if (degEl) degEl.textContent = "0°";
  }
}

async function uploadDesigns() {
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

// ── Parça tipi atama tablosu ──────────────────────────────────────────────────

function renderAssignTable(preview) {
  const container = document.getElementById("piece-assign-table");
  const allTypes  = state.detectedPieceTypes.length
    ? state.detectedPieceTypes
    : ["front","back","left_sleeve","right_sleeve","unknown"];

  const rows = [];
  for (const [size, pieces] of Object.entries(preview))
    for (const [ptype, info] of Object.entries(pieces))
      rows.push({ size, ptype, info });

  if (!rows.length) {
    container.innerHTML = "<p style='color:var(--gray-500);font-size:.83rem'>Parça bulunamadı</p>";
    return;
  }

  const optHtml = allTypes.map(t =>
    `<option value="${t}">${t.replace(/_/g," ")}</option>`).join("");

  let html = `<table class="assign-table"><thead><tr>
    <th>Beden</th><th>Etiket</th><th>Alan</th><th>Parça Tipi</th>
  </tr></thead><tbody>`;
  for (const { size, ptype, info } of rows) {
    html += `<tr>
      <td><strong>${size}</strong></td>
      <td style="font-size:.78rem;color:var(--gray-500)">${info.label||"—"}</td>
      <td><span class="badge-area">${info.area_cm2} cm²</span></td>
      <td>
        <select data-size="${size}" data-old="${ptype}" onchange="reassignPiece(this)">
          ${allTypes.map(t=>`<option value="${t}"${t===ptype?" selected":""}>${t.replace(/_/g," ")}</option>`).join("")}
        </select>
      </td></tr>`;
  }
  html += "</tbody></table>";
  container.innerHTML = html;
}

async function reassignPiece(select) {
  const size = select.dataset.size, oldType = select.dataset.old, newType = select.value;
  if (oldType === newType) return;
  const fd = new FormData();
  fd.append("size", size); fd.append("old_type", oldType); fd.append("new_type", newType);
  try {
    await apiFetch(`/session/${state.sessionId}/assign-piece-type`, { method:"POST", body:fd });
    select.dataset.old = newType;
    toast(`${size}/${oldType} → ${newType}`, "success");
  } catch (e) {
    toast(`Atama hatası: ${e.message}`, "error");
    select.value = oldType;
  }
}

// ── Üretim ────────────────────────────────────────────────────────────────────
document.getElementById("generate-btn").addEventListener("click", () => runGrading());

async function runGrading(sizesOverride = null) {
  if (!state.sessionId) {
    toast("Önce PLT dosyası yükleyin ve Analiz Et'e tıklayın", "error"); return;
  }
  const selectedSizes = sizesOverride || Array.from(
    document.querySelectorAll("#output-sizes input:checked")
  ).map(cb => cb.value);
  if (!selectedSizes.length) { toast("En az bir çıktı bedeni seçin", "error"); return; }

  const bleed = document.getElementById("bleed-select").value;
  const dpi   = document.getElementById("dpi-select").value;

  const btn      = document.getElementById("generate-btn");
  const genProg  = document.getElementById("generate-progress");
  const genFill  = document.getElementById("gen-progress-fill");
  const genLabel = document.getElementById("progress-label");
  const resultSec= document.getElementById("result-section");
  const errBox   = document.getElementById("error-box");

  btn.disabled = true;
  genProg.classList.remove("hidden");
  genFill.style.width = "5%";
  genLabel.textContent = "Tasarımlar yükleniyor...";
  resultSec.classList.add("hidden");
  errBox.classList.add("hidden");
  setStep(4);

  // Start progress polling — updates bar while grade request is in flight
  let pollTimer = null;
  const startPolling = () => {
    pollTimer = setInterval(async () => {
      try {
        const prog = await apiFetch(`/session/${state.sessionId}/progress`);
        genFill.style.width = `${prog.pct}%`;
        genLabel.textContent = prog.msg || "İşleniyor...";
        if (prog.done) stopPolling();
      } catch (_) { /* ignore transient errors */ }
    }, 1200);
  };
  const stopPolling = () => { clearInterval(pollTimer); pollTimer = null; };

  try {
    await uploadDesigns();
    genFill.style.width = "8%";
    genLabel.textContent = `${selectedSizes.length} beden üretiliyor...`;

    startPolling();

    const rotStr = Object.entries(state.designRotations)
      .filter(([, deg]) => deg !== 0)
      .map(([t, deg]) => `${t}:${deg}`)
      .join(",");

    const fd = new FormData();
    fd.append("target_sizes", selectedSizes.join(","));
    fd.append("bleed_mm", bleed);
    fd.append("dpi", dpi);
    if (rotStr) fd.append("design_rotations", rotStr);
    const data = await apiFetch(`/session/${state.sessionId}/grade`, { method:"POST", body:fd });

    stopPolling();
    genFill.style.width = "100%";
    genLabel.textContent = `Tamamlandı: ${data.completed_sizes.length} beden`;
    renderResults(data);
    toast(`${data.completed_sizes.length} beden başarıyla üretildi!`, "success");
  } catch (err) {
    stopPolling();
    toast(`Hata: ${err.message}`, "error");
    errBox.textContent = `Hata: ${err.message}`;
    errBox.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    setTimeout(() => genProg.classList.add("hidden"), 1200);
  }
}

function renderResults(data) {
  const grid = document.getElementById("download-grid");
  grid.innerHTML = "";

  data.completed_sizes.forEach(size => {
    const a = document.createElement("a");
    a.href     = `${API}/session/${state.sessionId}/pdf/${size}`;
    a.download = `forma_${size}.pdf`;
    a.className = "download-card";
    a.innerHTML = `
      <div class="download-size">${size}</div>
      <svg viewBox="0 0 20 20" fill="currentColor" width="20" class="download-icon">
        <path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"/>
      </svg>
      <div class="download-label">PDF İndir</div>`;
    grid.appendChild(a);
  });

  // ZIP butonu
  const zipBtn = document.getElementById("zip-download-btn");
  if (data.completed_sizes.length > 1) {
    zipBtn.href = `${API}/session/${state.sessionId}/download-all`;
    zipBtn.classList.remove("hidden");
  }

  if (data.errors?.length) {
    const errBox = document.getElementById("error-box");
    errBox.innerHTML = "<b>Uyarılar:</b><br>" + data.errors.join("<br>");
    errBox.classList.remove("hidden");
  }

  // Başarısız bedenler için retry butonu
  if (data.failed_sizes?.length) {
    state.failedSizes = data.failed_sizes;
    const retryBox = document.getElementById("retry-box");
    if (retryBox) {
      retryBox.innerHTML = `
        <span>Başarısız: <strong>${data.failed_sizes.join(", ")}</strong></span>
        <button class="btn-secondary" id="retry-btn">↺ Yeniden Dene</button>`;
      retryBox.classList.remove("hidden");
      document.getElementById("retry-btn").addEventListener("click", () => {
        retryBox.classList.add("hidden");
        runGrading(state.failedSizes);
      });
    }
  }

  // SVG önizleme sekmeleri
  const tabs = document.getElementById("preview-tabs");
  tabs.innerHTML = "";
  data.completed_sizes.forEach((size, i) => {
    const btn = document.createElement("button");
    btn.className = "preview-tab" + (i===0?" active":"");
    btn.textContent = size;
    btn.addEventListener("click", () => {
      tabs.querySelectorAll(".preview-tab").forEach(t=>t.classList.remove("active"));
      btn.classList.add("active");
      loadSVGPreview(size);
    });
    tabs.appendChild(btn);
  });

  if (data.completed_sizes.length > 0) loadSVGPreview(data.completed_sizes[0]);
  document.getElementById("result-section").classList.remove("hidden");
}

function loadSVGPreview(size) {
  document.getElementById("svg-frame").src = `${API}/session/${state.sessionId}/svg/${size}`;
}
