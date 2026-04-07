"""
HPGL/PLT Dosya Ayrıştırıcı — v2
=================================
Desteklenen komutlar: IN, SP, PU, PD, PA, PR, LB, CO, VS, SC

Kritik düzeltmeler (v2):
  - PU; (koordinatsız) artık path'ı kapatıyor
  - PA komutu kalem durumuna göre doğru çalışıyor
  - LB etiketi hem ÖNCE hem SONRA gelen path ile eşleşiyor
  - Koordinat ölçeği otomatik tespit ediliyor (bazı sistemler 40 unit/mm değil)
"""
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import numpy as np

from .models import PatternPiece, SIZE_ORDER, PIECE_ALIASES, SIZE_INDEX

logger = logging.getLogger(__name__)

# Bilinen beden tokenları
_RE_SIZE = re.compile(
    r'\b(XXS|XS|XXXL|XXL|XL|[SML]|[2-5]XL)\b', re.IGNORECASE
)
_RE_PIECE = re.compile(
    r'\b(front|back|arka|[oö]n|sol[_ ]?kol|sa[gğ][_ ]?kol|'
    r'left[_ ]?sleeve|right[_ ]?sleeve|lsleeve|rsleeve|'
    r'sleeve[_ ]?[lr]|piece[1-4]|[fb][12]?|ls|rs)\b',
    re.IGNORECASE
)

HPGL_UNITS_PER_MM = 40.0
MIN_POINTS = 4
MIN_AREA_MM2 = 500.0


# ─── Parser ──────────────────────────────────────────────────────────────────

class PLTParser:
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self._cx = 0.0
        self._cy = 0.0
        self._pen_down = False
        self._current_path: List[Tuple[float, float]] = []
        # (points, label_before, label_after)
        self._paths: List[Tuple[List[Tuple[float, float]], str]] = []
        self._pending_label: str = ""
        self._scale = HPGL_UNITS_PER_MM  # otomatik düzeltilecek

    def parse(self) -> List[PatternPiece]:
        raw = self.filepath.read_bytes().decode("latin-1", errors="replace")
        raw = raw.replace('\r', '').replace('\x00', '')

        tokens = self._tokenize(raw)
        self._process(tokens)

        # Ölçeği tespit et
        all_coords = [pt for pts, _ in self._paths for pt in pts]
        if all_coords:
            xs = [c[0] for c in all_coords]
            ys = [c[1] for c in all_coords]
            coord_range = max(max(xs) - min(xs), max(ys) - min(ys))
            # Tipik forma ön = ~500mm → 500*40 = 20000 HPGL unit
            # Eğer max koordinat 5000'den küçükse muhtemelen 1 unit/mm
            if coord_range > 0:
                if coord_range < 5000:
                    self._scale = 1.0  # 1 unit = 1mm
                    logger.info(f"Koordinat ölçeği: 1 unit/mm (aralık={coord_range:.0f})")
                elif coord_range < 1_000_000:
                    self._scale = HPGL_UNITS_PER_MM  # 40 unit/mm (standart HPGL)
                    logger.info(f"Koordinat ölçeği: 40 unit/mm (aralık={coord_range:.0f})")
                else:
                    self._scale = HPGL_UNITS_PER_MM * 10  # 400 unit/mm (yüksek çözünürlük)
                    logger.info(f"Koordinat ölçeği: 400 unit/mm (aralık={coord_range:.0f})")

        pieces = self._build_pieces()
        logger.info(f"PLT: {len(pieces)} geçerli parça ({self.filepath.name})")
        return pieces

    # ── Tokenizer ─────────────────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        HPGL komutlarını tokenlara ayır.
        Hem ';' hem '\n' separator olarak kullanılır.
        LB komutu özel: ';' değil '\x03' (ETX) ile biter.
        """
        tokens: List[str] = []
        i = 0
        buf = ""
        while i < len(text):
            ch = text[i]
            if ch == ';' or ch == '\n':
                t = buf.strip()
                if t:
                    tokens.append(t)
                buf = ""
            elif buf.upper().startswith("LB"):
                # LB komutu: ETX (\x03) veya satır sonu ile biter
                # Zaten "LB" bufferda — devam et
                if ch == '\x03':
                    tokens.append(buf.strip())
                    buf = ""
                else:
                    buf += ch
            else:
                buf += ch
            i += 1
        if buf.strip():
            tokens.append(buf.strip())
        return tokens

    # ── Token işleyici ────────────────────────────────────────────────────────

    def _process(self, tokens: List[str]) -> None:
        for tok in tokens:
            if not tok:
                continue
            up = tok.upper()
            cmd = up[:2]

            if cmd == 'IN':
                self._finish_path()

            elif cmd == 'SP':
                # Yeni kalem = yeni parça
                self._finish_path()

            elif cmd == 'PU':
                # Kalemi kaldır — her zaman path'ı bitir
                self._finish_path()
                self._pen_down = False
                coords = _parse_coords(tok[2:])
                if coords:
                    self._cx, self._cy = coords[-1]

            elif cmd == 'PD':
                coords = _parse_coords(tok[2:])
                if coords:
                    if not self._current_path:
                        # Path başlangıcı: mevcut konumu ilk nokta olarak ekle
                        self._current_path.append((self._cx, self._cy))
                    for x, y in coords:
                        self._cx, self._cy = x, y
                        self._current_path.append((x, y))
                self._pen_down = True

            elif cmd == 'PA':
                coords = _parse_coords(tok[2:])
                if coords:
                    if self._pen_down:
                        if not self._current_path:
                            self._current_path.append((self._cx, self._cy))
                        for x, y in coords:
                            self._cx, self._cy = x, y
                            self._current_path.append((x, y))
                    else:
                        # Kalem yukarı → sadece konumu güncelle
                        self._finish_path()
                        self._cx, self._cy = coords[-1]

            elif cmd == 'PR':
                coords = _parse_coords(tok[2:])
                if coords:
                    if not self._current_path and self._pen_down:
                        self._current_path.append((self._cx, self._cy))
                    for dx, dy in coords:
                        self._cx += dx
                        self._cy += dy
                        if self._pen_down:
                            self._current_path.append((self._cx, self._cy))

            elif cmd == 'LB':
                label = re.sub(r'\\003|\x03', '', tok[2:]).strip()
                self._pending_label = label
                # Etiket path'tan ÖNCE mi SONRA mı geldi?
                # Sonra gelen etiket: son path'ı güncelle
                if self._paths and not self._current_path:
                    last_pts, _ = self._paths[-1]
                    self._paths[-1] = (last_pts, label)
                    self._pending_label = ""

            # Yoksay
            elif cmd in ('CO', 'VS', 'SC', 'SI', 'DI', 'DR', 'SR', 'SL', 'TD', 'RO'):
                pass

    def _finish_path(self) -> None:
        pts = self._current_path
        self._current_path = []
        if len(pts) < MIN_POINTS:
            return

        # Poligonu kapat (son nokta ≠ ilk nokta ise ekle)
        if not _points_close(pts[0], pts[-1]):
            pts.append(pts[0])

        # Tekrarlayan noktaları temizle
        deduped = [pts[0]]
        for p in pts[1:]:
            if not _points_close(deduped[-1], p):
                deduped.append(p)

        if len(deduped) >= MIN_POINTS:
            self._paths.append((deduped, self._pending_label))
            self._pending_label = ""

    def _build_pieces(self) -> List[PatternPiece]:
        pieces = []
        for pts, label in self._paths:
            arr = np.array(pts, dtype=float) / self._scale  # → mm
            tmp = PatternPiece(label=label, size="", piece_type="", points=arr)
            if tmp.area() < MIN_AREA_MM2:
                continue
            size, ptype = _parse_label(label)
            pieces.append(PatternPiece(label=label, size=size, piece_type=ptype, points=arr))

        _infer_missing_metadata(pieces)
        return pieces


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def _parse_coords(text: str) -> List[Tuple[float, float]]:
    nums = re.findall(r'[-+]?\d*\.?\d+', text)
    pairs = []
    for k in range(0, len(nums) - 1, 2):
        try:
            pairs.append((float(nums[k]), float(nums[k+1])))
        except ValueError:
            pass
    return pairs


def _points_close(a, b, tol=1.0) -> bool:
    return abs(a[0]-b[0]) < tol and abs(a[1]-b[1]) < tol


def _parse_label(label: str) -> Tuple[str, str]:
    # Strip both actual ETX (\x03) and literal backslash-003 string
    clean = re.sub(r'\\003|\x03', '', label).strip()
    upper = clean.upper()
    m = _RE_SIZE.search(upper)
    size = m.group(1).upper() if m else ""

    m2 = _RE_PIECE.search(clean)
    raw = m2.group(1).lower() if m2 else ""
    ptype = PIECE_ALIASES.get(raw, raw or "unknown")
    return size, ptype


# ─── Metadata tahmini ────────────────────────────────────────────────────────

def _infer_missing_metadata(pieces: List[PatternPiece]) -> None:
    """
    Etiket yoksa veya eksikse geometriden tamamla.

    Beden tahmini:
      - Etiketlerde beden var → kullan
      - Yok → parçaları alana göre sırala, eşit gruplar = farklı bedenler

    Parça tipi tahmini (EN GÜVENİLİR YÖNTEM):
      - Her beden grubunda parçaları alana göre sırala (büyükten küçüğe)
      - Rank 0 → front  (en büyük)
      - Rank 1 → back
      - Rank 2 → left_sleeve
      - Rank 3 → right_sleeve
    """
    # Zaten tipi olan parçaları atla
    needs_type  = [p for p in pieces if p.piece_type in ("", "unknown")]
    needs_size  = [p for p in pieces if not p.size]

    # ── Beden tahmini ──────────────────────────────────────────────────────
    if needs_size:
        known_sizes = set(p.size for p in pieces if p.size)
        if not known_sizes:
            # Hiç etiket yok: parçaları gruplara ayır
            _assign_sizes_by_clustering(pieces)
        else:
            # Bazı bedenler biliniyor — bilinmeyenleri sona ekle
            for p in needs_size:
                p.size = "M"  # varsayılan

    # ── Parça tipi tahmini ─────────────────────────────────────────────────
    if needs_type:
        # Beden bazında grupla
        size_groups: Dict[str, List[PatternPiece]] = {}
        for p in pieces:
            size_groups.setdefault(p.size, []).append(p)

        for size, group in size_groups.items():
            unknowns = [p for p in group if p.piece_type in ("", "unknown")]
            if not unknowns:
                continue
            # Alan büyükten küçüğe sırala
            unknowns.sort(key=lambda p: p.area(), reverse=True)
            type_order = ["front", "back", "left_sleeve", "right_sleeve"]
            for i, p in enumerate(unknowns):
                p.piece_type = type_order[i % 4]
            logger.info(
                f"Beden {size}: {len(unknowns)} parça alan sıralamasıyla atandı "
                f"({[p.piece_type for p in unknowns]})"
            )


def _assign_sizes_by_clustering(pieces: List[PatternPiece]) -> None:
    """
    Etiket hiç yoksa: parçaları alana göre sırala ve gruplara böl.
    Tipik: 4 parça/beden (front, back, sol kol, sağ kol)
    """
    N_PER_SIZE = 4
    n = len(pieces)
    if n == 0:
        return

    # Alana göre sırala
    sorted_pieces = sorted(pieces, key=lambda p: p.area())
    n_sizes = max(1, n // N_PER_SIZE)

    # Mevcut boyut sırası: S, M, L, XL, XXL
    start_idx = max(0, 3 - n_sizes // 2)  # M etrafında merkezle
    size_candidates = SIZE_ORDER[start_idx:start_idx + n_sizes]

    for i, p in enumerate(sorted_pieces):
        size_idx = min(i // N_PER_SIZE, len(size_candidates) - 1)
        p.size = size_candidates[size_idx]


def group_pieces(pieces: List[PatternPiece]) -> Dict[str, Dict[str, PatternPiece]]:
    """
    Parçaları {size: {piece_type: PatternPiece}} olarak grupla.
    Aynı size+type için en büyük alanı al.
    """
    result: Dict[str, Dict[str, PatternPiece]] = {}
    for piece in pieces:
        if not piece.size:
            continue
        sg = result.setdefault(piece.size, {})
        ex = sg.get(piece.piece_type)
        if ex is None or piece.area() > ex.area():
            sg[piece.piece_type] = piece
    return result
