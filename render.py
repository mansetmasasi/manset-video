#!/usr/bin/env python3
"""
Manşet Masası — dikey haber videosu üretici (Reels / Shorts / TikTok, 1080x1920).

Girdi: GitHub repository_dispatch ile gelen JSON (payload.json).
  id          : video kimliği (dosya adı)
  slaytlar    : haber kartı görsellerinin adresleri (Google Slaytlar küçük resimleri, ~30 dk geçerli)
  cumleler    : seslendirme cümleleri
  ses         : Google Cloud TTS ses adı (örn. tr-TR-Wavenet-E)
  hiz         : konuşma hızı (0.8 - 1.3)
  kanal       : kanal adı (üst şerit)
  kategori    : üst şeritte kırmızı etiket

Çıktı (site/v/ klasörüne):
  <id>.mp4   H.264 + AAC 48 kHz stereo, 30 fps, +faststart (Instagram ve Facebook Reels şartları)
  <id>.jpg   kapak
  <id>.json  {"ok": true, "sure": 27.4, ...}  ya da  {"ok": false, "hata": "..."}

Seslendirme:
  GCP_TTS_KEY varsa Google Cloud Text-to-Speech (SSML <mark> ile cümle zamanları).
  Yoksa ücretsiz, açık kaynak Piper (GitHub sunucusunda çalışır; kart, hesap, ödeme istemez).
    PIPER_DIR : piper programının klasörü (iş akışı indirir)
    PIPER_SES : ses modeli (varsayılan tr_TR-fahrettin-medium)
TEST_SES=1 ise ses yerine sessizlik üretir (yerel deneme için).
"""
import base64
import html
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

W, H, FPS = 1080, 1920, 30
KUTU_Y = 380            # haber kartının üst kenarı
KART_W = 1000           # kart genişliği (16:9 → 562 yükseklik)
ALTYAZI_Y = 1080        # altyazının üst kenarı
YAZI = os.environ.get('YAZI_ADI', 'Barlow Condensed')


def calistir(komut):
    r = subprocess.run(komut, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError('Komut başarısız: ' + ' '.join(komut[:3]) + ' … ' + r.stderr[-800:])
    return r.stdout


def indir(url, yol, deneme=3):
    son = None
    for i in range(deneme):
        try:
            istek = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (MansetMasasi video)'})
            with urllib.request.urlopen(istek, timeout=60) as y, open(yol, 'wb') as f:
                f.write(y.read())
            if os.path.getsize(yol) < 1000:
                raise RuntimeError('görsel çok küçük')
            return
        except Exception as e:  # noqa: BLE001
            son = e
            time.sleep(2 * (i + 1))
    raise RuntimeError('Görsel indirilemedi (adresin süresi dolmuş olabilir): ' + str(son))


def sure(yol):
    return float(calistir(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', yol]).strip())


def ssml(cumleler):
    parca = ''.join('<mark name="c%d"/>%s ' % (i, html.escape(c, quote=False)) for i, c in enumerate(cumleler))
    return '<speak>' + parca + '<mark name="son"/></speak>'


PIPER_SESLER = ['tr_TR-fahrettin-medium', 'tr_TR-fettah-medium', 'tr_TR-dfki-medium']
PIPER_ARA = 0.28        # cümleler arası sessizlik (sn)


def motor():
    if os.environ.get('TEST_SES') == '1':
        return 'test'
    return 'google' if os.environ.get('GCP_TTS_KEY') else 'piper'


def piper_model(klasor, ad):
    """Ses modelini (yoksa) Hugging Face'teki resmî Piper ses deposundan indirir."""
    m = re.match(r'^([a-z]{2})_([A-Z]{2})-([a-z0-9_]+)-(x_low|low|medium|high)$', ad)
    if not m:
        raise RuntimeError('Geçersiz Piper ses adı: ' + ad)
    os.makedirs(klasor, exist_ok=True)
    yol = os.path.join(klasor, ad + '.onnx')
    temel = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/%s/%s_%s/%s/%s/%s' % (
        m.group(1), m.group(1), m.group(2), m.group(3), m.group(4), ad)
    for uz in ('.onnx.json', '.onnx'):
        hedef = yol[:-5] + uz
        if os.path.exists(hedef) and os.path.getsize(hedef) > 1000:
            continue
        son = None
        for i in range(3):
            try:
                istek = urllib.request.Request(temel + uz, headers={'User-Agent': 'MansetMasasi video'})
                with urllib.request.urlopen(istek, timeout=120) as y, open(hedef + '.tmp', 'wb') as f:
                    f.write(y.read())
                os.replace(hedef + '.tmp', hedef)
                son = None
                break
            except Exception as e:  # noqa: BLE001
                son = e
                time.sleep(3 * (i + 1))
        if son:
            raise RuntimeError('Piper sesi indirilemedi (%s): %s' % (ad, son))
    return yol


def piper_seslendir(cumleler, hiz, yol):
    """Her cümleyi ayrı okutur, aralarına kısa sessizlik koyup birleştirir. Cümle zamanları kesin bilinir."""
    kok = os.environ.get('PIPER_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'piper'))
    program = os.path.join(kok, 'piper')
    if not os.path.exists(program):
        raise RuntimeError('Piper bulunamadı (%s). İş akışı dosyası (video.yml) güncel mi?' % program)
    istenen = os.environ.get('PIPER_SES') or PIPER_SESLER[0]
    adaylar = [istenen] + [s for s in PIPER_SESLER if s != istenen]
    model, son = None, None
    for ad in adaylar:
        try:
            model = piper_model(os.path.join(kok, 'sesler'), ad)
            break
        except Exception as e:  # noqa: BLE001
            son = e
    if not model:
        raise RuntimeError(str(son))
    klasor = os.path.dirname(os.path.abspath(yol))
    parcalar, baslar, t = [], [], 0.0
    for i, c in enumerate(cumleler):
        p = os.path.join(klasor, 'p%02d.wav' % i)
        r = subprocess.run([program, '--model', model, '--output_file', p, '--length_scale', '%.3f' % (1.0 / hiz),
                            '--sentence_silence', '0', '--quiet'],
                           input=c.strip() + '\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0 or not os.path.exists(p) or os.path.getsize(p) < 100:
            raise RuntimeError('Piper seslendiremedi: ' + (r.stderr or '')[-400:])
        baslar.append(round(t, 3))
        t += sure(p) + PIPER_ARA
        parcalar.append(p)
    girdiler, filtre = [], ''
    for i, p in enumerate(parcalar):
        girdiler += ['-i', p]
        filtre += '[%d:a]aresample=48000,apad=pad_dur=%.2f[a%d];' % (i, PIPER_ARA, i)
    filtre += ''.join('[a%d]' % i for i in range(len(parcalar))) + 'concat=n=%d:v=0:a=1,loudnorm=I=-16:TP=-1.5:LRA=11[s]' % len(parcalar)
    calistir(['ffmpeg', '-y', '-v', 'error'] + girdiler + ['-filter_complex', filtre, '-map', '[s]',
              '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', yol])
    return baslar


def seslendir(cumleler, ses, hiz, yol):
    """WAV üretir; her cümlenin başlangıç saniyesini döndürür (bilinmiyorsa None)."""
    if motor() == 'piper':
        return piper_seslendir(cumleler, hiz, yol)
    if motor() == 'test':
        toplam = sum(max(1.2, len(c) * 0.065) for c in cumleler)
        calistir(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '%.2f' % toplam, yol])
        return None
    govde = {
        'input': {'ssml': ssml(cumleler)},
        'voice': {'languageCode': 'tr-TR', 'name': ses},
        'audioConfig': {'audioEncoding': 'LINEAR16', 'sampleRateHertz': 48000, 'speakingRate': hiz},
        'enableTimePointing': ['SSML_MARK'],
    }
    url = 'https://texttospeech.googleapis.com/v1beta1/text:synthesize?key=' + os.environ['GCP_TTS_KEY']
    istek = urllib.request.Request(url, data=json.dumps(govde).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(istek, timeout=90) as y:
            j = json.loads(y.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('Seslendirme hatası %s: %s' % (e.code, e.read().decode('utf-8', 'ignore')[:300]))
    with open(yol, 'wb') as f:
        f.write(base64.b64decode(j['audioContent']))
    zamanlar = {t.get('markName'): float(t.get('timeSeconds', 0)) for t in j.get('timepoints', [])}
    if all(('c%d' % i) in zamanlar for i in range(len(cumleler))):
        return [zamanlar['c%d' % i] for i in range(len(cumleler))]
    return None


def oransal_zamanlar(cumleler, toplam):
    uz = [max(8, len(c)) for c in cumleler]
    t, cikti = 0.0, []
    for u in uz:
        cikti.append(t)
        t += toplam * u / sum(uz)
    return cikti


def parcala(cumle, en_fazla=6):
    """Altyazı okunaklı olsun diye uzun cümleyi en fazla 6 kelimelik parçalara böler."""
    k = cumle.split()
    if len(k) <= en_fazla + 2:
        return [cumle]
    n = math.ceil(len(k) / en_fazla)
    boy = math.ceil(len(k) / n)
    return [' '.join(k[i:i + boy]) for i in range(0, len(k), boy)]


def ass_zaman(s):
    s = max(0.0, s)
    return '%d:%02d:%02d.%02d' % (int(s // 3600), int(s % 3600 // 60), int(s % 60), int(round((s - int(s)) * 100)) % 100)


def ass_kacis(s):
    return s.replace('\\', '').replace('{', '(').replace('}', ')').replace('\n', ' ')


def ass_yaz(yol, cumleler, baslar, toplam, kanal, kategori, not_metni='Seslendirme: yapay zekâ · Kaynaklar açıklamada'):
    satir = [
        '[Script Info]', 'ScriptType: v4.00+', 'PlayResX: %d' % W, 'PlayResY: %d' % H, 'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '',
        '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
        'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        # Renkler &HAABBGGRR
        'Style: Altyazi,%s,92,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,2,8,70,70,%d,1' % (YAZI, ALTYAZI_Y),
        'Style: Kategori,%s,46,&H002F41E0,&H002F41E0,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,2,1,7,60,60,150,1' % (YAZI,),
        'Style: Kanal,%s,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,1,0,1,2,1,9,60,60,150,1' % (YAZI,),
        'Style: Not,%s,34,&H00B2A08C,&H00B2A08C,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,2,1,2,60,60,120,1' % (YAZI,),
        '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]
    son = ass_zaman(toplam)
    satir.append('Dialogue: 0,0:00:00.00,%s,Kategori,,0,0,0,,%s' % (son, ass_kacis(kategori.upper())))
    satir.append('Dialogue: 0,0:00:00.00,%s,Kanal,,0,0,0,,%s' % (son, ass_kacis(kanal)))
    satir.append('Dialogue: 0,0:00:00.00,%s,Not,,0,0,0,,%s' % (son, ass_kacis(not_metni)))
    for i, c in enumerate(cumleler):
        bas = baslar[i]
        bit = baslar[i + 1] if i + 1 < len(cumleler) else toplam - 0.3
        parcalar = parcala(c)
        uz = [max(4, len(p)) for p in parcalar]
        t = bas
        for p, u in zip(parcalar, uz):
            d = (bit - bas) * u / sum(uz)
            # Okunan parça beyaz, kısa bir büyüme efektiyle girer
            satir.append('Dialogue: 1,%s,%s,Altyazi,,0,0,0,,{\\fad(80,40)\\t(0,120,\\fscx104\\fscy104)\\t(120,220,\\fscx100\\fscy100)}%s'
                         % (ass_zaman(t), ass_zaman(t + d), ass_kacis(p)))
            t += d
    with open(yol, 'w', encoding='utf-8') as f:
        f.write('\n'.join(satir) + '\n')


def slayt_klibi(girdi, sure_sn, cikti, yakinlas):
    kare = max(1, int(round(sure_sn * FPS)))
    z = "min(1.0+%.5f*on,1.04)" % (0.04 / kare) if yakinlas else '1.0'
    calistir([
        'ffmpeg', '-y', '-v', 'error', '-loop', '1', '-i', girdi,
        '-vf', "scale=1600:900:force_original_aspect_ratio=increase,crop=1600:900,"
               "zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,format=yuv420p"
               % (z, kare, KART_W, int(KART_W * 9 / 16) // 2 * 2, FPS),
        '-frames:v', str(kare), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', cikti
    ])


def uret(p, klasor, cikti_klasor):
    vid = re.sub(r'[^A-Za-z0-9_\-]', '', str(p['id']))[:60]
    if not vid:
        raise RuntimeError('Geçersiz video kimliği.')
    cumleler = [c.strip() for c in p.get('cumleler', []) if c and c.strip()][:14]
    if not cumleler:
        raise RuntimeError('Seslendirme metni boş.')
    slaytlar = [u for u in p.get('slaytlar', []) if u][:3]
    if not slaytlar:
        raise RuntimeError('Kart görseli yok.')
    os.makedirs(cikti_klasor, exist_ok=True)

    resimler = []
    for i, u in enumerate(slaytlar):
        yol = os.path.join(klasor, 's%d.png' % i)
        indir(u, yol)
        resimler.append(yol)

    ses = os.path.join(klasor, 'ses.wav')
    hiz = min(1.3, max(0.8, float(p.get('hiz') or 1.08)))
    baslar = seslendir(cumleler, p.get('ses') or 'tr-TR-Wavenet-E', hiz, ses)
    ses_suresi = sure(ses)
    toplam = round(ses_suresi + 0.8, 2)
    if toplam < 5:
        toplam = 5.0
    if toplam > 89:
        raise RuntimeError('Video 90 saniyeyi aşıyor (%.0f sn). Seslendirmeyi kısalt.' % toplam)
    if baslar is None:
        baslar = oransal_zamanlar(cumleler, ses_suresi)

    # Slaytları cümle gruplarına böl: kapak → ne oldu → neden önemli
    n = len(resimler)
    sinirlar = [0.0]
    for k in range(1, n):
        idx = min(len(cumleler) - 1, max(1, round(len(cumleler) * k / n)))
        sinirlar.append(baslar[idx])
    sinirlar.append(toplam)
    klipler = []
    for i, r in enumerate(resimler):
        d = max(0.5, sinirlar[i + 1] - sinirlar[i])
        k = os.path.join(klasor, 'k%d.mp4' % i)
        slayt_klibi(r, d, k, True)
        klipler.append(k)
    liste = os.path.join(klasor, 'liste.txt')
    with open(liste, 'w') as f:
        f.write(''.join("file '%s'\n" % os.path.abspath(k) for k in klipler))
    kart = os.path.join(klasor, 'kart.mp4')
    calistir(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', liste, '-c', 'copy', kart])

    # İsteğe bağlı: Pexels'ten habere uygun temsilî arka plan görüntüleri (yoksa düz lacivert zemin)
    zemin = arka_plan(p.get('arkaplan') or [], sinirlar, toplam, klasor)
    not_metni = 'Seslendirme: yapay zekâ · Kaynaklar açıklamada'
    if zemin:
        kredi = [k for k in (p.get('kredi') or []) if k][:2]
        not_metni = 'Temsilî görüntü: Pexels' + (' / ' + ', '.join(kredi) if kredi else '') + ' · Seslendirme: yapay zekâ'

    ass = os.path.join(klasor, 'altyazi.ass')
    ass_yaz(ass, cumleler, baslar, toplam, str(p.get('kanal') or ''), str(p.get('kategori') or 'gündem'), not_metni)
    yazi_klasoru = os.environ.get('YAZI_KLASORU', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yazi'))

    mp4 = os.path.join(cikti_klasor, vid + '.mp4')
    kart_h = int(KART_W * 9 / 16) // 2 * 2
    zemin_filtre = ("[2:v]setpts=PTS-STARTPTS[zemin];" if zemin else "color=c=0x0F1B2D:s=%dx%d:r=%d:d=%.2f[zemin];" % (W, H, FPS, toplam))
    filtre = (
        zemin_filtre +
        "color=c=0xE0412F:s=%dx10:r=%d:d=%.2f[serit];" % (W, FPS, toplam) +
        "color=c=0x1C2C44:s=%dx%d:r=%d:d=%.2f[cerceve];" % (KART_W + 16, kart_h + 16, FPS, toplam) +
        "[zemin][cerceve]overlay=x=%d:y=%d[a];" % ((W - KART_W - 16) // 2, KUTU_Y - 8) +
        "[a][0:v]overlay=x=%d:y=%d:shortest=1[b];" % ((W - KART_W) // 2, KUTU_Y) +
        # İlerleme çubuğu: soldan sağa dolar (izleyici videonun ne kadar süreceğini görür)
        "[b][serit]overlay=x='-W+W*t/%.2f':y=%d[c];" % (toplam, H - 10) +
        "[c]ass='%s':fontsdir='%s'[v]" % (ass.replace("'", ''), yazi_klasoru.replace("'", ''))
    )
    calistir([
        'ffmpeg', '-y', '-v', 'error', '-i', kart, '-i', ses] + (['-i', zemin] if zemin else []) + [
        '-filter_complex', filtre, '-map', '[v]', '-map', '1:a',
        '-af', 'apad', '-t', '%.2f' % toplam,
        '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', str(FPS * 2),
        '-preset', 'medium', '-crf', '23', '-maxrate', '2500k', '-bufsize', '5000k',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2',
        '-movflags', '+faststart', mp4
    ])
    jpg = os.path.join(cikti_klasor, vid + '.jpg')
    calistir(['ffmpeg', '-y', '-v', 'error', '-ss', '0.6', '-i', mp4, '-frames:v', '1', '-q:v', '3', jpg])
    boyut = os.path.getsize(mp4)
    if boyut > 19.5 * 1024 * 1024:
        raise RuntimeError('Video 20 MB sınırını aşıyor (%.1f MB).' % (boyut / 1048576))
    return {'ok': True, 'id': vid, 'sure': toplam, 'boyut': boyut, 'cumle': len(cumleler),
            # Google ücretli olabilir → karakter sayılır; Piper ücretsiz → 0 (panel harcama yazmaz)
            'karakter': sum(len(c) for c in cumleler) if motor() == 'google' else 0, 'zaman': int(time.time()),
            'zamanlama': {'google': 'tts', 'piper': 'piper'}.get(motor(), 'test'), 'motor': motor(),
            'arkaplan': bool(zemin)}


def arka_plan(adresler, sinirlar, toplam, klasor):
    """Her slayt bölümü için bir klip: dikey kırpılır, karartılır (yazı okunsun), sessiz. Hata olursa None (düz zemin)."""
    adresler = [a for a in adresler if a][:3]
    if not adresler:
        return None
    try:
        kaynak = []
        for i, u in enumerate(adresler):
            yol = os.path.join(klasor, 'ap%d.mp4' % i)
            try:
                indir(u, yol, deneme=2)
                kaynak.append(yol)
            except Exception:  # noqa: BLE001
                continue
        if not kaynak:
            return None
        parcalar = []
        for i in range(len(sinirlar) - 1):
            d = max(0.5, sinirlar[i + 1] - sinirlar[i])
            cikti = os.path.join(klasor, 'apk%d.mp4' % i)
            calistir(['ffmpeg', '-y', '-v', 'error', '-stream_loop', '-1', '-i', kaynak[i % len(kaynak)], '-t', '%.3f' % d, '-an',
                      '-vf', 'scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,eq=brightness=-0.22:saturation=0.85,fps=%d,format=yuv420p' % (W, H, W, H, FPS),
                      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', cikti])
            parcalar.append(cikti)
        liste = os.path.join(klasor, 'ap-liste.txt')
        with open(liste, 'w') as f:
            f.write(''.join("file '%s'\n" % os.path.abspath(k) for k in parcalar))
        zemin = os.path.join(klasor, 'zemin.mp4')
        calistir(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', liste, '-c', 'copy', zemin])
        return zemin
    except Exception as e:  # noqa: BLE001
        print('Arka plan kullanılamadı, düz zemin:', e)
        return None


def telegram_indir(file_id, yol):
    """Kanal sahibinin bota gönderdiği videoyu indirir (Telegram bot API: en fazla 20 MB)."""
    token = os.environ.get('TG_TOKEN')
    if not token:
        raise RuntimeError('TG_TOKEN tanımlı değil (GitHub → Settings → Secrets → Actions).')
    with urllib.request.urlopen('https://api.telegram.org/bot%s/getFile?file_id=%s' % (token, urllib.parse.quote(file_id)), timeout=60) as y:
        j = json.loads(y.read().decode('utf-8'))
    if not j.get('ok'):
        raise RuntimeError('Telegram dosyayı vermedi: ' + str(j.get('description', ''))[:200])
    indir('https://api.telegram.org/file/bot%s/%s' % (token, j['result']['file_path']), yol)


def ses_var_mi(yol):
    return bool(calistir(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', yol]).strip())


def kendi_uret(p, klasor, cikti_klasor):
    """Kanal sahibinin kendi videosu: dikey 1080x1920'e oturtulur (yatay videoda bulanık zemin), en fazla 89 sn,
    üstte kanal şeridi, altta 'Kanal görüntüsü' notu. Orijinal ses korunur."""
    vid = re.sub(r'[^A-Za-z0-9_\-]', '', str(p['id']))[:60]
    if not vid:
        raise RuntimeError('Geçersiz video kimliği.')
    ham = os.path.join(klasor, 'ham.mp4')
    if p.get('dosya_url'):
        indir(p['dosya_url'], ham)
    else:
        telegram_indir(str(p.get('file_id') or ''), ham)
    toplam = min(89.0, round(sure(ham), 2))
    if toplam < 3:
        raise RuntimeError('Video 3 saniyeden kısa.')
    ass = os.path.join(klasor, 'kendi.ass')
    ass_yaz(ass, [], [], toplam, str(p.get('kanal') or ''), str(p.get('kategori') or 'gündem'), 'Görüntü: ' + str(p.get('kanal') or 'kanal'))
    yazi_klasoru = os.environ.get('YAZI_KLASORU', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yazi'))
    mp4 = os.path.join(cikti_klasor, vid + '.mp4')
    ust = 230  # üst şerit payı
    filtre = (
        "[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=30:2,eq=brightness=-0.3,setsar=1[zemin];" % (W, H, W, H) +
        "[0:v]scale=%d:%d:force_original_aspect_ratio=decrease,setsar=1[on];" % (W, H - ust - 140) +
        "[zemin][on]overlay=x=(W-w)/2:y=%d+(H-%d-140-h)/2,fps=%d,format=yuv420p[a];" % (ust, ust, FPS) +
        "color=c=0xE0412F:s=%dx10:r=%d:d=%.2f[serit];" % (W, FPS, toplam) +
        "[a][serit]overlay=x='-W+W*t/%.2f':y=%d[b];" % (toplam, H - 10) +
        "[b]ass='%s':fontsdir='%s'[v]" % (ass.replace("'", ''), yazi_klasoru.replace("'", ''))
    )
    girdi = ['-i', ham]
    ses_esle = ['-map', '0:a:0'] if ses_var_mi(ham) else ['-map', '1:a']
    if not ses_var_mi(ham):
        girdi += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
    calistir(['ffmpeg', '-y', '-v', 'error'] + girdi + [
        '-filter_complex', filtre, '-map', '[v]'] + ses_esle + [
        '-t', '%.2f' % toplam,
        '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', str(FPS * 2),
        '-preset', 'medium', '-crf', '23', '-maxrate', '3500k', '-bufsize', '7000k',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2',
        '-movflags', '+faststart', mp4
    ])
    jpg = os.path.join(cikti_klasor, vid + '.jpg')
    calistir(['ffmpeg', '-y', '-v', 'error', '-ss', '%.2f' % min(1.0, toplam / 3), '-i', mp4, '-frames:v', '1', '-q:v', '3', jpg])
    boyut = os.path.getsize(mp4)
    if boyut > 95 * 1024 * 1024:
        raise RuntimeError('Video 95 MB sınırını aşıyor.')
    return {'ok': True, 'id': vid, 'sure': toplam, 'boyut': boyut, 'karakter': 0, 'zaman': int(time.time()), 'tur': 'kendi'}


def kendi_foto_uret(p, klasor, cikti_klasor):
    """Kanal sahibinin fotoğrafı: Instagram'ın sevdiği 4:5 (1080x1350) biçime oturtulur (boşluklar bulanık zemin),
    üstte ince kanal şeridi, altta "Fotoğraf: kanal" notu. Çıktı: <id>.jpg"""
    vid = re.sub(r'[^A-Za-z0-9_\-]', '', str(p['id']))[:60]
    if not vid:
        raise RuntimeError('Geçersiz kimlik.')
    ham = os.path.join(klasor, 'ham-foto')
    if p.get('dosya_url'):
        indir(p['dosya_url'], ham)
    else:
        telegram_indir(str(p.get('file_id') or ''), ham)
    fw, fh = 1080, 1350
    yazi_klasoru = os.environ.get('YAZI_KLASORU', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yazi'))
    kanal = str(p.get('kanal') or 'kanal').replace("'", '').replace(':', ' ').replace('\\', '')
    font = os.path.join(yazi_klasoru, 'BarlowCondensed-Bold.ttf')
    yazi = ("drawtext=fontfile='%s':" % font) if os.path.exists(font) else 'drawtext='
    filtre = (
        "[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=30:2,eq=brightness=-0.3,setsar=1[zemin];" % (fw, fh, fw, fh) +
        "[0:v]scale=%d:%d:force_original_aspect_ratio=decrease,setsar=1[on];" % (fw, fh - 90) +
        "[zemin][on]overlay=x=(W-w)/2:y=(H-90-h)/2[a];" +
        "[a]drawbox=x=0:y=%d:w=%d:h=90:color=0x0F1B2D@0.92:t=fill,drawbox=x=0:y=%d:w=12:h=90:color=0xE0412F:t=fill," % (fh - 90, fw, fh - 90) +
        yazi + "text='%s · Fotoğraf':fontcolor=white:fontsize=40:x=40:y=%d" % (kanal, fh - 68)
    )
    jpg = os.path.join(cikti_klasor, vid + '.jpg')
    calistir(['ffmpeg', '-y', '-v', 'error', '-i', ham, '-filter_complex', filtre, '-frames:v', '1', '-q:v', '2', jpg])
    return {'ok': True, 'id': vid, 'tur': 'foto', 'sure': 0, 'boyut': os.path.getsize(jpg), 'karakter': 0, 'zaman': int(time.time())}


def main():
    girdi = sys.argv[1] if len(sys.argv) > 1 else 'payload.json'
    cikti_klasor = sys.argv[2] if len(sys.argv) > 2 else 'site/v'
    with open(girdi, encoding='utf-8') as f:
        p = json.load(f)
    vid = re.sub(r'[^A-Za-z0-9_\-]', '', str(p.get('id', 'bilinmeyen')))[:60] or 'bilinmeyen'
    gecici = os.path.join('/tmp', 'video-' + vid)
    os.makedirs(gecici, exist_ok=True)
    os.makedirs(cikti_klasor, exist_ok=True)
    try:
        sonuc = {'kendi': kendi_uret, 'kendi-foto': kendi_foto_uret}.get(p.get('tur'), uret)(p, gecici, cikti_klasor)
    except Exception as e:  # noqa: BLE001
        sonuc = {'ok': False, 'id': vid, 'hata': str(e)[:600], 'zaman': int(time.time())}
    with open(os.path.join(cikti_klasor, vid + '.json'), 'w', encoding='utf-8') as f:
        json.dump(sonuc, f, ensure_ascii=False)
    print(json.dumps(sonuc, ensure_ascii=False))
    # Hata olsa bile 0 dön: .json dosyası yayınlansın, Apps Script nedeni okuyup resimli paylaşıma geçsin.
    return 0


if __name__ == '__main__':
    sys.exit(main())
