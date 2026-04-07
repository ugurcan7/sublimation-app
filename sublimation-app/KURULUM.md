# Sublimasyon Forma Üretim Sistemi — Kurulum

## 1. Gereksinimler

- **Python 3.9+**  
  Mac: `brew install python` veya python.org'dan indirin
- **Cairo** (vector PDF için, opsiyonel ama önerilir)  
  Mac: `brew install cairo`  
  Ubuntu: `sudo apt-get install libcairo2`

---

## 2. Kurulum ve Başlatma

```bash
cd "sublimation-app"
chmod +x run.sh
./run.sh
```

`run.sh` otomatik olarak:
- `venv/` sanal ortamı oluşturur
- `requirements.txt` bağımlılıklarını kurar
- Sunucuyu http://localhost:8000 adresinde başlatır

---

## 3. Arayüze Erişim

| URL | Açıklama |
|-----|----------|
| http://localhost:8000/app | **Web arayüzü** |
| http://localhost:8000/docs | API dokümantasyonu |
| http://localhost:8000/redoc | Alternatif API dok. |

---

## 4. Demo PLT Dosyası Oluşturma

Gerçek PLT dosyanız yoksa demo oluşturabilirsiniz:

```bash
source venv/bin/activate
python demo_plt_generator.py
# demo_pastal.plt dosyası oluşturulur
```

Bu dosyayı arayüze yükleyebilirsiniz.

---

## 5. Kullanım Akışı

1. **PLT Yükle** → `demo_pastal.plt` veya kendi PLT dosyanızı yükleyin  
   - Sistem beden isimlerini (S, M, L, XL, XXL) ve parça tiplerini otomatik tespit eder
   
2. **Beden Seç** → Tasarımınızın hangi bedende olduğunu seçin (varsayılan: M)

3. **Tasarım Yükle** → Her parça için PNG/JPG görsel yükleyin:
   - Ön Panel
   - Arka Panel  
   - Sol Kol
   - Sağ Kol

4. **Üret & İndir** → "Tüm Bedenleri Üret" butonuna tıklayın  
   - Her beden için PDF oluşturulur (300 DPI)

---

## 6. API Doğrudan Kullanımı

```bash
# Oturum oluştur
curl -X POST "http://localhost:8000/session" \
  -F "reference_size=M"

# PLT yükle (SESSION_ID döndürür)
curl -X POST "http://localhost:8000/session/SESSION_ID/plt" \
  -F "file=@demo_pastal.plt"

# Tasarım yükle (her parça için)
curl -X POST "http://localhost:8000/session/SESSION_ID/design/front" \
  -F "file=@front_design.png"

# Grading çalıştır
curl -X POST "http://localhost:8000/session/SESSION_ID/grade" \
  -F "target_sizes=S,M,L,XL,XXL" \
  -F "bleed_mm=3" \
  -F "dpi=300"

# PDF indir
curl "http://localhost:8000/session/SESSION_ID/pdf/L" -o forma_L.pdf
```

---

## 7. Bağımlılıklar

| Paket | Amaç |
|-------|------|
| fastapi + uvicorn | Web sunucusu |
| numpy + scipy | Grading algoritması |
| shapely | Geometri işlemleri |
| svgwrite | SVG üretimi |
| cairosvg | SVG → PDF (vector) |
| Pillow | Görsel işleme |
| aiofiles | Async dosya işleme |

### PDF Kalitesi

- **cairosvg kuruluysa**: Gerçek vector PDF (sonsuz keskinlik)
- **cairosvg yoksa**: reportlab ile temel PDF (yeterli)
- Çok sayfalı birleştirme için: `pip install pypdf`

---

## 8. PLT Dosyası Formatı

Sistem şu HPGL komutlarını destekler:
- `IN` — Initialize
- `SP n` — Select Pen
- `PU x,y` — Pen Up (move)
- `PD x,y` — Pen Down (draw)
- `PA x,y` — Plot Absolute
- `PR x,y` — Plot Relative
- `LB text\003` — Label (beden/parça ismi)

**Etiket formatları otomatik tanınır:**
- `M-FRONT`, `L_BACK`, `XL SOL KOL`
- `FRONT-M`, `BACK L`, `RIGHT_SLEEVE_XL`

---

## 9. Grading Algoritması

```
1. PLT'deki referans beden (M) parçalarını al
2. En yakın büyük beden (L) ile karşılaştır
3. Her parçayı 300 noktaya yeniden örnekle (eşit yay uzunluğu)
4. Döngüsel hizalama ile en iyi başlangıç noktasını bul
5. Noktadan noktaya fark vektörlerini hesapla (GradingVectors)
6. Gürültü azaltma: hareketli ortalama (window=7)
7. Hedef beden için ölçekle:
   scale = (hedef_adım - referans_adım) / (karş_adım - referans_adım)
   graded_pts = ref_pts + grading_vectors * scale
```

---

## 10. Sorun Giderme

**"PLT'de parça bulunamadı"**  
→ PLT dosyasının HPGL formatında olduğundan emin olun  
→ `demo_plt_generator.py` ile test edin

**"Referans beden PLT'de bulunamadı"**  
→ PLT'deki beden etiketleri tanınmıyor olabilir  
→ Etiket formatını kontrol edin (örn: `M-FRONT`, `FRONT_M`)

**Grading hatalı görünüyor**  
→ PLT'deki parça sırası tutarsız olabilir  
→ `GET /session/{id}/grading-info` ile vektörleri kontrol edin

**PDF boş çıkıyor**  
→ `pip install cairosvg` ve `brew install cairo` yapın  
→ Alternatif: SVG dosyasını doğrudan kullanın
