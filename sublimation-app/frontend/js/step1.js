import { state } from './state.js';
import { apiFetch, ensureSession } from './api.js';
import { toast, setStep } from './ui.js';
import { renderSizeTable } from './step2.js';
import { renderPieceSelectGrid } from './step2.js';

export function resetState() {
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

export function setPLTFile(f) {
  state.pltFile = f;
  document.getElementById("plt-filename").textContent = f.name;
  document.getElementById("plt-info").classList.remove("hidden");
}

export function initStep1() {
  const pltInput     = document.getElementById("plt-input");
  const pltDrop      = document.getElementById("plt-drop");
  const pltInfo      = document.getElementById("plt-info");
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
      state.sizeNamesFromPlt = data.size_names_from_plt || false;
      toast(`PLT analiz edildi — ${data.total_pieces} ham parça`, "success");

      const warn = document.getElementById("plt-warnings");
      if (data.warnings?.length) {
        warn.innerHTML = data.warnings.map(w => `<p>⚠ ${w}</p>`).join("");
        warn.classList.remove("hidden");
      } else {
        warn.classList.add("hidden");
      }

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

      const preview = await apiFetch(`/session/${state.sessionId}/preview`);
      state.allPieces = preview;

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
}
