// ── UI Yardımcıları ───────────────────────────────────────────────────────────

export function setStep(n) {
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

export function toast(msg, type = "info") {
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

export function _pieceDisplayName(type) {
  const DISPLAY = {
    front: "Ön Panel", back: "Arka Panel",
    left_sleeve: "Sol Kol", right_sleeve: "Sağ Kol",
  };
  return DISPLAY[type] || type.replace(/_/g, " ");
}
