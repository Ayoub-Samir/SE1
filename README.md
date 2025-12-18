# Yatırım Programı Revizyon Talebi – Ödev Uygulaması

Bu proje, sunumdaki **“Yatırım Programı Revizyon Talebi”** senaryosunu uçtan uca çalışan bir demo olarak gerçekleştirir.
Kurumsal mimaride geçen bileşenler (Nextcloud, n8n, LiteLLM/Ollama, Mattermost, Appflowy, Presenton, Superset) burada **hafif bir “tek uygulama” prototip** ile simüle edilmiştir; istenirse webhook’larla gerçek sistemlere bağlanacak şekilde genişletilebilir.

## Senaryo Akışı (Sunumdaki adımlarla eşleştirme)

1. **Dosya yükleme (Nextcloud benzeri)**: Kullanıcı revizyon talebini `Upload` sayfasından yükler.
2. **OCR / metin çıkarma**: PDF’den metin çıkarılır (metin yoksa OCR opsiyoneldir).
3. **AI ile bilgi çıkarımı (LiteLLM/Ollama benzeri)**: Metinden `proje_kodu`, `talep_tutarı`, `gerekçe` alanları çıkarılır (varsayılan: kural tabanlı; opsiyonel: OpenAI API).
4. **Proje sorgusu + risk analizi (Knime benzeri)**: Örnek proje veritabanından bütçe/harcama çekilir, risk puanı hesaplanır.
5. **Bildirim (Mattermost benzeri)**: İstenirse Mattermost Incoming Webhook’a mesaj atılır.
6. **Onay/Red (Mattermost butonları / Appflowy kayıt)**: Web arayüzünden Onay/Red verilir; karar kayıt altına alınır (Markdown “bilgi bankası”).
7. **YPK sunumu üretimi (Presenton benzeri)**: Onaylanan talepler için sunum çıktısı üretilir (varsayılan: Markdown; opsiyonel: PPTX).
8. **Dashboard güncelleme (Superset benzeri)**: Basit bir dashboard sayfasında talepler ve projeler görüntülenir.

## Kurulum

Bu repo Python 3.12 ile çalışır.

### 1) Bağımlılıklar

`requirements.txt` içeriğini kurun:

```powershell
python -m pip install -r requirements.txt
```

PPTX üretimi için (opsiyonel):

```powershell
python -m pip install -r requirements-pptx.txt
```

> Not: `python-pptx` kurulu değilse sunum çıktısı Markdown olarak üretilecektir.

### 2) Ortam değişkenleri

`.env.example` dosyasını `.env` olarak kopyalayın ve gerekirse düzenleyin.

### 3) Çalıştırma

```powershell
python -m uvicorn app.main:app --reload
```

Arayüz: `http://127.0.0.1:8000`

### Docker (opsiyonel)

```powershell
docker build -t revizyon-demo .
docker run -p 8000:8000 revizyon-demo
```

## Demo İçin Örnek Dosya

Örnek bir revizyon talebi PDF’i üretmek için:

```powershell
python scripts/generate_sample_pdf.py
```

Oluşan dosyayı `Upload` ekranından yükleyebilirsiniz.

## Hosting (Herhangi bir hosting)

Bu uygulama **stateless** çalışır; fakat demo için dosyaları ve SQLite DB’yi yerelde tutar. Bulutta:

- **Render/Railway/Fly.io**: Dockerfile ekleyerek veya Python web service olarak deploy edebilirsiniz.
- Dosya ve DB kalıcılığı isteniyorsa:
  - `DATA_DIR` kalıcı disk (volume) üzerinde olmalı,
  - ya da SQLite yerine Postgres’e geçilmelidir.

## Render Deploy (Önerilen)

1) Bu klasörü GitHub’a push edin (public/private fark etmez).

2) Render’da:
- **New → Web Service** (veya **New → Blueprint** ile `render.yaml`)
- Repo’yu seçin
- Eğer Docker seçeneği sorarsa: **Docker** (repo’daki `Dockerfile` kullanılacak)
- **Port**: `8000` (Blueprint ile kuruyorsanız `render.yaml` içinde `PORT=8000` hazır)

3) Render → Environment:
- `LLM_PROVIDER=mock` (varsayılan)
- `APP_BASE_URL=https://<service-adın>.onrender.com`
- (opsiyonel, kalıcı disk kullanıyorsanız) `DATA_DIR`, `STORAGE_DIR`, `OUTPUT_DIR` değerlerini disk mount path altına verin (örn. `/var/data/...`).

Deploy bitince uygulama URL’nizi açıp `/dashboard` ve `/upload` ile test edin.

## Dizin Yapısı

- `app/`: FastAPI uygulaması
- `templates/`: HTML arayüz şablonları
- `static/`: basit CSS
- `data/`: örnek proje seed + uygulama DB
- `storage/`: yüklenen dosyalar
- `outputs/`: üretilen sunum/çıktılar
