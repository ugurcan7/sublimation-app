"use strict";

const API = "";

// ── Durum ─────────────────────────────────────────────────────────────────────
const state = {
  sessionId:       null,
  pltFile:         null,
  pltMode:         "flat",       // "flat" | "labeled"
  allPieces:       {},           // { size: { piece_type: pieceData } } — önizleme için
  // Kullanıcının seçimleri: { original_key: assigned_type }
  // assigned_type: "front"|"back"|"left_sleeve"|"right_sleeve"|"skip"
  pieceAssignments: {},
  activePieceTypes: [],          // atlanmayanlar, sıraya göre
  designFiles:     {},           // { piece_type: File }
  designRotations: {},
  designDataUrls:  {},
  piecePreview:    {},
  failedSizes:     [],
};

// ── Stepper ───────────────────────────────────────────────────────────────────
function setStep(n) {
  document.querySelectorAll(".step").forEach(el => {
    const s = parseInt(el.dataset.step);
    el.classList.remove("active", "done");
    if (s === n) el.classList.add("active");
    else if (s < n) el.classList.add("done");
  });
  for (let i = 2; i <= 4; i++) {
    const card = document.getElementById(`step-${i}`);
    if (!card) continue;
    if (n >= 2 && i <= n) card.classList.remove("disabled");
    else card.classList.add("disabled");
  }
}

// ── Toast ─────────────────────────────────────────────────────────────────────
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
  resetState();
  pltInput.value = "";
  pltInfo.classList.add("hidden");
  pltResult.classList.add("hidden");
  setStep(1);
});

function resetState() {
  state.pltFile = null;
  state.sessionId = null;
  state.allPieces = {};
  state.pieceAssignments = {};
  state.activePieceTypes = [];
  state.designFiles = {};
  state.designRotations = {};
  state.designDataUrls = {};
  state.piecePreview = {};
}

function setPLTFile(f) {
  state.pltFile = f;
  pltFilename.textContent = f.name;
  pltInfo.classList.remove("hidden");
}

pltUploadBtn.addEventListener("click", async e => {
  e.preventDefault();
  if (!state.pltFile) { toast("PLT dosyası seçilmedi", "error"); return; }
  pltUploadBtn.disabled = true;
  pltProgress.classList.remove("hidden");
  pltFill.style.width = "20%";
  try {
    state.sessionId = null;
    resetState();
    state.pltFile = pltInput.files[0] || state.pltFile;
    await ensureSession();
    pltFill.style.width = "50%";
    const fd = new FormData();
    fd.append("file", state.pltFile);
    const data = await apiFetch(`/session/${state.sessionId}/plt`, { method: "POST", body: fd });
    pltFill.style.width = "80%";

    state.pltMode = data.mode || "flat";
    toast(`PLT analiz edildi — ${data.total_pieces} ham parça`, "success");

    // Uyarılar
    const warn = document.getElementById("plt-warnings");
    if (data.warnings?.length) {
      warn.innerHTML = data.warnings.map(w => `<p>⚠ ${w}</p>`).join("");
      warn.classList.remove("hidden");
    } else {
      warn.classList.add("hidden");
    }

    // Özet satırı
    const summary = document.getElementById("result-summary");
    const pTypeCount = data.piece_types_found?.length || 0;
    summary.innerHTML = `
      <div class="result-stat"><span class="stat-num">${data.total_pieces}</span><span class="stat-lbl">Ham Parça</span></div>
      <div class="result-stat"><span class="stat-num">${pTypeCount}</span><span class="stat-lbl">Tespit Edilen Tip</span></div>
      <div class="result-stat mode-badge ${state.pltMode === 'flat' ? 'mode-manual' : 'mode-auto'}">
        ${state.pltMode === 'flat' ? '⚙ Manuel Seçim' : '✓ Otomatik'}
      </div>`;

    pltResult.classList.remove("hidden");
    pltFill.style.width = "100%";

    // Preview verisi yükle
    const preview = await apiFetch(`/session/${state.sessionId}/preview`);
    state.allPieces = preview;

    // Step 2: önce bölümü aç, sonra kartları doldur
    setStep(2);
    renderPieceSelectGrid(preview);
    document.getElementById("step-2").scrollIntoView({ behavior: "smooth", block: "start" });

  } catch (err) {
    const warnEl = document.getElementById("plt-warnings");
    warnEl.innerHTML = `<p>❌ ${err.message}</p>`;
    warnEl.classList.remove("hidden");
    toast(err.message, "error");
  } finally {
    pltUploadBtn.disabled = false;
    setTimeout(() => pltProgress.classList.add("hidden"), 600);
  }
});

// ── Step 2: Parça Seçim Grid ─────────────────────────────────────────────────

const PIECE_LABELS = {
  front:        { icon: "👕", label: "Ön Panel"   },
  back:         { icon: "🔄", label: "Arka Panel" },
  left_sleeve:  { icon: "💪", label: "Sol Kol"    },
  right_sleeve: { icon: "💪", label: "Sağ Kol"    },
  front_2:      { icon: "👕", label: "Ön Panel 2" },
  back_2:       { icon: "🔄", label: "Arka Panel 2"},
  sleeve_3:     { icon: "💪", label: "Kol 3"      },
  sleeve_4:     { icon: "💪", label: "Kol 4"      },
};

const ASSIGN_OPTIONS = [
  { value: "skip",         label: "— Atla —"      },
  { value: "front",        label: "👕 Ön Panel"   },
  { value: "back",         label: "🔄 Arka Panel" },
  { value: "left_sleeve",  label: "💪 Sol Kol"    },
  { value: "right_sleeve", label: "💪 Sağ Kol"    },
];

function renderPieceSelectGrid(preview) {
  const grid = document.getElementById("piece-select-grid");
  grid.innerHTML = "";
  state.pieceAssignments = {};

  // Tüm parçaları düzleştir
  const allPieces = [];
  for (const [size, pieces] of Object.entries(preview)) {
    for (const [ptype, pdata] of Object.entries(pieces)) {
      allPieces.push({ size, ptype, pdata });
    }
  }

  if (!allPieces.length) {
    grid.innerHTML = '<p style="color:var(--gray-500);font-size:.88rem">Gösterilecek parça bulunamadı.</p>';
    return;
  }

  // Alana göre sırala (büyük parçalar önce)
  allPieces.sort((a, b) => (b.pdata.area_cm2 || 0) - (a.pdata.area_cm2 || 0));

  allPieces.forEach(({ size, ptype, pdata }, idx) => {
    const key = `${size}__${ptype}`;
    // Varsayılan atama: ilk 4 parçaya ön/arka/sol kol/sağ kol
    const defaultAssign = ["front", "back", "left_sleeve", "right_sleeve"][idx] || "skip";
    state.pieceAssignments[key] = defaultAssign;

    const dimsText = pdata.bbox
      ? `${(pdata.bbox.w/10).toFixed(0)}×${(pdata.bbox.h/10).toFixed(0)} cm`
      : "";

    const card = document.createElement("div");
    card.className = "piece-select-card";
    card.dataset.key = key;

    const svgContent = _buildThumbSVG(pdata, 200, 130);
    const optHtml = ASSIGN_OPTIONS.map(o =>
      `<option value="${o.value}"${o.value === defaultAssign ? " selected" : ""}>${o.label}</option>`
    ).join("");

    card.innerHTML = `
      <div class="psc-thumb">
        <svg viewBox="0 0 200 130" xmlns="http://www.w3.org/2000/svg" class="psc-svg">${svgContent}</svg>
      </div>
      <div class="psc-footer">
        <div class="psc-info">
          <span class="psc-area">${pdata.area_cm2 || 0} cm²</span>
          <span class="psc-dims">${dimsText}</span>
        </div>
        <select class="psc-select" data-key="${key}">
          ${optHtml}
        </select>
      </div>`;

    grid.appendChild(card);
    _updateCardStyle(card, defaultAssign);

    card.querySelector(".psc-select").addEventListener("change", function() {
      state.pieceAssignments[this.dataset.key] = this.value;
      _updateCardStyle(card, this.value);
    });
  });

  // piecePreview doldurup sonraki adımda kullanmak için
  state.piecePreview = {};
  for (const [size, pieces] of Object.entries(preview)) {
    for (const [ptype, pdata] of Object.entries(pieces)) {
      state.piecePreview[ptype] = pdata;
    }
  }
}

function _updateCardStyle(card, assignValue) {
  card.classList.remove("psc-active", "psc-skipped");
  if (assignValue === "skip") {
    card.classList.add("psc-skipped");
  } else {
    card.classList.add("psc-active");
  }
}

function _buildThumbSVG(pdata, W, H) {
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
  return `<rect width="${W}" height="${H}" fill="#f8fafc"/>
          <polygon points="${poly}" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5" stroke-linejoin="round"/>`;
}

// Parçaları onayla butonu
document.getElementById("confirm-pieces-btn").addEventListener("click", async () => {
  const btn = document.getElementById("confirm-pieces-btn");

  // Atlanmayan parçaların listesi
  const active = Object.entries(state.pieceAssignments)
    .filter(([, v]) => v !== "skip");

  if (!active.length) {
    toast("En az bir parça seçin", "error"); return;
  }

  btn.disabled = true;
  btn.textContent = "Kaydediliyor...";

  // Backend'e yeni tip atamalarını gönder (sadece değişenler)
  try {
    for (const [key, newType] of active) {
      const [size, oldType] = key.split("__");
      if (oldType === newType) continue;
      const fd = new FormData();
      fd.append("size", size);
      fd.append("old_type", oldType);
      fd.append("new_type", newType);
      await apiFetch(`/session/${state.sessionId}/assign-piece-type`, { method: "POST", body: fd });
    }
  } catch (e) {
    console.warn("Atama hatası:", e.message);
  }

  // Aktif parça tiplerini kaydet
  state.activePieceTypes = [...new Set(active.map(([, v]) => v))];

  // Design section için önizleme verisi güncelle
  const newPreview = {};
  for (const [key, newType] of active) {
    const [, oldType] = key.split("__");
    if (state.piecePreview[oldType]) newPreview[newType] = state.piecePreview[oldType];
    else if (state.piecePreview[newType]) newPreview[newType] = state.piecePreview[newType];
  }
  state.piecePreview = newPreview;

  btn.disabled = false;
  btn.innerHTML = `Parçaları Onayla <svg viewBox="0 0 20 20" fill="currentColor" width="16"><path d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z"/></svg>`;

  setStep(3);
  renderDesignSection(state.activePieceTypes, newPreview);
  document.getElementById("step-3").scrollIntoView({ behavior: "smooth", block: "start" });
  toast(`${state.activePieceTypes.length} parça seçildi`, "success");
});

// ── Tasarım kartları ──────────────────────────────────────────────────────────

function _thumbSvgContent(type, pdata, imgSrc, deg) {
  const W = 200, H = 130;
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
    const tr = deg ? ` transform="rotate(${deg} ${cx} ${cy})"` : "";
    imgEl = `<g clip-path="url(#${clipId})">
      <image href="${imgSrc}" x="${ox.toFixed(1)}" y="${oy.toFixed(1)}"
             width="${dw.toFixed(1)}" height="${dh.toFixed(1)}"
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
  if (!types.length) return;

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
        <button type="button" class="btn-rotate hidden" id="rotate-${safeId}" data-type="${type}">
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

  // "Tümüne uygula"
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
    toast(`Tasarım 30MB'den büyük olamaz`, "error"); return;
  }
  state.designFiles[type] = file;
  if (!(type in state.designRotations)) state.designRotations[type] = 0;
  if (Object.keys(state.designFiles).length === 1) setStep(3);

  const safeId = `design-${type}`;
  const reader = new FileReader();
  reader.onload = ev => {
    state.designDataUrls[type] = ev.target.result;
    updateThumbDesign(type);
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
  state.designRotations[type] = ((state.designRotations[type] ?? 0) + 90) % 360;
  if (state.designDataUrls[type]) updateThumbDesign(type);
  const safeId = `design-${type}`;
  const degEl  = document.querySelector(`#rotate-${safeId} .rotate-deg`);
  if (degEl) degEl.textContent = `${state.designRotations[type]}°`;
}

function removeDesign(type) {
  delete state.designFiles[type];
  delete state.designRotations[type];
  delete state.designDataUrls[type];
  updateThumbDesign(type);
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

// ── Üretim ────────────────────────────────────────────────────────────────────
document.getElementById("generate-btn").addEventListener("click", () => runGrading());

async function runGrading() {
  if (!state.sessionId) {
    toast("Önce PLT dosyası yükleyin", "error"); return;
  }

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
  document.getElementById("step-4").scrollIntoView({ behavior: "smooth", block: "start" });

  let pollTimer = null;
  const startPolling = () => {
    pollTimer = setInterval(async () => {
      try {
        const prog = await apiFetch(`/session/${state.sessionId}/progress`);
        genFill.style.width = `${prog.pct}%`;
        genLabel.textContent = prog.msg || "İşleniyor...";
        if (prog.done) stopPolling();
      } catch (_) {}
    }, 1200);
  };
  const stopPolling = () => { clearInterval(pollTimer); pollTimer = null; };

  try {
    await uploadDesigns();
    genFill.style.width = "8%";
    genLabel.textContent = "Parçalar işleniyor...";
    startPolling();

    const rotStr = Object.entries(state.designRotations)
      .filter(([, deg]) => deg !== 0)
      .map(([t, deg]) => `${t}:${deg}`)
      .join(",");

    const fd = new FormData();
    // BASE modda target_sizes = "BASE", labeled modda tüm tespit edilen bedenler
    const targetSizes = state.pltMode === "flat" ? "BASE" :
      Object.keys(state.allPieces).join(",") || "BASE";
    fd.append("target_sizes", targetSizes);
    fd.append("bleed_mm", bleed);
    fd.append("dpi", dpi);
    if (rotStr) fd.append("design_rotations", rotStr);

    const data = await apiFetch(`/session/${state.sessionId}/grade`, { method:"POST", body:fd });
    stopPolling();
    genFill.style.width = "100%";
    genLabel.textContent = `Tamamlandı!`;
    renderResults(data);
    toast(`PDF hazır!`, "success");
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
    const label = size === "BASE" ? "PDF" : size;
    a.innerHTML = `
      <div class="download-size">${label}</div>
      <svg viewBox="0 0 20 20" fill="currentColor" width="20" class="download-icon">
        <path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"/>
      </svg>
      <div class="download-label">PDF İndir</div>`;
    grid.appendChild(a);
  });

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

  // SVG önizleme
  const tabs = document.getElementById("preview-tabs");
  tabs.innerHTML = "";
  data.completed_sizes.forEach((size, i) => {
    const btn = document.createElement("button");
    btn.className = "preview-tab" + (i===0?" active":"");
    btn.textContent = size === "BASE" ? "Önizleme" : size;
    btn.addEventListener("click", () => {
      tabs.querySelectorAll(".preview-tab").forEach(t=>t.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("svg-frame").src = `${API}/session/${state.sessionId}/svg/${size}`;
    });
    tabs.appendChild(btn);
  });

  if (data.completed_sizes.length > 0) {
    document.getElementById("svg-frame").src =
      `${API}/session/${state.sessionId}/svg/${data.completed_sizes[0]}`;
  }

  document.getElementById("result-section").classList.remove("hidden");
}
