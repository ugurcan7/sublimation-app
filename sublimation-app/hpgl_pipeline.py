"""
HPGL/PLT Robust Pipeline
========================
Standalone — no FastAPI dependency. Run directly:

    python hpgl_pipeline.py demo_pastal.plt

Outputs:
    cleaned_polygons.json
    debug_polygons.svg

Pipeline stages:
    1. Parse HPGL pen commands → raw paths
    2. Auto-detect coordinate scale
    3. Close open paths (if gap < tolerance)
    4. Filter noise (< 1% of max area)
    5. Validate / repair with Shapely
    6. Sort by area DESC
    7. Compute bounding boxes + normalized coords
    8. Emit JSON + debug SVG
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
log = logging.getLogger("hpgl_pipeline")

# ─── Constants ────────────────────────────────────────────────────────────────

HPGL_UNITS_PER_MM = 40.0          # standard: 1 plotter unit = 0.025 mm
MIN_POINTS        = 4              # fewer points → not a polygon
CLOSE_TOL_MM      = 2.0           # auto-close gap tolerance (mm)
NOISE_RATIO       = 0.01           # discard if area < 1% of max

# Debug SVG palette (cycles if > 12 pieces)
_PALETTE = [
    "#2563eb", "#7c3aed", "#059669", "#d97706",
    "#dc2626", "#0891b2", "#65a30d", "#9333ea",
    "#db2777", "#ea580c", "#16a34a", "#1d4ed8",
]


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — HPGL TOKENIZER
# ═══════════════════════════════════════════════════════════════════════════════

def tokenize(text: str) -> List[str]:
    """
    Split HPGL text into command tokens.

    Rules:
    - Normal commands end at ';' or newline
    - LB (label) ends at:
        * actual ETX byte (\\x03)
        * literal backslash-003 sequence (\\003)
        * newline (fallback for files that use newline-terminated labels)
    """
    # Normalise: replace literal \\003 with actual ETX so one code path handles both
    text = text.replace("\\003", "\x03")

    tokens: List[str] = []
    buf = ""
    i = 0
    while i < len(text):
        ch = text[i]
        # Inside an LB command — collect until ETX or newline
        if buf.upper().startswith("LB"):
            if ch in ("\x03", "\n"):
                tokens.append(buf.strip())
                buf = ""
            else:
                buf += ch
        elif ch in (";", "\n"):
            t = buf.strip()
            if t:
                tokens.append(t)
            buf = ""
        else:
            buf += ch
        i += 1
    if buf.strip():
        tokens.append(buf.strip())
    return tokens


def parse_coords(text: str) -> List[Tuple[float, float]]:
    """Extract (x, y) pairs from a coordinate string."""
    nums = re.findall(r"[-+]?\d*\.?\d+", text)
    pairs: List[Tuple[float, float]] = []
    for k in range(0, len(nums) - 1, 2):
        try:
            pairs.append((float(nums[k]), float(nums[k + 1])))
        except ValueError:
            pass
    return pairs


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — HPGL STATE MACHINE → RAW PATHS
# ═══════════════════════════════════════════════════════════════════════════════

class _HPGLMachine:
    """
    Interprets HPGL token stream and emits raw paths.

    Supported commands: IN SP PU PD PA PR LB
    Ignored (no geometry): VS SC SI DI DR SR SL TD RO CO
    """

    def __init__(self) -> None:
        self._cx = 0.0
        self._cy = 0.0
        self._pen_down = False
        self._cur: List[Tuple[float, float]] = []
        self._pending_label = ""
        # Each entry: (points_list, label_str)
        self.raw_paths: List[Tuple[List[Tuple[float, float]], str]] = []

    def feed(self, tokens: List[str]) -> None:
        for tok in tokens:
            if not tok:
                continue
            cmd = tok[:2].upper()

            if cmd in ("IN",):
                self._flush()

            elif cmd == "SP":
                self._flush()

            elif cmd == "PU":
                # Pen up always ends current path
                self._flush()
                self._pen_down = False
                coords = parse_coords(tok[2:])
                if coords:
                    self._cx, self._cy = coords[-1]

            elif cmd == "PD":
                coords = parse_coords(tok[2:])
                if coords:
                    if not self._cur:
                        self._cur.append((self._cx, self._cy))
                    for x, y in coords:
                        self._cx, self._cy = x, y
                        self._cur.append((x, y))
                self._pen_down = True

            elif cmd == "PA":
                coords = parse_coords(tok[2:])
                if coords:
                    if self._pen_down:
                        if not self._cur:
                            self._cur.append((self._cx, self._cy))
                        for x, y in coords:
                            self._cx, self._cy = x, y
                            self._cur.append((x, y))
                    else:
                        self._flush()
                        self._cx, self._cy = coords[-1]

            elif cmd == "PR":
                coords = parse_coords(tok[2:])
                if coords:
                    if self._pen_down and not self._cur:
                        self._cur.append((self._cx, self._cy))
                    for dx, dy in coords:
                        self._cx += dx
                        self._cy += dy
                        if self._pen_down:
                            self._cur.append((self._cx, self._cy))

            elif cmd == "LB":
                label = re.sub(r"\\003|\x03", "", tok[2:]).strip()
                self._pending_label = label
                # Label arrived AFTER path was flushed → attach to last path
                if self.raw_paths and not self._cur:
                    pts, _ = self.raw_paths[-1]
                    self.raw_paths[-1] = (pts, label)
                    self._pending_label = ""

        # Flush any remaining path at EOF
        self._flush()

    def _flush(self) -> None:
        pts = self._cur
        self._cur = []
        if len(pts) < MIN_POINTS:
            return
        # Deduplicate consecutive identical points
        deduped: List[Tuple[float, float]] = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - deduped[-1][0]) > 0.5 or abs(p[1] - deduped[-1][1]) > 0.5:
                deduped.append(p)
        if len(deduped) >= MIN_POINTS:
            self.raw_paths.append((deduped, self._pending_label))
            self._pending_label = ""


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — COORDINATE SCALE AUTO-DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_scale(raw_paths: List[Tuple[List[Tuple[float, float]], str]]) -> float:
    """
    Heuristic: inspect coordinate range to pick the right unit/mm factor.

    Typical jersey pastal (5 sizes) in standard HPGL:
        range ≈ 100 000 – 200 000 units  →  40 units/mm

    Micro-scale (some CUT files):
        range < 5 000                    →  1 unit/mm

    High-resolution HPGL:
        range > 1 000 000                →  400 units/mm
    """
    all_pts = [p for pts, _ in raw_paths for p in pts]
    if not all_pts:
        return HPGL_UNITS_PER_MM

    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    coord_range = max(max(xs) - min(xs), max(ys) - min(ys))

    if coord_range < 5_000:
        scale = 1.0
        reason = "1 unit/mm (micro-scale)"
    elif coord_range < 1_000_000:
        scale = HPGL_UNITS_PER_MM
        reason = f"40 unit/mm (standard HPGL, range={coord_range:.0f})"
    else:
        scale = HPGL_UNITS_PER_MM * 10
        reason = f"400 unit/mm (hi-res, range={coord_range:.0f})"

    log.info(f"Scale detected: {reason}")
    return scale


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — PATH → CLOSED POLYGON
# ═══════════════════════════════════════════════════════════════════════════════

def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def try_close(pts_mm: List[Tuple[float, float]], tol_mm: float = CLOSE_TOL_MM
              ) -> Optional[List[Tuple[float, float]]]:
    """
    Attempt to close a path:
    - Already closed (first ≈ last)  → remove duplicate tail, return
    - Gap < tol_mm                   → append first point, return
    - Gap ≥ tol_mm                   → return None (discard)
    """
    if len(pts_mm) < MIN_POINTS:
        return None

    gap = _dist(pts_mm[0], pts_mm[-1])

    if gap < 0.01:
        # Already closed — drop duplicate tail
        return pts_mm[:-1]

    if gap < tol_mm:
        return pts_mm + [pts_mm[0]]

    # Not closable
    log.debug(f"  Path discarded: gap={gap:.1f}mm > tol={tol_mm}mm")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — AREA + NOISE FILTER
# ═══════════════════════════════════════════════════════════════════════════════

def shoelace_area(pts: List[Tuple[float, float]]) -> float:
    """Signed shoelace formula → always return positive."""
    n = len(pts)
    s = 0.0
    for i in range(n):
        j = (i + 1) % n
        s += pts[i][0] * pts[j][1]
        s -= pts[j][0] * pts[i][1]
    return abs(s) / 2.0


def filter_noise(polygons: List[Tuple[List[Tuple[float, float]], str]],
                 ratio: float = NOISE_RATIO,
                 ) -> List[Tuple[List[Tuple[float, float]], str]]:
    """Remove polygons whose area < ratio * max_area."""
    if not polygons:
        return []

    areas = [shoelace_area(pts) for pts, _ in polygons]
    max_area = max(areas)
    threshold = ratio * max_area

    kept = []
    for (pts, label), area in zip(polygons, areas):
        if area >= threshold:
            kept.append((pts, label, area))
        else:
            log.debug(f"  Noise removed: area={area:.1f} < threshold={threshold:.1f}  label={repr(label)}")

    log.info(f"Noise filter: {len(polygons)} → {len(kept)} polygons (threshold={threshold:.1f} mm²)")
    return kept  # type: ignore[return-value]  # now (pts, label, area)


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 6 — SHAPELY VALIDATION + REPAIR
# ═══════════════════════════════════════════════════════════════════════════════

def validate_polygon(pts: List[Tuple[float, float]],
                     ) -> Optional[List[Tuple[float, float]]]:
    """
    Use Shapely to check and optionally repair a polygon.

    Repair strategy:
      - buffer(0) fixes most self-intersections
      - If result is MultiPolygon → take largest sub-polygon
    """
    try:
        from shapely.geometry import Polygon
        from shapely.validation import make_valid
    except ImportError:
        log.warning("Shapely not installed — skipping validation")
        return pts

    poly = Polygon(pts)

    if poly.is_empty:
        return None

    if not poly.is_valid:
        poly = make_valid(poly)
        if poly.is_empty:
            return None
        # make_valid may return a GeometryCollection / MultiPolygon
        if poly.geom_type != "Polygon":
            # Take the largest sub-polygon
            from shapely.geometry import MultiPolygon, GeometryCollection
            candidates = (
                list(poly.geoms)
                if poly.geom_type in ("MultiPolygon", "GeometryCollection")
                else [poly]
            )
            polys_only = [g for g in candidates if g.geom_type == "Polygon" and not g.is_empty]
            if not polys_only:
                return None
            poly = max(polys_only, key=lambda g: g.area)

    # Extract exterior ring coordinates (drop repeated last point)
    coords = list(poly.exterior.coords)[:-1]
    if len(coords) < MIN_POINTS:
        return None

    return [(float(x), float(y)) for x, y in coords]


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 7 — BOUNDING BOX + NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def bounding_box(pts: List[Tuple[float, float]]) -> Dict:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return {
        "min_x": min_x, "min_y": min_y,
        "max_x": max_x, "max_y": max_y,
        "width": max_x - min_x,
        "height": max_y - min_y,
    }


def normalize_points(pts: List[Tuple[float, float]],
                     bbox: Dict,
                     ) -> List[Tuple[float, float]]:
    """
    Map each point to [0, 1] relative to its bounding box.
    Used for transferring design placement across sizes.
    """
    w = bbox["width"] or 1.0
    h = bbox["height"] or 1.0
    return [
        ((x - bbox["min_x"]) / w, (y - bbox["min_y"]) / h)
        for x, y in pts
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 8 — DEBUG SVG RENDERER
# ═══════════════════════════════════════════════════════════════════════════════

def render_debug_svg(pieces: List[Dict], output_path: str) -> None:
    """
    Render all polygons into one SVG with:
    - Filled polygon (semi-transparent)
    - Cut-line outline
    - Bounding box (dashed)
    - Label: index + area
    """
    if not pieces:
        log.warning("No pieces to render.")
        return

    # Global bounds for viewBox
    all_pts = [p for pc in pieces for p in pc["points"]]
    gxs = [p[0] for p in all_pts]
    gys = [p[1] for p in all_pts]
    vx, vy = min(gxs), min(gys)
    vw = max(gxs) - vx
    vh = max(gys) - vy
    pad = max(vw, vh) * 0.02
    vx -= pad; vy -= pad; vw += 2*pad; vh += 2*pad

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}" '
        f'width="1400" height="{int(1400 * vh / max(vw, 1))}" '
        f'style="background:#f8fafc">',
        "  <defs>",
        "    <style>text { font-family: monospace; }</style>",
        "  </defs>",
    ]

    for i, pc in enumerate(pieces):
        color = _PALETTE[i % len(_PALETTE)]
        pts = pc["points"]
        bb = pc["bbox"]
        area = pc["area"]

        pts_str = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)

        # Filled polygon
        lines.append(
            f'  <polygon points="{pts_str}" '
            f'fill="{color}" fill-opacity="0.25" '
            f'stroke="{color}" stroke-width="0.8" stroke-linejoin="round"/>'
        )

        # Bounding box (dashed)
        lines.append(
            f'  <rect x="{bb["min_x"]:.2f}" y="{bb["min_y"]:.2f}" '
            f'width="{bb["width"]:.2f}" height="{bb["height"]:.2f}" '
            f'fill="none" stroke="{color}" stroke-width="0.4" '
            f'stroke-dasharray="3,2" opacity="0.6"/>'
        )

        # Label background + text
        cx = (bb["min_x"] + bb["max_x"]) / 2
        cy = (bb["min_y"] + bb["max_y"]) / 2
        fs = max(3.0, min(bb["width"], bb["height"]) * 0.06)
        label_text = pc.get("label", "")
        line1 = f"#{i}  {label_text}" if label_text else f"#{i}"
        line2 = f"area={area:.0f} mm²"

        for offset, txt in [(-fs * 0.6, line1), (fs * 0.6, line2)]:
            lines.append(
                f'  <text x="{cx:.2f}" y="{cy + offset:.2f}" '
                f'font-size="{fs:.2f}" text-anchor="middle" '
                f'fill="{color}" font-weight="bold" '
                f'stroke="white" stroke-width="{fs*0.08:.2f}" paint-order="stroke">'
                f"{txt}</text>"
            )

    lines.append("</svg>")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Debug SVG → {output_path}  ({len(pieces)} pieces)")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run_pipeline(
    plt_path: str,
    json_out: str = "cleaned_polygons.json",
    svg_out: str = "debug_polygons.svg",
    close_tol_mm: float = CLOSE_TOL_MM,
    noise_ratio: float = NOISE_RATIO,
) -> List[Dict]:
    """
    Full pipeline: PLT file → cleaned polygon list.

    Returns list of dicts:
        {
            "index": int,
            "label": str,
            "points": [[x, y], ...],          # mm
            "points_normalized": [[rx, ry], ...],
            "area": float,                     # mm²
            "bbox": {min_x, min_y, max_x, max_y, width, height},
        }
    """
    log.info(f"=== HPGL Pipeline: {plt_path} ===")

    # ── 1. Read & tokenize ────────────────────────────────────────────────────
    raw = Path(plt_path).read_bytes().decode("latin-1", errors="replace")
    raw = raw.replace("\r", "").replace("\x00", "")
    tokens = tokenize(raw)
    log.info(f"Tokens: {len(tokens)}")

    # ── 2. State machine → raw paths ─────────────────────────────────────────
    machine = _HPGLMachine()
    machine.feed(tokens)
    log.info(f"Raw paths: {len(machine.raw_paths)}")

    # ── 3. Auto scale ─────────────────────────────────────────────────────────
    scale = detect_scale(machine.raw_paths)

    # Convert to mm
    raw_mm: List[Tuple[List[Tuple[float, float]], str]] = [
        ([(x / scale, y / scale) for x, y in pts], label)
        for pts, label in machine.raw_paths
    ]

    # ── 4. Close paths ────────────────────────────────────────────────────────
    closed: List[Tuple[List[Tuple[float, float]], str]] = []
    for pts, label in raw_mm:
        result = try_close(pts, tol_mm=close_tol_mm)
        if result is not None:
            closed.append((result, label))

    log.info(f"After closing: {len(closed)} polygons")

    # ── 4b. Remove pastal frame ───────────────────────────────────────────────
    # The full-fabric boundary rectangle spans nearly the entire coord range.
    # Detect it: bbox_width > 80% of global width AND bbox_height > 80% of global height.
    if closed:
        all_x = [x for pts, _ in closed for x, y in pts]
        all_y = [y for pts, _ in closed for x, y in pts]
        g_w = max(all_x) - min(all_x)
        g_h = max(all_y) - min(all_y)
        filtered_closed = []
        for pts, label in closed:
            bb = bounding_box(pts)
            is_frame = (bb["width"] > 0.8 * g_w and bb["height"] > 0.8 * g_h)
            if is_frame:
                log.info(f"  Pastal çerçevesi atıldı: {bb['width']:.0f}×{bb['height']:.0f}mm")
            else:
                filtered_closed.append((pts, label))
        closed = filtered_closed

    # ── 5. Noise filter ───────────────────────────────────────────────────────
    # Returns (pts, label, area) triples
    with_area = filter_noise(closed, ratio=noise_ratio)  # type: ignore[assignment]

    # ── 6. Shapely validation ─────────────────────────────────────────────────
    validated: List[Tuple[List[Tuple[float, float]], str, float]] = []
    for pts, label, area in with_area:
        fixed = validate_polygon(pts)
        if fixed is not None:
            # Recompute area after repair
            validated.append((fixed, label, shoelace_area(fixed)))
        else:
            log.debug(f"  Discarded invalid polygon  label={repr(label)}")

    log.info(f"After validation: {len(validated)} polygons")

    # ── 7. Sort by area DESC ──────────────────────────────────────────────────
    validated.sort(key=lambda t: t[2], reverse=True)

    # ── 8. Build output dicts ─────────────────────────────────────────────────
    pieces: List[Dict] = []
    for idx, (pts, label, area) in enumerate(validated):
        bb = bounding_box(pts)
        norm = normalize_points(pts, bb)
        pieces.append({
            "index": idx,
            "label": label,
            "points": [[round(x, 4), round(y, 4)] for x, y in pts],
            "points_normalized": [[round(x, 6), round(y, 6)] for x, y in norm],
            "area": round(area, 2),
            "bbox": {k: round(v, 4) for k, v in bb.items()},
        })

    log.info(f"Final pieces: {len(pieces)}")
    for pc in pieces:
        log.info(
            f"  [{pc['index']:2d}] {pc['label'] or '(no label)':20s} "
            f"area={pc['area']:>10.0f} mm²  "
            f"bbox=({pc['bbox']['width']:.0f}×{pc['bbox']['height']:.0f}mm)"
        )

    # ── 9. Write JSON ─────────────────────────────────────────────────────────
    Path(json_out).write_text(
        json.dumps(pieces, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(f"JSON → {json_out}")

    # ── 10. Write debug SVG ───────────────────────────────────────────────────
    render_debug_svg(pieces, svg_out)

    return pieces


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hpgl_pipeline.py <file.plt> [output.json] [debug.svg]")
        sys.exit(1)

    plt_file = sys.argv[1]
    json_file = sys.argv[2] if len(sys.argv) > 2 else "cleaned_polygons.json"
    svg_file  = sys.argv[3] if len(sys.argv) > 3 else "debug_polygons.svg"

    result = run_pipeline(plt_file, json_out=json_file, svg_out=svg_file)
    print(f"\nDone. {len(result)} pieces extracted.")
    print(f"  JSON : {json_file}")
    print(f"  SVG  : {svg_file}")
