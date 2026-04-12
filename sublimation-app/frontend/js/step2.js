import { state } from './state.js';
import { apiFetch } from './api.js';
import { toast, setStep } from './ui.js';
import { renderDesignSection } from './step3.js';

// ── Sabitler ──────────────────────────────────────────────────────────────────

export const PIECE_LABELS = {
  front:        { icon: "👕", label: "Ön Panel"   },
  back:         { icon: "🔄", label: "Arka Panel" },
  left_sleeve:  { icon: "💪", label: "Sol Kol"    },
  right_sleeve: { icon: "💪", label: "Sağ Kol"    },
  front_2:      { icon: "👕", label: "Ön Panel 2" },
  back_2:       { icon: "🔄", label: "Arka Panel 2"},
  sleeve_3:     { icon: "💪", label: "Kol 3"      },
  sleeve_4:     { icon: "💪", label: "Kol 4"      },
};

export const ASSIGN_OPTIONS = [
  { value: "skip",         label: "— Atla —"       },
  { value: "front",        label: "👕 Ön Panel"    },
  { value: "back",         label: "🔄 Arka Panel"  },
  { value: "left_sleeve",  label: "💪 Sol Kol"     },
  { value: "right_sleeve", label: "💪 Sağ Kol"     },
  { value: "front_2",      label: "👕 Ön Panel 2"  },
  { value: "back_2",       label: "🔄 Arka Panel 2"},
];

export const GRADING_SERIES = [
  { label: "— Tek beden (grading yok) —", sizes: null },
  { label: "XS · S · M · L · XL (5 beden)",         sizes: ["XS","S","M","L","XL"] },
  { label: "XS · S · M · L · XL · XXL (6 beden)",   sizes: ["XS","S","M","L","XL","XXL"] },
  { label: "34 · 36 · 38 · 40 · 42 · 44 (6 beden)", sizes: ["34","36","38","40","42","44"] },
  { label: "36 · 38 · 40 · 42 · 44 · 46 · 48 (7)",  sizes: ["36","38","40","42","44","46","48"] },
  { label: "34 · 36 · 38 · 40 · 42 · 44 · 46 · 48 (8)", sizes: ["34","36","38","40","42","44","46","48"] },
  { label: "38 · 40 · 42 · 44 · 46 · 48 · 50 · 52 (8)", sizes: ["38","40","42","44","46","48","50","52"] },
  { label: "34 → 56 (13 beden, step 2)",             sizes: ["34","36","38","40","42","44","46","48","50","52","54","56","58"] },
];

// ── Yardımcılar ───────────────────────────────────────────────────────────────

export function _defaultSizeNames(n) {
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

export function _smartAssignTypes(pieces) {
  const withRatio = pieces.map((p, idx) => {
    const bb = p.pdata.bbox;
    const ratio = bb ? Math.max(bb.w, bb.h) / (Math.min(bb.w, bb.h) || 1) : 1;
    return { ...p, idx, ratio };
  });

  const body   = withRatio.filter(p => p.ratio <= 1.5).sort((a, b) => (b.pdata.area_cm2 || 0) - (a.pdata.area_cm2 || 0));
  const sleeve = withRatio.filter(p => p.ratio >  1.5).sort((a, b) => (b.pdata.area_cm2 || 0) - (a.pdata.area_cm2 || 0));

  if (sleeve.length === 0 && body.length >= 4) {
    const candidates = body.splice(body.length - 2, 2);
    sleeve.push(...candidates);
  }

  const assign = {};
  const bodyTypes   = ["front", "back", "front_2", "back_2"];
  const sleeveTypes = ["left_sleeve", "right_sleeve"];

  body.forEach((p, i)   => { assign[p.idx] = bodyTypes[i]   || "skip"; });
  sleeve.forEach((p, i) => { assign[p.idx] = sleeveTypes[i] || "skip"; });

  return assign;
}

export function _buildThumbSVG(pdata, W, H) {
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

export function _updateCardStyle(card, assignValue) {
  card.classList.remove("psc-active", "psc-skipped");
  if (assignValue === "skip") {
    card.classList.add("psc-skipped");
  } else {
    card.classList.add("psc-active");
  }
}

export function _updatePiecePreviewFromSize(preview, sKey) {
  state.piecePreview = {};
  const group = preview[sKey] || {};
  for (const [ptype, pdata] of Object.entries(group)) {
    state.piecePreview[ptype] = pdata;
  }
}

// ── Graded mod beden tablosu ──────────────────────────────────────────────────

export function renderSizeTable(preview) {
  const wrap = document.getElementById("size-table-wrap");
  document.getElementById("piece-select-grid").innerHTML = "";

  const sizes = Object.keys(preview);

  state.sizeLabels = {};
  state.referenceSize = sizes[0];

  const PIECE_ICONS = { front: "👕", back: "🔄", left_sleeve: "💪", right_sleeve: "💪" };
  const PIECE_NAMES = { front: "Ön", back: "Arka", left_sleeve: "Sol Kol", right_sleeve: "Sağ Kol" };

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

    const displayValue = fromPlt ? sKey : (defaults?.[idx] ?? "");
    const placeholder  = fromPlt ? "" : "34, 36, M, L…";

    const piecesHtml = Object.entries(group).map(([ptype, pdata]) => {
      const cls = ptype.includes("sleeve") ? "sp-sleeve" : ptype === "back" ? "sp-back" : "sp-front";
      const optHtml = ["front","back","left_sleeve","right_sleeve"].map(t =>
        `<option value="${t}"${t===ptype?" selected":""}>${PIECE_NAMES[t]||t}</option>`
      ).join("");
      return `<span class="size-piece-badge ${cls}" style="display:inline-flex;align-items:center;gap:4px">
        ${PIECE_ICONS[ptype]||"▪"}
        <select class="ptype-select" data-size="${sKey}" data-old-type="${ptype}" style="font-size:.75rem;border:none;background:transparent;cursor:pointer">
          ${optHtml}
        </select>
        <span style="opacity:.6">${pdata.area_cm2}cm²</span>
      </span>`;
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

    state.sizeLabels[sKey] = displayValue;
  });

  html += `</tbody></table>
  <label class="option-label" style="font-size:.8rem;margin-top:8px;display:flex;gap:6px;align-items:center">
    <input type="checkbox" id="retype-all-sizes" checked>
    Değişikliği tüm bedenlere uygula
  </label>`;
  wrap.innerHTML = html;

  wrap.querySelectorAll(".size-name-input").forEach(inp => {
    inp.addEventListener("input", () => {
      state.sizeLabels[inp.dataset.key] = inp.value.trim();
    });
  });

  wrap.querySelectorAll(".ref-radio").forEach(radio => {
    radio.addEventListener("change", () => {
      wrap.querySelectorAll("tr").forEach(r => r.classList.remove("ref-row"));
      document.getElementById(`size-row-${radio.value}`)?.classList.add("ref-row");
      state.referenceSize = radio.value;
    });
  });

  // Parça tipi dropdown değişimi — event delegation
  wrap.addEventListener("change", async function(e) {
    const sel = e.target.closest(".ptype-select");
    if (!sel) return;
    const size = sel.dataset.size;
    const oldType = sel.dataset.oldType;
    const newType = sel.value;
    if (oldType === newType) return;
    const allSizes = document.getElementById("retype-all-sizes")?.checked ?? true;
    const fd = new FormData();
    fd.append("size", size);
    fd.append("old_type", oldType);
    fd.append("new_type", newType);
    fd.append("all_sizes", allSizes ? "true" : "false");
    try {
      const result = await apiFetch(`/session/${state.sessionId}/assign-piece-type`, { method: "POST", body: fd });
      sel.dataset.oldType = newType;
      toast(`Parça tipi güncellendi (${result.affected_sizes?.length || 1} beden)`, "success");
    } catch(err) {
      toast(`Hata: ${err.message}`, "error");
      sel.value = oldType;
    }
  });

  _updatePiecePreviewFromSize(preview, state.referenceSize);
}

// ── Flat mod parça seçim grid ─────────────────────────────────────────────────

export function renderPieceSelectGrid(preview) {
  const grid = document.getElementById("piece-select-grid");
  grid.innerHTML = "";
  state.pieceAssignments = {};

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

  allPieces.sort((a, b) => (b.pdata.area_cm2 || 0) - (a.pdata.area_cm2 || 0));

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

  state.piecePreview = {};
  for (const [size, pieces] of Object.entries(preview)) {
    for (const [ptype, pdata] of Object.entries(pieces)) {
      state.piecePreview[ptype] = pdata;
    }
  }

  _renderFlatGradingRow();
}

export function _renderFlatGradingRow() {
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

// ── Parçaları Onayla butonu ───────────────────────────────────────────────────

export function initStep2() {
  document.getElementById("confirm-pieces-btn").addEventListener("click", async () => {
    const btn = document.getElementById("confirm-pieces-btn");

    btn.disabled = true;
    btn.textContent = "Kaydediliyor...";

    if (state.pltMode === "graded") {
      const refRadio = document.querySelector('input[name="ref-size"]:checked');
      state.referenceSize = refRadio?.value || Object.keys(state.allPieces)[0];

      _updatePiecePreviewFromSize(state.allPieces, state.referenceSize);

      state.activePieceTypes = Object.keys(state.allPieces[state.referenceSize] || {});

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

    const sizeLabelEl = document.getElementById("size-label-input");
    state.sizeLabel = (sizeLabelEl?.value.trim() || "BASE").toUpperCase();

    const active = Object.entries(state.pieceAssignments)
      .filter(([, v]) => v !== "skip");

    if (!active.length) {
      toast("En az bir parça seçin", "error");
      btn.disabled = false;
      return;
    }

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

    state.activePieceTypes = [...new Set(active.map(([, v]) => v))];

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
}
