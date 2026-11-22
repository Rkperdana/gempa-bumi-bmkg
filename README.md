# Seismic Explorer — RKPERDANA

Dashboard pemantauan gempa berbasis data resmi BMKG, dikembangkan sebagai proyek personal RKPERDANA. Menggunakan aksen Ubuntu oranye (`#E95420`) sebagaimana Global Trade Atlas, dengan peta interaktif GeoJSON dan tema terang/gelap.

## Sumber data

Sistem membaca **tiga feed JSON resmi BMKG**, tanpa mengambil HTML antarmuka tabel gempa:

- [Gempa M5+](https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json)
- [Gempa dirasakan](https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json)
- [Gempa terbaru](https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json)

Semua data bersumber dari BMKG. Daftar ini **bukan** tabel 200 gempa real-time,
bukan catatan seluruh gempa di Indonesia atau dunia, dan tidak menjamin mencakup
kejadian di luar Indonesia. Kejadian yang sebelumnya hanya muncul di antarmuka
HTML tidak akan dipantau lagi. Data historis yang semata-mata berasal dari HTML
tidak dipertahankan ketika snapshot dipindah ke mode JSON-only.

## Cara kerjanya

- GitHub Actions `.github/workflows/update-bmkg.yml` dijadwalkan setiap 10 menit, dengan cadangan `.github/workflows/schedule-bmkg.yml` dua kali per jam. **Jadwal GitHub bersifat best-effort**: eksekusi dapat tertunda atau tidak muncul sama sekali. Untuk keandalan yang lebih tinggi, gunakan pemicu HTTP eksternal di bawah ini.
- `scripts/update_data.py` mengambil tiga JSON resmi BMKG, memvalidasi isi, dan menormalisasi waktu, koordinat, magnitudo, serta kedalaman.
- Jika salah satu feed resmi gagal, pembaruan snapshot gagal secara aman tanpa mengganti data terakhir.
- Kejadian dari tiga feed dipadukan berdasarkan waktu dan lokasi, tanpa menduplikasi kejadian yang sama.
- Hasil yang berhasil ditulis ke `data/gempa.json` dengan status `live`, lalu situs diterbitkan via GitHub Pages.
- Browser yang membuka dashboard memeriksa perubahan berkas data setiap 60 detik.

### Status data

- `live`: ketiga feed JSON resmi BMKG berhasil diperiksa dan waktu pemeriksaan tercatat.
- `preview` atau `fixture`: hanya data contoh atau data pengujian, bukan pantauan live.
- Jika lebih dari 90 menit tidak ada pemeriksaan sukses, dashboard menampilkan peringatan keterlambatan sinkronisasi.

Parameter gempa pada feed JSON resmi dapat direvisi BMKG. Lihat situs resmi BMKG untuk informasi terkini dan informasi gempa yang telah dikonfirmasi.

## Struktur berkas

- `index.html`: dashboard utama tanpa navbar.
- `styles.css`: desktop/mobile, tema terang dan gelap.
- `app.js`: peta, filter, pencarian, dan pengecekan JSON berkala.
- `assets/indonesia.geojson`: peta dasar.
- `assets/favicon.svg`: ikon personal bernuansa oranye Ubuntu.
- `data/gempa.json`: kejadian yang disinkronkan.
- `scripts/update_data.py`: sinkronisasi BMKG.
- `.github/workflows/update-bmkg.yml`: jadwal dan deploy GitHub Pages.
- `tests/`: pengujian parser dan integrasi.
- `START-LOKAL.bat`: server lokal di Windows.

## Menjalankan lokal

```bash
python -m http.server 8000
```

Buka http://localhost:8000. Untuk pengujian:

```bash
python -m unittest discover -s tests -v
node --check app.js
```

## Pemicu otomatis cadangan di luar GitHub

**Mengapa diperlukan:** Pada 6 November 2026, dua workflow yang memakai `schedule` tidak membuat run dengan interval yang dikonfigurasi, meskipun run `push` berhasil mengambil data BMKG dan menerbitkan GitHub Pages. Jadi masalah ini berada di pemicu jadwal, bukan kegagalan parser.

GitHub menyediakan `workflow_dispatch`, yang sudah diaktifkan pada workflow utama. Pemicu ini dapat dipanggil menggunakan layanan scheduler HTTPS seperti [cron-job.org](https://cron-job.org/), sehingga jadwal tidak bergantung pada sistem `on.schedule` GitHub.

### Setup aman dengan cron-job.org

1. Di GitHub, buka **Settings akun → Developer settings → Personal access tokens → Fine-grained tokens**. Buat token untuk **hanya** repository `Rkperdana/gempa-bumi-bmkg`, dengan **Actions: Read and write**. Simpan token secara privat, jangan memasukkannya ke kode website atau file repository.
2. Di cron-job.org, buat job **setiap 10 atau 15 menit** dengan HTTP **POST** ke:
   `https://api.github.com/repos/Rkperdana/gempa-bumi-bmkg/actions/workflows/update-bmkg.yml/dispatches`
3. Isi header:
   - `Authorization: Bearer <FINE_GRAINED_TOKEN>`
   - `Accept: application/vnd.github+json`
   - `Content-Type: application/json`
   - `X-GitHub-Api-Version: 2022-11-28`
4. Body JSON: `{"ref":"main"}`. Respons **HTTP 204** menandakan GitHub menerima permintaan pemicu (belum menjamin job selesai).
5. Buka [Actions](https://github.com/Rkperdana/gempa-bumi-bmkg/actions) dan pastikan run `workflow_dispatch` berikutnya berhasil, termasuk langkah **Update earthquake data from BMKG** dan **Deploy to GitHub Pages**.
6. Periksa `checked_at` pada `data/gempa.json` yang diterbitkan melalui GitHub Pages (bukan hanya file di branch `main`). Berkas di branch `main` hanya di-commit jika ada perubahan kejadian; pemeriksaan dengan data identik tetap dapat menghasilkan deployment dengan `checked_at` terbaru.

**Catatan keamanan:** Jangan memberikan token GitHub kepada pengguna publik maupun menyimpannya di URL query string, source code JavaScript, commit, atau log publik. Hapus token yang bocor dan buat ulang. `on.schedule` GitHub boleh tetap aktif sebagai jalur cadangan, tetapi tidak dapat dijadikan jaminan interval yang presisi.

## Publikasi

Alamat GitHub Pages setelah perubahan nama repository: https://rkperdana.github.io/gempa-bumi-bmkg/

Aktifkan **Settings → Pages → GitHub Actions**. Workflow mendukung pemicu manual, pembaruan terjadwal, dan pemicu ketika ada perubahan kode. Sumber dan atribusi BMKG harus dipertahankan.

**Proyek ini tidak membagikan API key atau token.** Pemilik situs telah mengonfirmasi izin penggunaan untuk integrasi dashboard. Pastikan cakupan, cara pengambilan HTML, dan persyaratan atribusi tetap sesuai dengan izin yang berlaku.
