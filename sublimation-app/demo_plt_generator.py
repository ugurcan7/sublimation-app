"""
Demo PLT Dosyası Oluşturucu
============================
Gerçekçi bir sublimasyon forma kalıbı PLT dosyası üretir.
Bedenler: S, M, L, XL, XXL
Parçalar: Ön, Arka, Sol Kol, Sağ Kol

HPGL birimleri: 40 unit/mm
"""
import math

# ─── Kalıp şekilleri ─────────────────────────────────────────────────────────

def make_jersey_front(width_mm, height_mm, neck_radius_mm, shoulder_drop_mm):
    """
    Forma ön parçası — basitleştirilmiş.
    Kare + boyun kesim + omuz eğimi.
    """
    pts = []
    w, h = width_mm, height_mm
    nr = neck_radius_mm

    # Saat yönünde, sol alt'tan başla
    pts.append((0, 0))           # Sol alt
    pts.append((w, 0))           # Sağ alt
    pts.append((w, h))           # Sağ üst omuz

    # Sağ omuz → boyun sağı (eğri yaklaşımı — çokgen)
    shoulder_x = w * 0.35
    neck_top = h + shoulder_drop_mm

    # Omuz çizgisi
    pts.append((w * 0.65, h + shoulder_drop_mm))   # Sağ boyun yanı

    # Boyun eğrisi (yarım çember yaklaşımı)
    n_neck = 12
    for i in range(n_neck + 1):
        angle = math.pi - (math.pi / n_neck) * i
        nx = w / 2 + nr * math.cos(angle)
        ny = neck_top + nr * math.sin(angle) - nr
        pts.append((nx, ny))

    pts.append((w * 0.35, h + shoulder_drop_mm))   # Sol boyun yanı
    pts.append((0, h))           # Sol üst omuz
    pts.append((0, 0))           # Kapalı

    return pts


def make_jersey_back(width_mm, height_mm, neck_radius_mm, shoulder_drop_mm):
    """Forma arka parçası — önden biraz daha büyük boyun."""
    nr_back = neck_radius_mm * 0.6  # Arka boyun daha az derin
    pts = []
    w, h = width_mm, height_mm

    pts.append((0, 0))
    pts.append((w, 0))
    pts.append((w, h))
    pts.append((w * 0.65, h + shoulder_drop_mm * 0.5))

    n_neck = 12
    for i in range(n_neck + 1):
        angle = math.pi - (math.pi / n_neck) * i
        nx = w / 2 + nr_back * math.cos(angle)
        ny = (h + shoulder_drop_mm * 0.5) + nr_back * math.sin(angle) - nr_back
        pts.append((nx, ny))

    pts.append((w * 0.35, h + shoulder_drop_mm * 0.5))
    pts.append((0, h))
    pts.append((0, 0))

    return pts


def make_sleeve(length_mm, top_width_mm, bottom_width_mm, cap_height_mm):
    """
    Kol parçası.
    Trapez şeklinde + üstte yuvarlak kap.
    """
    pts = []

    # Alt kenar (ek yeri — daha dar)
    cuff_offset = (top_width_mm - bottom_width_mm) / 2

    pts.append((cuff_offset, 0))                          # Sol alt
    pts.append((cuff_offset + bottom_width_mm, 0))        # Sağ alt
    pts.append((top_width_mm, length_mm))                 # Sağ üst

    # Kap eğrisi (armhole — kol başı)
    n_cap = 16
    cx = top_width_mm / 2
    cy = length_mm + cap_height_mm
    for i in range(n_cap + 1):
        angle = math.pi * i / n_cap  # 0 → pi (üstten alta)
        x = cx + (top_width_mm / 2) * math.cos(angle)
        y = cy - cap_height_mm * math.sin(angle)
        pts.append((x, y))

    pts.append((0, length_mm))                            # Sol üst
    pts.append((cuff_offset, 0))                          # Kapalı

    return pts


# ─── Beden ölçüleri ──────────────────────────────────────────────────────────

SIZES = {
    "S": {
        "front_w": 460, "front_h": 650, "neck_r": 70,  "shoulder_drop": 15,
        "sleeve_len": 200, "sleeve_top_w": 165, "sleeve_bot_w": 130, "sleeve_cap": 40,
    },
    "M": {
        "front_w": 490, "front_h": 680, "neck_r": 73,  "shoulder_drop": 16,
        "sleeve_len": 210, "sleeve_top_w": 175, "sleeve_bot_w": 138, "sleeve_cap": 42,
    },
    "L": {
        "front_w": 520, "front_h": 710, "neck_r": 76,  "shoulder_drop": 17,
        "sleeve_len": 220, "sleeve_top_w": 185, "sleeve_bot_w": 146, "sleeve_cap": 44,
    },
    "XL": {
        "front_w": 552, "front_h": 742, "neck_r": 79,  "shoulder_drop": 18,
        "sleeve_len": 230, "sleeve_top_w": 195, "sleeve_bot_w": 154, "sleeve_cap": 46,
    },
    "XXL": {
        "front_w": 586, "front_h": 776, "neck_r": 82,  "shoulder_drop": 19,
        "sleeve_len": 240, "sleeve_top_w": 207, "sleeve_bot_w": 163, "sleeve_cap": 48,
    },
}

UNITS_PER_MM = 40  # HPGL


def mm_to_hpgl(v):
    return v * UNITS_PER_MM


def pts_to_hpgl(pts):
    return [(int(mm_to_hpgl(x)), int(mm_to_hpgl(y))) for x, y in pts]


# ─── PLT üretici ─────────────────────────────────────────────────────────────

def generate_plt(output_path: str):
    lines = ["IN;", "VS30;"]

    # Her beden için parçaları farklı konuma yerleştir (pastal düzeni)
    col_offset = 0  # Yatay konum (mm)
    col_spacing = 700  # Her beden grubu arası boşluk

    for size_name, dims in SIZES.items():
        row_offset = 0  # Dikey konum (mm)
        row_spacing = 850

        # ── Ön parça ──────────────────────────────────────────────────────────
        front_pts = make_jersey_front(
            dims["front_w"], dims["front_h"],
            dims["neck_r"], dims["shoulder_drop"]
        )
        front_hpgl = [(int(mm_to_hpgl(x + col_offset)),
                       int(mm_to_hpgl(y + row_offset))) for x, y in front_pts]

        lines.append(f"SP1;")
        lines.append(f"PU{front_hpgl[0][0]},{front_hpgl[0][1]};")
        for x, y in front_hpgl[1:]:
            lines.append(f"PD{x},{y};")
        lines.append("PU;")
        lines.append(f"LB{size_name}-FRONT\\003")

        row_offset += row_spacing

        # ── Arka parça ────────────────────────────────────────────────────────
        back_pts = make_jersey_back(
            dims["front_w"] + 10, dims["front_h"] + 5,
            dims["neck_r"], dims["shoulder_drop"]
        )
        back_hpgl = [(int(mm_to_hpgl(x + col_offset)),
                      int(mm_to_hpgl(y + row_offset))) for x, y in back_pts]

        lines.append("SP1;")
        lines.append(f"PU{back_hpgl[0][0]},{back_hpgl[0][1]};")
        for x, y in back_hpgl[1:]:
            lines.append(f"PD{x},{y};")
        lines.append("PU;")
        lines.append(f"LB{size_name}-BACK\\003")

        row_offset += row_spacing

        # ── Sol kol ───────────────────────────────────────────────────────────
        lsleeve_pts = make_sleeve(
            dims["sleeve_len"], dims["sleeve_top_w"],
            dims["sleeve_bot_w"], dims["sleeve_cap"]
        )
        ls_hpgl = [(int(mm_to_hpgl(x + col_offset)),
                    int(mm_to_hpgl(y + row_offset))) for x, y in lsleeve_pts]

        lines.append("SP2;")
        lines.append(f"PU{ls_hpgl[0][0]},{ls_hpgl[0][1]};")
        for x, y in ls_hpgl[1:]:
            lines.append(f"PD{x},{y};")
        lines.append("PU;")
        lines.append(f"LB{size_name}-LEFT_SLEEVE\\003")

        # ── Sağ kol (sol kolun yansıması) ─────────────────────────────────────
        # Sağ kolun x koordinatlarını mirror et
        max_x = max(x for x, y in lsleeve_pts)
        rsleeve_pts = [(max_x - x + col_offset + dims["sleeve_top_w"] * 1.2,
                        y + row_offset) for x, y in lsleeve_pts]
        rs_hpgl = [(int(mm_to_hpgl(x)), int(mm_to_hpgl(y))) for x, y in rsleeve_pts]

        lines.append("SP2;")
        lines.append(f"PU{rs_hpgl[0][0]},{rs_hpgl[0][1]};")
        for x, y in rs_hpgl[1:]:
            lines.append(f"PD{x},{y};")
        lines.append("PU;")
        lines.append(f"LB{size_name}-RIGHT_SLEEVE\\003")

        col_offset += col_spacing

    lines.append("SP0;")
    lines.append("IN;")

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="ascii") as f:
        f.write(content)

    print(f"Demo PLT üretildi: {output_path}")
    print(f"Toplam satır: {len(lines)}")
    print(f"Bedenler: {list(SIZES.keys())}")


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(__file__), "demo_pastal.plt")
    generate_plt(out)
    print("\nTest için şu komutu çalıştırın:")
    print(f"  python demo_plt_generator.py")
    print(f"  Ardından arayüzden '{out}' dosyasını yükleyin.")
