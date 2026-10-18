# Manşet Masası — video deposu

Bu depo, Manşet Masası panelinin dikey haber videolarını (Instagram Reels, Facebook Reels, YouTube Shorts, Telegram) üretir.

## Kurulum (bir kez, ~10 dakika)

1. GitHub'da **herkese açık (Public)** yeni bir depo aç. Örnek adı: `manset-video`.
2. Bu klasördeki iki dosyayı yükle: `render.py` ve `.github/workflows/video.yml`.
   (GitHub'da "Add file → Upload files" ile klasörü sürükleyebilirsin.)
3. **Settings → Pages → Build and deployment → Source: GitHub Actions** seç.
4. **Settings → Secrets and variables → Actions → New repository secret**
   - Ad: `GCP_TTS_KEY`
   - Değer: Google Cloud Text-to-Speech API anahtarın.
   - Kendi videolarını bota gönderip paylaşacaksan ikinci bir secret ekle: Ad `TG_TOKEN`, değer: Telegram bot anahtarın.
     (Videoyu Telegram'dan indirmek için gerekir. Secret'lar loglarda görünmez.)
5. Panelde **Ayarlar → Video** bölümüne GitHub kullanıcı adını, depo adını ve erişim anahtarını (fine-grained token, bu depo için *Contents: Read and write*) yaz.

Videolar `https://KULLANICI.github.io/DEPO/v/` altında 3 gün durur, sonra kendiliğinden silinir.
Depo herkese açık olduğu için GitHub Actions dakikaları ücretsizdir.
