"use strict";

const API = "";

// ── Durum ─────────────────────────────────────────────────────────────────────
const state = {
  sessionId:        null,
  pltFile:          null,
  pltMode:          "flat",       // "flat" | "labeled"
  sizeLabel:        "",           // kullanıcının girdiği beden etiketi (M, L, 42 vs.)
  flatGradingSizes: null,         // flat grading serisi: ["34","36",...] veya null (tek beden)
  allPieces:        {},
  pieceAssignments: {},
  activePieceTypes: [],
  designFiles:      {},
  designRotations:  {},
  designTransforms: {},   // { type: { offsetX, offsetY, scale } }
  designDataUrls:   {},
  piecePreview:     {},
  failedSizes:      [],
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
  state.designTransforms = {};
  state.designDataUrls = {};
  state.piecePreview = {};
  state.sizeLabel = "";
  state.sizeLabels = {};
  state.referenceSize = null;
  state.sizeNamesFromPlt = false;
  state.flatGradingSizes = null;
  document.getElementById("size-table-wrap").innerHTML = "";
  document.getElementById("piece-select-grid").innerHTML = "";
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
    state.sizeNamesFromPlt = data.size_names_from_plt || false;  // PLT'den gerçek isim geldi mi?
    toast(`PLT analiz edildi — ${data.total_pieces} ham parça`, "success");

    // Uyarılar
    const warn = document.getElementById("plt-warnings");
    if (data.warnings?.length) {
      warn.innerHTML = data.warnings.map(w => `<p>⚠ ${w}</p>`).join("");
      warn.classList.remove("hidden");
    } else {
      warn.classList.add("hidden");
    }

    // Özet
    const summary = document.getElementById("result-summary");
    const nSizes = data.detected_sizes?.length || 0;
    summary.innerHTML = `
      <div class="result-stat"><span class="stat-num">${data.total_pieces}</span><span class="stat-lbl">Ham Parça</span></div>
      <div class="result-stat"><span class="stat-num">${nSizes}</span><span class="stat-lbl">Beden</span></div>
      <div class="result-stat mode-badge ${state.pltMode === 'graded' ? 'mode-auto' : 'mode-manual'}">
        ${state.pltMode === 'graded' ? `✓ ${nSizes} Beden Tespit` : '⚙ Tek Beden'}
      </div>`;

    pltResult.classList.remove("hidden");
    pltFill.style.width = "100%";

    // Preview verisi yükle
    const preview = await apiFetch(`/session/${state.sessionId}/preview`);
    state.allPieces = preview;

    // Step 2
    setStep(2);
    if (state.pltMode === "graded") {
      renderSizeTable(preview);
    } else {
      renderPieceSelectGrid(preview);
    }
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

// ── Step 2: Beden Tablosu (Graded Mod) ──────────────────────────────────────

/** Beden sayısına göre standart seri öner */
function _defaultSizeNames(n) {
  const series = {
    1:  ["M"],
    2:  ["M","L"],
    3:  ["S","M","L"],
    4:  ["S","M","L","XL"],
    5:  ["XS","S","M","L","XL"],
    6:  ["XS","S","M","L","XL","XXL"],
    7:  ["XXS","XS","S","M","L","XL","XXL"],
    8:  ["XXS","XS","S","M","L","XL","XXL","3XL"],
    9:  ["XXS","XS","S","M","L","XL","XXL","3XL","4XL"],
    10: ["32","34","36","38","40","42","44","46","48","50"],
    11: ["32","34","36","38","40","42","44","46","48","50","52"],
    12: ["32","34","36","38","40","42","44","46","48","50","52","54"],
    13: ["34","36","38","40","42","44","46","48","50","52","54","56","58"],
    14: ["32","34","36","38","40","42","44","46","48","50","52","54","56","58"],
  };
  return series[n] || Array.from({length: n}, (_, i) => String(i + 1));
}

function renderSizeTable(preview) {
  const wrap = document.getElementById("size-table-wrap");
  document.getElementById("piece-select-grid").innerHTML = "";

  const sizes = Object.keys(preview); // S1, S2, ... veya M, L, XL, ...

  state.sizeLabels = {};
  state.referenceSize = sizes[0];

  const PIECE_ICONS = { front: "👕", back: "🔄", left_sleeve: "💪", right_sleeve: "💪" };
  const PIECE_NAMES = { front: "Ön", back: "Arka", left_sleeve: "Sol Kol", right_sleeve: "Sağ Kol" };

  // PLT'den gerçek isimler geldiyse → sKey zaten gerçek isim
  // Gelmemişse → standart seri öner (düzenlenebilir)
  const fromPlt = state.sizeNamesFromPlt;
  const defaults = fromPlt ? null : _defaultSizeNames(sizes.length);

  let html = `
    <table class="size-table">
      <thead>
        <tr>
          <th>Referans</th>
          <th>Beden Adı ${fromPlt ? '<span class="plt-tag">PLT\'den</span>' : ''}</th>
          <th>Parçalar (alan cm²)</th>
        </tr>
      </thead>
      <tbody>`;

  sizes.forEach((sKey, idx) => {
    const group = preview[sKey];
    const isRef = idx === 0;

    // Görüntülenecek isim:
    //   - PLT'den geldiyse → sKey zaten gerçek isim (M, L, 38, ...)
    //   - Gelmediyse → standart seri öner (düzenlenebilir)
    const displayValue = fromPlt ? sKey : (defaults?.[idx] ?? "");
    const placeholder  = fromPlt ? "" : "34, 36, M, L…";

    const piecesHtml = Object.entries(group).map(([ptype, pdata]) => {
      const cls = ptype.includes("sleeve") ? "sp-sleeve" : ptype === "back" ? "sp-back" : "sp-front";
      return `<span class="size-piece-badge ${cls}">${PIECE_ICONS[ptype] || "▪"} ${PIECE_NAMES[ptype] || ptype} ${pdata.area_cm2}cm²</span>`;
    }).join("");

    html += `
      <tr class="${isRef ? "ref-row" : ""}" id="size-row-${sKey}">
        <td style="text-align:center">
          <input type="radio" class="ref-radio" name="ref-size" value="${sKey}" ${isRef ? "checked" : ""}>
        </td>
        <td>
          <input type="text" class="size-name-input" data-key="${sKey}"
                 value="${displayValue}" placeholder="${placeholder}">
        </td>
        <td><div class="size-pieces-row">${piecesHtml}</div></td>
      </tr>`;

    // sizeLabels'a başlangıç değeri yaz
    state.sizeLabels[sKey] = displayValue;
  });

  html += "</tbody></table>";
  wrap.innerHTML = html;

  // Beden adı input değişince state güncelle
  wrap.querySelectorAll(".size-name-input").forEach(inp => {
    inp.addEventListener("input", () => {
      state.sizeLabels[inp.dataset.key] = inp.value.trim();
    });
  });

  // Referans seçimi değişince satırı vurgula
  wrap.querySelectorAll(".ref-radio").forEach(radio => {
    radio.addEventListener("change", () => {
      wrap.querySelectorAll("tr").forEach(r => r.classList.remove("ref-row"));
      document.getElementById(`size-row-${radio.value}`)?.classList.add("ref-row");
      state.referenceSize = radio.value;
    });
  });

  _updatePiecePreviewFromSize(preview, state.referenceSize);
}

function _updatePiecePreviewFromSize(preview, sKey) {
  state.piecePreview = {};
  const group = preview[sKey] || {};
  for (const [ptype, pdata] of Object.entries(group)) {
    state.piecePreview[ptype] = pdata;
  }
}

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
  { value: "skip",         label: "— Atla —"       },
  { value: "front",        label: "👕 Ön Panel"    },
  { value: "back",         label: "🔄 Arka Panel"  },
  { value: "left_sleeve",  label: "💪 Sol Kol"     },
  { value: "right_sleeve", label: "💪 Sağ Kol"     },
  { value: "front_2",      label: "👕 Ön Panel 2"  },
  { value: "back_2",       label: "🔄 Arka Panel 2"},
];

// Parça şekline göre akıllı tip tahmini
// Kollar tipik olarak dikdörtgen ve uzun (ratio > 1.5), gövde parçaları daha kare
function _smartAssignTypes(pieces) {
  // Her parça için uzunluk/genişlik oranını hesapla
  const withRatio = pieces.map((p, idx) => {
    const bb = p.pdata.bbox;
    const ratio = bb ? Math.max(bb.w, bb.h) / (Math.min(bb.w, bb.h) || 1) : 1;
    return { ...p, idx, ratio };
  });

  // Kol adayı: oran > 1.5 VEYA alan küçük ama uzunsa
  // Gövde adayı: oran <= 1.5 (daha kareye yakın)
  const body   = withRatio.filter(p => p.ratio <= 1.5).sort((a, b) => (b.pdata.area_cm2 || 0) - (a.pdata.area_cm2 || 0));
  const sleeve = withRatio.filter(p => p.ratio >  1.5).sort((a, b) => (b.pdata.area_cm2 || 0) - (a.pdata.area_cm2 || 0));

  // Kol yoksa en küçük iki gövde parçasını kol say
  if (sleeve.length === 0 && body.length >= 4) {
    const candidates = body.splice(body.length - 2, 2);
    sleeve.push(...candidates);
  }

  const assign = {};
  const bodyTypes   = ["front", "back", "front_2", "back_2"];
  const sleeveTypes = ["left_sleeve", "right_sleeve"];

  body.forEach((p, i)   => { assign[p.idx] = bodyTypes[i]   || "skip"; });
  sleeve.forEach((p, i) => { assign[p.idx] = sleeveTypes[i] || "skip"; });

  return assign; // { idx → type }
}

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

  // Şekil + alan bazlı akıllı tip tahmini
  const smartAssign = _smartAssignTypes(allPieces);

  allPieces.forEach(({ size, ptype, pdata }, idx) => {
    const key = `${size}__${ptype}`;
    const defaultAssign = smartAssign[idx] || "skip";
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

  // Flat grading serisi seçici
  _renderFlatGradingRow();
}

const GRADING_SERIES = [
  { label: "— Tek beden (grading yok) —", sizes: null },
  { label: "XS · S · M · L · XL (5 beden)",         sizes: ["XS","S","M","L","XL"] },
  { label: "XS · S · M · L · XL · XXL (6 beden)",   sizes: ["XS","S","M","L","XL","XXL"] },
  { label: "34 · 36 · 38 · 40 · 42 · 44 (6 beden)", sizes: ["34","36","38","40","42","44"] },
  { label: "36 · 38 · 40 · 42 · 44 · 46 · 48 (7)",  sizes: ["36","38","40","42","44","46","48"] },
  { label: "34 · 36 · 38 · 40 · 42 · 44 · 46 · 48 (8)", sizes: ["34","36","38","40","42","44","46","48"] },
  { label: "38 · 40 · 42 · 44 · 46 · 48 · 50 · 52 (8)", sizes: ["38","40","42","44","46","48","50","52"] },
  { label: "34 → 56 (13 beden, step 2)",             sizes: ["34","36","38","40","42","44","46","48","50","52","54","56","58"] },
];

function _renderFlatGradingRow() {
  // Varsa öncekini kaldır
  document.getElementById("flat-grading-row")?.remove();

  const wrap = document.getElementById("piece-select-grid");
  if (!wrap) return;

  const row = document.createElement("div");
  row.id = "flat-grading-row";
  row.className = "option-row flat-grading-row";
  row.innerHTML = `
    <label class="option-label" style="flex:1;min-width:220px">
      <span style="font-weight:600;display:block;margin-bottom:4px">Grading Serisi</span>
      <select id="grading-series-select" class="select-field" style="width:100%">
        ${GRADING_SERIES.map((s, i) => `<option value="${i}">${s.label}</option>`).join("")}
      </select>
    </label>
    <div class="grading-extra hidden" id="grading-extra" style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
      <label class="option-label">
        <span style="font-size:.78rem">Yüklenen beden</span>
        <input type="text" id="size-label-input" class="select-field" placeholder="M, L, 42…" style="width:80px">
      </label>
      <label class="option-label">
        <span style="font-size:.78rem">Genişlik adımı</span>
        <input type="number" id="width-step-input" class="select-field" value="4" min="1" max="20" step="0.5" style="width:72px"> mm
      </label>
      <label class="option-label">
        <span style="font-size:.78rem">Yükseklik adımı</span>
        <input type="number" id="height-step-input" class="select-field" value="2" min="0.5" max="10" step="0.5" style="width:72px"> mm
      </label>
    </div>`;

  wrap.after(row);

  document.getElementById("grading-series-select").addEventListener("change", function() {
    const idx = parseInt(this.value);
    state.flatGradingSizes = GRADING_SERIES[idx].sizes;
    const extra = document.getElementById("grading-extra");
    if (state.flatGradingSizes) {
      extra.classList.remove("hidden");
      extra.style.display = "flex";
    } else {
      extra.classList.add("hidden");
    }
  });
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

  btn.disabled = true;
  btn.textContent = "Kaydediliyor...";

  // ── Graded Mod ──
  if (state.pltMode === "graded") {
    // Referans beden seçimi
    const refRadio = document.querySelector('input[name="ref-size"]:checked');
    state.referenceSize = refRadio?.value || Object.keys(state.allPieces)[0];

    // Referans bedenin parçalarını piecePreview'a yaz
    _updatePiecePreviewFromSize(state.allPieces, state.referenceSize);

    // Aktif parça tipleri: referans bedendeki parçalar
    state.activePieceTypes = Object.keys(state.allPieces[state.referenceSize] || {});

    // Beden isim eşlemesini kaydet
    document.querySelectorAll(".size-name-input").forEach(inp => {
      state.sizeLabels[inp.dataset.key] = inp.value.trim() || inp.dataset.key;
    });

    btn.disabled = false;
    btn.innerHTML = `Onayla &amp; Devam <svg viewBox="0 0 20 20" fill="currentColor" width="16"><path d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z"/></svg>`;
    setStep(3);
    renderDesignSection(state.activePieceTypes, state.piecePreview);
    document.getElementById("step-3").scrollIntoView({ behavior: "smooth", block: "start" });
    toast(`Referans beden: ${state.sizeLabels[state.referenceSize] || state.referenceSize} — ${state.activePieceTypes.length} parça`, "success");
    return;
  }

  // ── Flat Mod ──
  // Beden etiketini kaydet
  const sizeLabelEl = document.getElementById("size-label-input");
  state.sizeLabel = (sizeLabelEl?.value.trim() || "BASE").toUpperCase();

  // Atlanmayan parçaların listesi
  const active = Object.entries(state.pieceAssignments)
    .filter(([, v]) => v !== "skip");

  if (!active.length) {
    toast("En az bir parça seçin", "error");
    btn.disabled = false;
    return;
  }

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

function updateThumbDesign(type) {
  const safeId = `design-${type}`;
  const svgEl  = document.getElementById(`thumb-${safeId}`);
  if (!svgEl) return;
  const pdata  = state.piecePreview[type];
  const imgSrc = state.designDataUrls[type] || null;
  const deg    = state.designRotations[type] ?? 0;
  svgEl.innerHTML = _thumbSvgContent(type, pdata, imgSrc, deg);
  // dw/dh'yi SVG element'e yaz (drag hesabı için)
  if (pdata?.bbox) {
    const W = 200, H = 130, pad = 10;
    const scale = Math.min((W - 2*pad) / pdata.bbox.w, (H - 2*pad) / pdata.bbox.h);
    svgEl.dataset.dw = (pdata.bbox.w * scale).toFixed(2);
    svgEl.dataset.dh = (pdata.bbox.h * scale).toFixed(2);
  }
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

function renderDesignSection(types, previewData) {
  const grid = document.getElementById("design-grid");
  grid.innerHTML = "";
  if (!types.length) return;

  // ── Graded mod: referans beden banner + uyarla butonu ──
  const banner     = document.getElementById("ref-size-banner");
  const adaptRow   = document.getElementById("adapt-btn-row");
  const step3Desc  = document.getElementById("step3-desc");

  if (state.pltMode === "graded") {
    const totalSizes = Object.keys(state.allPieces).length;

    // Dropdown: tüm beden seçenekleri
    const sel = document.getElementById("ref-size-select-step3");
    if (sel) {
      sel.innerHTML = Object.keys(state.allPieces).map(sKey => {
        const lbl = state.sizeLabels?.[sKey] || sKey;
        return `<option value="${sKey}" ${sKey === state.referenceSize ? "selected" : ""}>${lbl}</option>`;
      }).join("");

      sel.onchange = () => {
        state.referenceSize = sel.value;
        _updatePiecePreviewFromSize(state.allPieces, state.referenceSize);
        const hint = document.getElementById("ref-size-hint-text");
        if (hint) hint.textContent =
          `${state.sizeLabels?.[state.referenceSize] || state.referenceSize} — diğer ${totalSizes - 1} beden otomatik ölçeklendirilecek`;
        // Parça önizlemelerini de güncelle
        renderDesignSection(Object.keys(state.allPieces[state.referenceSize] || {}), state.piecePreview);
      };
    }

    const hint = document.getElementById("ref-size-hint-text");
    if (hint) hint.textContent =
      `${state.sizeLabels?.[state.referenceSize] || state.referenceSize} — diğer ${totalSizes - 1} beden otomatik ölçeklendirilecek`;

    banner?.classList.remove("hidden");

    // Adapt butonu
    if (adaptRow) {
      adaptRow.classList.remove("hidden");
      const adaptBtnText = document.getElementById("adapt-btn-text");
      if (adaptBtnText) adaptBtnText.textContent =
        `Tüm ${totalSizes} Bedene Uyarla & PDF Üret`;
      _refreshAdaptBtn();

      // Butona tıklayınca direkt grading başlat
      const adaptBtn = document.getElementById("adapt-btn");
      adaptBtn?.removeEventListener("click", runGrading);
      adaptBtn?.addEventListener("click", runGrading);
    }

    // Step 3 açıklama güncelle
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

    // Sürükle-bırak konum kontrolü
    const svgThumb = card.querySelector(".piece-thumb-svg");
    _initDragTransform(svgThumb, type);

    // Scale slider
    const scaleSlider = card.querySelector(".tx-slider");
    scaleSlider.addEventListener("input", function() {
      if (!state.designTransforms[type]) state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
      state.designTransforms[type].scale = parseFloat(this.value);
      document.getElementById(`scale-val-${safeId}`).textContent = parseFloat(this.value).toFixed(2) + "×";
      updateThumbDesign(type);
    });

    // Reset butonu
    card.querySelector(".btn-tx-reset").addEventListener("click", e => {
      e.stopPropagation();
      state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
      scaleSlider.value = "1.0";
      document.getElementById(`scale-val-${safeId}`).textContent = "1.0×";
      updateThumbDesign(type);
    });
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
    // Transform sıfırla (yeni yükleme)
    if (!state.designTransforms[type]) {
      state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
    }
    updateThumbDesign(type);
    document.getElementById(`hint-${safeId}`)?.classList.add("hidden");
    document.getElementById(`remove-${safeId}`)?.classList.remove("hidden");
    document.getElementById(`txctrls-${safeId}`)?.classList.remove("hidden");
    // SVG'ye "grab" cursor ver
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

// Sürükleme ile desen konumlandırma
function _initDragTransform(svgEl, type) {
  if (!svgEl) return;
  let dragging = false;
  let startClientX, startClientY, startOffX, startOffY;

  // Parça boyutlarını veri attribute'tan al (updateThumbDesign'de set edilir)
  const getDims = () => ({
    dw: parseFloat(svgEl.dataset.dw) || 100,
    dh: parseFloat(svgEl.dataset.dh) || 80,
  });

  svgEl.addEventListener("mousedown", e => {
    if (!state.designDataUrls[type]) return; // tasarım yoksa sürükleme yok
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
    const vbW   = 200;  // SVG viewBox genişliği
    const domW  = rect.width;
    const { dw, dh } = getDims();
    // DOM piksel delta → SVG koordinat → parça birimi
    const dxSvg = (e.clientX - startClientX) * (vbW / domW);
    const dySvg = (e.clientY - startClientY) * (vbW / domW); // kare viewbox
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

  // Touch desteği
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
    const dxSvg = (t.clientX - startClientX) * (200 / rect.width);
    const dySvg = (t.clientY - startClientY) * (200 / rect.width);
    if (!state.designTransforms[type]) state.designTransforms[type] = { offsetX: 0, offsetY: 0, scale: 1.0 };
    state.designTransforms[type].offsetX = startOffX + dxSvg / dw;
    state.designTransforms[type].offsetY = startOffY + dySvg / dh;
    updateThumbDesign(type);
  }, { passive: false });

  svgEl.addEventListener("touchend", () => { dragging = false; });
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
    let targetSizes;
    if (state.pltMode === "graded") {
      // Graded: tüm bedenleri gönder (S1, S2, ...)
      targetSizes = Object.keys(state.allPieces).join(",");
    } else if (state.flatGradingSizes?.length) {
      // Flat grading serisi seçildi
      targetSizes = state.flatGradingSizes.join(",");
    } else {
      targetSizes = state.sizeLabel || "BASE";
    }
    fd.append("target_sizes", targetSizes);
    fd.append("bleed_mm", bleed);
    fd.append("dpi", dpi);
    if (state.pltMode === "graded" && state.referenceSize) {
      fd.append("reference_size", state.referenceSize);
    }
    if (state.sizeLabel && state.sizeLabel !== "BASE") fd.append("size_label", state.sizeLabel);
    if (rotStr) fd.append("design_rotations", rotStr);
    // Desen transform'ları (konum + ölçek)
    const txMap = {};
    for (const [t, tx] of Object.entries(state.designTransforms)) {
      if (tx.offsetX !== 0 || tx.offsetY !== 0 || tx.scale !== 1.0) {
        txMap[t] = [tx.offsetX, tx.offsetY, tx.scale];
      }
    }
    if (Object.keys(txMap).length) fd.append("design_transforms", JSON.stringify(txMap));
    // Flat grading adım büyüklükleri
    if (state.flatGradingSizes?.length) {
      const ws = parseFloat(document.getElementById("width-step-input")?.value || "4");
      const hs = parseFloat(document.getElementById("height-step-input")?.value || "2");
      fd.append("width_step_mm",  isNaN(ws) ? "4" : String(ws));
      fd.append("height_step_mm", isNaN(hs) ? "2" : String(hs));
    }

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
    // Kullanıcının girdiği beden adını kullan (yoksa internal key)
    const userLabel = (state.sizeLabels?.[size] || "").trim() || (size === "BASE" ? "PDF" : size);
    const a = document.createElement("a");
    a.href     = `${API}/session/${state.sessionId}/pdf/${size}`;
    a.download = `forma_${userLabel}.pdf`;
    a.className = "download-card";
    a.innerHTML = `
      <div class="download-size">${userLabel}</div>
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

// ── Önizleme Modalı ───────────────────────────────────────────────────────────

function openPreviewModal(type, pdata) {
  // Varsa öncekini kaldır
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

function _pieceDisplayName(type) {
  const DISPLAY = {
    front: "Ön Panel", back: "Arka Panel",
    left_sleeve: "Sol Kol", right_sleeve: "Sağ Kol",
  };
  return DISPLAY[type] || type.replace(/_/g, " ");
}
