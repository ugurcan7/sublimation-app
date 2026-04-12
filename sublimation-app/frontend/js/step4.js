import { state } from './state.js';
import { apiFetch } from './api.js';
import { API } from './api.js';
import { toast, setStep } from './ui.js';
import { uploadDesigns } from './step3.js';

export async function runGrading() {
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
      targetSizes = Object.keys(state.allPieces).join(",");
    } else if (state.flatGradingSizes?.length) {
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
    const txMap = {};
    for (const [t, tx] of Object.entries(state.designTransforms)) {
      if (tx.offsetX !== 0 || tx.offsetY !== 0 || tx.scale !== 1.0) {
        txMap[t] = [tx.offsetX, tx.offsetY, tx.scale];
      }
    }
    if (Object.keys(txMap).length) fd.append("design_transforms", JSON.stringify(txMap));
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

export function renderResults(data) {
  const grid = document.getElementById("download-grid");
  grid.innerHTML = "";

  data.completed_sizes.forEach(size => {
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

export function initStep4() {
  document.getElementById("generate-btn").addEventListener("click", () => runGrading());
}
