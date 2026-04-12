"""
Veri modelleri — tüm backend modülleri bu dosyadan import eder.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Tuple
import numpy as np


# ─── Sabitler ────────────────────────────────────────────────────────────────

SIZE_ORDER: List[str] = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]
SIZE_INDEX: Dict[str, int] = {s: i for i, s in enumerate(SIZE_ORDER)}

PIECE_TYPES = ["front", "back", "left_sleeve", "right_sleeve"]

PIECE_ALIASES: Dict[str, str] = {
    # Türkçe
    "on": "front", "ön": "front", "one": "front",
    "on_panel": "front", "ön_panel": "front",
    "on_parca": "front", "ön_parça": "front",
    "arka": "back", "arka_panel": "back",
    "arka_parca": "back", "arka_parça": "back",
    "sol_kol": "left_sleeve", "sol kol": "left_sleeve", "sol": "left_sleeve",
    "sag_kol": "right_sleeve", "sag kol": "right_sleeve",
    "sağ_kol": "right_sleeve", "sağ kol": "right_sleeve", "sağ": "right_sleeve",
    "kol": "left_sleeve",  # tek kol varsa left_sleeve
    # İngilizce
    "front": "front", "back": "back",
    "f": "front", "b": "back",
    "ls": "left_sleeve", "rs": "right_sleeve",
    "lsleeve": "left_sleeve", "rsleeve": "right_sleeve",
    "left_sleeve": "left_sleeve", "right_sleeve": "right_sleeve",
    "left": "left_sleeve", "right": "right_sleeve",
    "sleeve_l": "left_sleeve", "sleeve_r": "right_sleeve",
    "sleeve": "left_sleeve",
    # Sayısal (bazı CAD sistemleri)
    "piece1": "front", "piece2": "back",
    "piece3": "left_sleeve", "piece4": "right_sleeve",
    # CAD kısa kodlar
    "fp": "front", "bp": "back", "lk": "left_sleeve", "rk": "right_sleeve",
}

# HPGL'de 1 unit = 0.025 mm (40 unit/mm)
HPGL_UNITS_PER_MM = 40.0


# ─── Temel geometri ───────────────────────────────────────────────────────────

@dataclass
class Point:
    x: float
    y: float

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y)

    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center(self) -> Point:
        return Point((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)

    @property
    def area(self) -> float:
        return self.width * self.height


# ─── Kalıp parçası ───────────────────────────────────────────────────────────

@dataclass
class PatternPiece:
    """
    Tek bir kalıp parçası.
    points: mm cinsinden koordinatlar (HPGL'den dönüştürülmüş)
    """
    label: str                       # PLT'deki ham etiket (örn: "M-FRONT")
    size: str                        # normalize edilmiş beden (örn: "M")
    piece_type: str                  # "front" | "back" | "left_sleeve" | "right_sleeve" | "unknown"
    points: np.ndarray               # shape (N, 2) — mm

    # --- Türetilmiş özellikler --------------------------------------------------

    def bounding_box(self) -> BoundingBox:
        return BoundingBox(
            x_min=float(self.points[:, 0].min()),
            y_min=float(self.points[:, 1].min()),
            x_max=float(self.points[:, 0].max()),
            y_max=float(self.points[:, 1].max()),
        )

    def area(self) -> float:
        """Shoelace (Green) formülü ile alan."""
        pts = self.points
        n = len(pts)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += pts[i, 0] * pts[j, 1]
            area -= pts[j, 0] * pts[i, 1]
        return abs(area) / 2.0

    def perimeter(self) -> float:
        pts = self.points
        diff = np.diff(pts, axis=0, append=pts[:1])
        return float(np.linalg.norm(diff, axis=1).sum())

    def aspect_ratio(self) -> float:
        bb = self.bounding_box()
        if bb.height == 0:
            return 0.0
        return bb.width / bb.height

    def centroid(self) -> np.ndarray:
        return self.points.mean(axis=0)

    def translate(self, dx: float, dy: float) -> "PatternPiece":
        return PatternPiece(
            label=self.label,
            size=self.size,
            piece_type=self.piece_type,
            points=self.points + np.array([dx, dy]),
        )

    def to_svg_points(self) -> str:
        return " ".join(f"{x:.3f},{y:.3f}" for x, y in self.points)

    def close(self) -> np.ndarray:
        """Kapalı poligon noktaları (son nokta == ilk nokta)."""
        return np.vstack([self.points, self.points[:1]])


# ─── Grading ─────────────────────────────────────────────────────────────────

@dataclass
class GradingVectors:
    """
    İki beden arasındaki grading vektörleri.
    vectors: shape (N_SAMPLES, 2) — her örneklenmiş noktadaki (dx, dy) mm
    from_size: kaynak beden
    to_size: hedef beden
    n_samples: yeniden örnekleme sayısı
    """
    from_size: str
    to_size: str
    piece_type: str
    vectors: np.ndarray      # (N, 2)
    n_samples: int

    @property
    def step_count(self) -> int:
        return SIZE_INDEX.get(self.to_size, 0) - SIZE_INDEX.get(self.from_size, 0)


@dataclass
class GradedPiece:
    """Grading uygulanmış kalıp parçası."""
    piece_type: str
    size: str
    points: np.ndarray       # (N, 2) mm — yeniden örneklenmiş
    source_label: str = ""


# ─── Session ─────────────────────────────────────────────────────────────────

@dataclass
class UploadSession:
    session_id: str
    reference_size: str = "M"
    plt_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    # PLT'den ayrıştırılmış parçalar: {size: {piece_type: PatternPiece}}
    parsed_pieces: Dict[str, Dict[str, PatternPiece]] = field(default_factory=dict)

    # Kullanıcının yüklediği tasarım görsel dosyaları: {piece_type: file_path}
    design_files: Dict[str, str] = field(default_factory=dict)

    # Hesaplanan grading vektörleri: {piece_type: GradingVectors}
    grading_vectors: Dict[str, GradingVectors] = field(default_factory=dict)

    # Üretilen çıktı PDF yolları: {size: pdf_path}
    output_pdfs: Dict[str, str] = field(default_factory=dict)

    # SVG çıktıları: {size: {piece_type: svg_path}}
    output_svgs: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # Hata mesajları
    errors: List[str] = field(default_factory=list)

    def detected_sizes(self) -> List[str]:
        def _sort_key(s: str):
            if s in SIZE_INDEX:
                return (0, SIZE_INDEX[s], 0)
            # Numerik beden (36, 38, 40 …)
            try:
                return (0, 0, int(s))
            except ValueError:
                pass
            # S1, S2 … gibi sıralı etiketler
            import re as _re
            m = _re.match(r'^[A-Za-z]+(\d+)$', s)
            if m:
                return (0, 0, int(m.group(1)))
            return (1, 0, 0)  # bilinmeyen → sona
        return sorted(self.parsed_pieces.keys(), key=_sort_key)

    def detected_piece_types(self) -> List[str]:
        types = set()
        for size_pieces in self.parsed_pieces.values():
            types.update(size_pieces.keys())
        return sorted(types)
