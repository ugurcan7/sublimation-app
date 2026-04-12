// ── Uygulama Durumu ───────────────────────────────────────────────────────────
export const state = {
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
  sizeLabels:       {},
  referenceSize:    null,
  sizeNamesFromPlt: false,
};
