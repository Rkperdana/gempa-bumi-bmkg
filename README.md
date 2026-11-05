# Dataloka — Monitor Gempa Indonesia

**Website dashboard penuh**, bukan iframe atau mini-widget. Tidak memakai framework, database eksternal, CDN, atau API key di frontend.

## Isi proyek

- `index.html` — dashboard dengan logo Dataloka, peta, statistik, pencarian dan daftar gempa.
- `styles.css` — tata letak desktop/mobile, mode terang dan gelap.
- `app.js` — interaksi peta, filter, pencarian, dan pemeriksaan ulang data.
- `assets/dataloka-logo.png` — logo asli sesuai unggahan pengguna.
- `assets/indonesia.geojson` — peta Indonesia yang disederhanakan.
- `data/gempa.json` — **pratinjau 12 kejadian, bukan data real-time**.
- `scripts/update_data.py` — pengambilan, normalisasi, validasi, penggabungan tiga feed BMKG.
- `.github/workflows/update-bmkg.yml` — jadwal sinkronisasi 15 menit dan deploy GitHub Pages; awalnya nonaktif menunggu konfirmasi izin integrasi.
- `tests/test_ingest.py` — pengujian deduplikasi dan validasi.
- `START-LOKAL.bat` — server pratinjau lokal Windows.

## Melihat dashboard di komputer

Di Windows, klik dua kali **`START-LOKAL.bat`** lalu buka alamat `http://localhost:8000` di Chrome. Atau jalankan:

```bash
python -m http.server 8000
```

Buka `http://localhost:8000`. Jangan membuka `index.html` dengan skema `file://`, karena browser membatasi pengambilan GeoJSON dan JSON lokal.

## Menayangkan website di GitHub Pages

1. Buat repositori GitHub baru.
2. Unggah seluruh isi folder proyek (pastikan `.github` dan `assets` ikut terunggah).
3. Buka **Settings → Pages → Build and deployment → Deploy from a branch**, lalu pilih branch `main` dan folder `/(root)`.
4. Akses URL GitHub Pages untuk melihat dashboard. Awalnya akan bertanda **Mode pratinjau**.

Dashboard tidak perlu di-embed untuk dilihat. Situs ini sudah berdiri sendiri. Penyematan ke website lain dapat dilakukan belakangan jika diperlukan.

## Pemutakhiran otomatis BMKG (opsional, belum aktif)

Sumber resmi:

- https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json — gempa terbaru
- https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json — daftar 15 gempa M 5,0+
- https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json — daftar 15 gempa dirasakan

Pipeline Python menggabungkan data berdasarkan waktu dan kedekatan lokasi; memeriksa koordinat, magnitudo, kedalaman, waktu, dan menghindari duplikasi. Arsip lokal hanya berisi kejadian yang muncul pada feed saat mulai memantau dan sejak itu; **bukan sensus seluruh gempa Indonesia**. Browser mengecek JSON yang sudah dipublikasikan setiap 60 detik.

Penggunaan operasional ditahan dengan variabel repository `BMKG_INTEGRATION_AUTHORIZED`. Konfirmasikan terlebih dahulu persyaratan/izin penggunaan BMKG untuk tujuan situs media, dan aktifkan `BMKG_INTEGRATION_AUTHORIZED=true` **hanya setelah izin dipenuhi**. Lalu:

1. Buka **Settings → Pages → Build and deployment → GitHub Actions**.
2. Buat repository variable `BMKG_INTEGRATION_AUTHORIZED` bernilai `true` di **Settings → Secrets and variables → Actions → Variables**.
3. Buka Actions → workflow **Sinkronisasi dan publikasi BMKG** → Run workflow untuk sinkronisasi pertama.
4. Setelah aktif, GitHub Actions dijadwalkan mengecek 3 feed setiap 15 menit. Publikasi dapat tertunda oleh antrean GitHub Actions, serta status heartbeat JSON tidak selalu berubah di tiap pemeriksaan.

Catatan: Pada repositori privat, dukungan GitHub Pages dan GitHub Actions bergantung pada paket/kebijakan GitHub. Jangan mengklaim data sebagai real-time ketika sinkronisasi belum aktif atau terlambat.

## Pengujian

```bash
python -m unittest discover -s tests -v
node --check app.js
```

`index.html` adalah halaman utama. Tidak ada berkas iframe yang perlu dipasang.
