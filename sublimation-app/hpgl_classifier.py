"""
HPGL Geometric Classifier
==========================
Label olmayan PLT dosyalarında parçaları geometrik olarak
beden gruplarına ve parça tiplerine ayırır.

Kullanım:
    python hpgl_classifier.py cleaned_polygons.json [n_sizes]

Çıktı:
    classified_pieces.json
    classified_debug.svg
"""
from __future__ import annotations

import json
import sys
import math
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("hpgl_classifier")

# ─── Parça tipi eşikleri ─────────────────────────────────────────────────────

PALETTE = [
    "#2563eb","#7c3aed","#059669","#d97706",
    "#dc2626","#0891b2","#65a30d","#9333ea",
    "#db2777","#ea580c","#16a34a","#1d4ed8",
    "#f59e0b","#10b981","#ef4444","#8b5cf6",
    "#06b6d4","#84cc16","#f97316","#6366f1",
    "#14b8a6","#e11d48",
]

TYPE_COLORS = {
    "front":        "#2563eb",
    "back":         "#7c3aed",
    "left_sleeve":  "#059669",
    "right_sleeve": "#d97706",
    "panel":        "#dc2626",
    "strip":        "#0891b2",
    "detail":       "#65a30d",
    "unknown":      "#94a3b8",
}


# ─── Geometrik özellik çıkarımı ───────────────────────────────────────────────

def geometry_features(piece: Dict) -> Dict:
    bb = piece["bbox"]
    w, h = bb["width"], bb["height"]
    area = piece["area"]
    ratio = w / max(h, 1)
    perim_approx = 2 * (w + h)
    compactness = (4 * math.pi * area) / max(perim_approx ** 2, 1)
    return {
        "ratio": ratio,          # width / height
        "area": area,
        "compactness": compactness,
        "width": w,
        "height": h,
        "cx": (bb["min_x"] + bb["max_x"]) / 2,
        "cy": (bb["min_y"] + bb["max_y"]) / 2,
    }


def coarse_type(feat: Dict) -> str:
    """Sadece aspect ratio + area ile kaba sınıf."""
    r = feat["ratio"]
    if r > 1.0:
        return "body"
    elif r < 0.25:
        return "strip"
    elif r < 0.55:
        return "sleeve_tall"
    else:
        return "sleeve_wide"


# ─── Beden sayısını tahmin et ────────────────────────────────────────────────

def estimate_n_sizes(pieces: List[Dict]) -> int:
    """
    Beden sayısını tahmin et.
    Yöntem: her coarse type grubunun boyutlarının GCD'si ≈ beden sayısı
    """
    by_type: Dict[str, int] = defaultdict(int)
    for p in pieces:
        by_type[coarse_type(geometry_features(p))] += 1

    counts = list(by_type.values())
    if not counts:
        return 1

    from math import gcd
    from functools import reduce
    g = reduce(gcd, counts)
    log.info(f"Coarse type sayıları: {dict(by_type)}  GCD={g}")
    return g


# ─── Beden gruplandırma ───────────────────────────────────────────────────────

def group_by_size(pieces: List[Dict], n_sizes: int) -> List[List[int]]:
    """
    Parçaları n_sizes beden grubuna ayır.

    Strateji:
    1. Her coarse type içinde parçaları alana göre büyükten küçüğe sırala
    2. Her coarse type, tam olarak n_sizes adet (veya katı) parça içerir
    3. Rank i'deki parçalar → beden i grubuna gider
    4. Aynı beden grubuna düşen parçalar → beden i
    """
    # Coarse type → sorted indices (DESC area)
    type_groups: Dict[str, List[int]] = defaultdict(list)
    for i, p in enumerate(pieces):
        t = coarse_type(geometry_features(p))
        type_groups[t].append(i)

    for t in type_groups:
        type_groups[t].sort(key=lambda i: -pieces[i]["area"])

    # Her coarse type kaç "parça başına beden" içeriyor
    size_groups: List[List[int]] = [[] for _ in range(n_sizes)]

    for t, idxs in type_groups.items():
        n_per_size = len(idxs) // n_sizes
        if n_per_size == 0:
            # n_sizes'tan az parça — her birini ayrı beden olarak ata
            for rank, idx in enumerate(idxs):
                size_groups[rank % n_sizes].append(idx)
            continue

        # Rank bazlı atama: büyükten küçüğe → beden 0 = en büyük
        for rank, idx in enumerate(idxs):
            size_idx = rank // n_per_size
            if size_idx < n_sizes:
                size_groups[size_idx].append(idx)
            else:
                size_groups[n_sizes - 1].append(idx)  # taşanlar son bedene

    return size_groups


# ─── Parça tipi sınıflandırma ────────────────────────────────────────────────

def classify_within_size(size_pieces: List[Dict]) -> List[str]:
    """
    Bir beden grubundaki parçalara tip ata.

    Kurallar (alana göre büyükten küçüğe sıralı):
    - body tipi parçalar: en büyük = front, 2. = back, sonrakiler = panel
    - sleeve parçalar: mirror çifti varsa = left/right_sleeve, yoksa = sleeve
    - strip parçalar: strip
    """
    # Coarse type'a göre ayır
    bodies  = sorted([p for p in size_pieces if coarse_type(geometry_features(p)) == "body"],
                     key=lambda p: -p["area"])
    sleeves = sorted([p for p in size_pieces
                      if coarse_type(geometry_features(p)) in ("sleeve_tall", "sleeve_wide")],
                     key=lambda p: -p["area"])
    strips  = [p for p in size_pieces if coarse_type(geometry_features(p)) == "strip"]

    labels_map: Dict[int, str] = {}

    # Gövde parçaları
    type_order = ["front", "back", "panel_front", "panel_back",
                  "panel_3", "panel_4", "panel_5", "panel_6"]
    for i, p in enumerate(bodies):
        lbl = type_order[i] if i < len(type_order) else f"body_{i}"
        labels_map[id(p)] = lbl

    # Kol parçaları — mirror tespiti
    mirror_tol = 0.005  # %0.5 alan farkı
    used = set()
    sleeve_labels = []

    for i, s1 in enumerate(sleeves):
        if i in used:
            continue
        found = False
        for j, s2 in enumerate(sleeves):
            if j <= i or j in used:
                continue
            a1, a2 = s1["area"], s2["area"]
            if abs(a1 - a2) / max(a1, 1) < mirror_tol:
                # Mirror çift — X pozisyonuna göre sol/sağ belirle
                cx1 = (s1["bbox"]["min_x"] + s1["bbox"]["max_x"]) / 2
                cx2 = (s2["bbox"]["min_x"] + s2["bbox"]["max_x"]) / 2
                if cx1 < cx2:
                    sleeve_labels.append((i, "left_sleeve"))
                    sleeve_labels.append((j, "right_sleeve"))
                else:
                    sleeve_labels.append((i, "right_sleeve"))
                    sleeve_labels.append((j, "left_sleeve"))
                used.add(i)
                used.add(j)
                found = True
                break
        if not found and i not in used:
            sleeve_labels.append((i, "sleeve"))
            used.add(i)

    sleeve_rank_labels = ["left_sleeve", "right_sleeve",
                          "sleeve_back_l", "sleeve_back_r",
                          "sleeve_panel_l", "sleeve_panel_r",
                          "sleeve_3", "sleeve_4"]
    # Mirror tespiti olmayan sıraya göre etiketle
    non_mirrored = [(k, sleeves[k]) for k in range(len(sleeves)) if k not in used]
    for rank, (k, p) in enumerate(non_mirrored):
        lbl = sleeve_rank_labels[rank] if rank < len(sleeve_rank_labels) else f"sleeve_{rank}"
        sleeve_labels.append((k, lbl))

    for k, lbl in sleeve_labels:
        labels_map[id(sleeves[k])] = lbl

    # Şeritler
    for i, p in enumerate(strips):
        labels_map[id(p)] = f"strip_{i}" if i > 0 else "strip"

    # Sıralı etiket listesi döndür
    return [labels_map.get(id(p), "unknown") for p in size_pieces]


# ─── Debug SVG ───────────────────────────────────────────────────────────────

def render_classified_svg(pieces: List[Dict], output_path: str) -> None:
    if not pieces:
        return

    all_pts = [pt for p in pieces for pt in p["points"]]
    gxs = [x for x, y in all_pts]
    gys = [y for x, y in all_pts]
    vx = min(gxs); vy = min(gys)
    vw = max(gxs) - vx; vh = max(gys) - vy
    pad = max(vw, vh) * 0.01
    vx -= pad; vy -= pad; vw += 2*pad; vh += 2*pad

    svg_h = max(200, int(1800 * vh / max(vw, 1)))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}" '
        f'width="1800" height="{svg_h}" style="background:#f1f5f9">',
        "<defs><style>text{font-family:monospace;font-weight:bold}</style></defs>",
    ]

    for p in pieces:
        color = TYPE_COLORS.get(p.get("piece_type", "unknown"),
                                PALETTE[p.get("size_index", 0) % len(PALETTE)])
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in p["points"])
        bb = p["bbox"]
        cx = (bb["min_x"] + bb["max_x"]) / 2
        cy_c = (bb["min_y"] + bb["max_y"]) / 2
        fs = max(2.5, min(bb["width"], bb["height"]) * 0.055)
        size_lbl = p.get("size_label", "")
        type_lbl = p.get("piece_type", "")
        area_lbl = f"{p['area']/1000:.0f}k"

        lines += [
            f'<polygon points="{pts_str}" fill="{color}" fill-opacity="0.3" '
            f'stroke="{color}" stroke-width="1" stroke-linejoin="round"/>',
            f'<rect x="{bb["min_x"]:.1f}" y="{bb["min_y"]:.1f}" '
            f'width="{bb["width"]:.1f}" height="{bb["height"]:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="0.4" stroke-dasharray="4,2"/>',
        ]
        for dy, txt in [(-fs*1.1, size_lbl), (0, type_lbl), (fs*1.1, area_lbl)]:
            lines.append(
                f'<text x="{cx:.1f}" y="{cy_c+dy:.1f}" font-size="{fs:.1f}" '
                f'text-anchor="middle" fill="{color}" '
                f'stroke="white" stroke-width="{fs*0.1:.2f}" paint-order="stroke">'
                f"{txt}</text>"
            )

    lines.append("</svg>")
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    log.info(f"SVG → {output_path}")


# ─── Ana fonksiyon ────────────────────────────────────────────────────────────

def classify_pieces(
    json_in: str,
    json_out: str = "classified_pieces.json",
    svg_out: str = "classified_debug.svg",
    n_sizes: Optional[int] = None,
) -> List[Dict]:

    pieces = json.load(open(json_in, encoding="utf-8"))
    log.info(f"Yüklendi: {len(pieces)} parça ({json_in})")

    # Beden sayısını belirle
    if n_sizes is None:
        n_sizes = estimate_n_sizes(pieces)

    log.info(f"Beden sayısı: {n_sizes}  →  {len(pieces)}/{n_sizes} = {len(pieces)/n_sizes:.1f} parça/beden")

    # Beden grupları
    size_groups = group_by_size(pieces, n_sizes)

    # Beden adlarını belirle (büyükten küçüğe sırala)
    SIZE_NAMES = ["XXXL", "XXL", "XL", "L", "M", "S", "XS", "XXS"]
    if n_sizes <= 8:
        # Standart beden isimleri — büyükten küçüğe
        offset = max(0, (len(SIZE_NAMES) - n_sizes) // 2)
        size_name_list = SIZE_NAMES[offset: offset + n_sizes]
    else:
        # Sayısal
        size_name_list = [str(i + 1) for i in range(n_sizes)]

    # Her gruptaki parçalara tip ata
    result = []
    for size_idx, piece_indices in enumerate(size_groups):
        size_pieces = [pieces[i] for i in piece_indices]
        if not size_pieces:
            continue

        type_labels = classify_within_size(size_pieces)
        size_lbl = size_name_list[size_idx] if size_idx < len(size_name_list) else str(size_idx + 1)

        for p, lbl in zip(size_pieces, type_labels):
            result.append({
                **p,
                "size_label": size_lbl,
                "size_index": size_idx,
                "piece_type": lbl,
            })

    # Özet
    log.info("=== SINIFLANDIRMA SONUCU ===")
    from collections import Counter
    type_counts = Counter(p["piece_type"] for p in result)
    for t, c in sorted(type_counts.items()):
        log.info(f"  {t:20s}: {c} parça")

    log.info("\n=== BEDEN BAZINDA ===")
    by_size: Dict[str, List] = defaultdict(list)
    for p in result:
        by_size[p["size_label"]].append(p["piece_type"])
    for sz in size_name_list[:n_sizes]:
        types = sorted(by_size.get(sz, []))
        log.info(f"  {sz:6s}: {len(types)} parça  →  {types[:6]}")

    # JSON çıktısı
    Path(json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"JSON → {json_out}")

    render_classified_svg(result, svg_out)
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    json_in = sys.argv[1] if len(sys.argv) > 1 else "cleaned_polygons.json"
    n_sizes = int(sys.argv[2]) if len(sys.argv) > 2 else None
    json_out = sys.argv[3] if len(sys.argv) > 3 else "classified_pieces.json"
    svg_out  = sys.argv[4] if len(sys.argv) > 4 else "classified_debug.svg"

    result = classify_pieces(json_in, json_out, svg_out, n_sizes)
    print(f"\nDone. {len(result)} parça sınıflandırıldı.")
