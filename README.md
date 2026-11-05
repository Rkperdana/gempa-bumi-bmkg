# Seismic Explorer — RKPERDANA

Dashboard pemantauan gempa berbasis data resmi BMKG, dikembangkan sebagai proyek personal RKPERDANA. Menggunakan aksen Ubuntu oranye (`#E95420`) sebagaimana Global Trade Atlas, dengan peta interaktif GeoJSON dan tema terang/gelap.

## Sumber data

**Sumber utama:** [Gempa Bumi Real-time BMKG](https://www.bmkg.go.id/gempabumi/gempabumi-realtime). Pengolah Python membaca baris tabel yang di-render server pada halaman resmi BMKG. Halaman berjudul "200 Gempa Bumi Real-time", tetapi jumlah baris aktual dapat kurang dari 200; tidak ada kejadian yang diisi secara sintetis.

**Data pelengkap:**
- [Gempa M5+](https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json)
- [Gempa dirasakan](https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json)
- [Gempa terbaru](https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json)

Data pelengkap hanya menambahkan label gempa dirasakan, informasi intensitas, potensi tsunami, dan sumber. Parameter magnitudo, lokasi, kedalaman, dan waktu pada data utama **tetap mengikuti tabel real-time** untuk menghindari angka berbeda akibat revisi antarproduk BMKG.

Beberapa kejadian di tabel BMKG berada **di luar Indonesia**. Daftar kejadian tetap menampilkan data tersebut, sementara titik di peta hanya muncul dalam cakupan peta Indonesia. Angka "gempa dalam daftar terbaru" bukan jumlah seluruh gempa sepanjang hari.

## Cara kerjanya

- GitHub Actions `.github/workflows/update-bmkg.yml` memeriksa sumber setiap 15 menit (penjadwalan dapat terlambat karena antrean GitHub).
- `scripts/update_data.py` mengambil HTML tabel real-time, memvalidasi isi, mengubah WIB ke UTC, dan menormalisasi koordinat.
- Parser gagal secara aman ketika halaman BMKG berubah drastis atau jumlah data tiba-tiba kurang dari 100; JSON yang sudah berhasil diambil sebelumnya tidak ditimpa.
- JSON feed pelengkap dicocokkan berdasarkan waktu dan jarak. Kejadian duplikat dipersatukan, dan detail dari feed pelengkap tidak menimpa parameter utama real-time.
- Hasil yang berhasil ditulis ke `data/gempa.json` dengan status `live`, lalu situs diterbitkan via GitHub Pages.
- Browser yang membuka dashboard memeriksa perubahan berkas data setiap 60 detik.

### Status data

- `live`: sudah mengambil daftar kejadian dari tabel BMKG dan mencatat waktu pemeriksaan.
- `preview` atau `fixture`: hanya data contoh atau data pengujian, bukan pantauan live.
- Jika lebih dari 90 menit tidak ada pemeriksaan sukses, dashboard menampilkan peringatan keterlambatan sinkronisasi.

Gempa real-time merupakan parameter awal yang dapat direvisi BMKG. Lihat situs resmi BMKG untuk informasi terkini dan informasi gempa yang telah dikonfirmasi.

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

## Publikasi

Aktifkan **Settings → Pages → GitHub Actions**. Workflow mendukung pemicu manual, pembaruan terjadwal, dan pemicu ketika ada perubahan kode. Sumber dan atribusi BMKG harus dipertahankan.

**Proyek ini tidak membagikan API key atau token.** Pemilik situs telah mengonfirmasi izin penggunaan untuk integrasi dashboard. Pastikan cakupan, cara pengambilan HTML, dan persyaratan atribusi tetap sesuai dengan izin yang berlaku.
