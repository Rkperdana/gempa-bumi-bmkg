# Integrasi gempa BMKG → WordPress Dataloka.id

Integrasi ini **hanya** mengakses REST API Posts dan Media Dataloka di https://dataloka.id/wp-json/wp/v2/. Tidak menggunakan API, database, atau credentials Pirsadata. Workflow dashboard BMKG yang sudah ada tidak diubah.

## Aturan redaksi
- Dipantau sekitar setiap 10 menit (GitHub Actions schedule bersifat *best effort*, tidak dijamin tepat waktu).
- **M5,5+**: otomatis **publish** jika BMKG menyatakan secara eksplisit **tidak berpotensi tsunami**, sumber utama gempa tersedia, dan kejadian berumur maksimal 120 menit saat pertama dideteksi.
- Jika BMKG belum memberi keterangan tsunami atau menyebut berpotensi tsunami: hanya **draft**, perlu pemeriksaan redaksi. Tidak pernah mengarang peringatan atau klaim dampak.
- Gempa M5,0–5,4 dan gempa dirasakan: **draft**; draf ringkasan hari sebelumnya dibuat pukul **00.15 WIB** jika tersedia kejadian yang terpantau.
- Revisi BMKG memperbarui artikel bot yang sama selama belum diedit manusia dan sidik kejadian masih cocok. Tidak mengubah artikel di luar bot.
- Kejadian yang sudah berumur lebih dari 120 menit ketika pertama kali terlihat tidak dipublikasikan ulang.
- Ledger publikasi terpisah: `data/dataloka-wp-state.json`.
- Sumber resmi: https://data.bmkg.go.id/gempabumi/
- Semua artikel (termasuk draf ringkasan) mempunyai minimal **empat paragraf**. Pada akhir kalimat di paragraf terakhir tertulis **(RK/D-1)** tanpa pindah baris atau paragraf baru.
- Artikel yang diterbitkan otomatis mendapatkan **featured image JPEG 1200×675 (16:9), di bawah 500 KB**, berupa peta posisi episentrum dari koordinat BMKG.
- Batas daratan peta berasal dari Natural Earth (domain publik), terbundel lokal dalam `assets/natural-earth-110m-land.json`. Tidak ada API peta pihak ketiga saat runtime.
- Gambar diunggah ke WordPress Media Library dengan teks alternatif dan ditetapkan sebagai `featured_media` sebelum artikel dipublikasikan. Jika proses gambar gagal, artikel baru tidak dipublikasikan otomatis.
- Pembaruan artikel bot mempertahankan gambar sebelumnya; perubahan manual pada artikel/gambar tidak ditimpa oleh bot.

## Pengaktifan (hanya setelah peninjauan PR)

1. Pastikan akun WordPress yang dipilih memang mempunyai izin membuat dan **menerbitkan** artikel. Lebih aman membuat akun Author khusus bot daripada menggunakan akun admin umum.
2. Di WordPress buat **Application Password** khusus untuk koneksi ini. Jangan gunakan password login utama.
3. GitHub → repository **Rkperdana/gempa-bumi-bmkg** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:
   - `DATALOKA_WP_USERNAME`: nama pengguna WordPress untuk bot.
   - `DATALOKA_WP_APP_PASSWORD`: Application Password untuk bot.
4. Opsional: **Variables** → `DATALOKA_WP_CATEGORY_ID` = ID numerik kategori Dataloka. Jangan mengarang ID kategori.
5. Gabungkan PR ke `main`. Scheduled workflow akan menjalankan mode **live**; sebelum Secrets terisi, workflow gagal tertutup tanpa menulis ke WordPress.
6. Untuk uji manual: GitHub → **Actions** → **Dataloka | Gempa BMKG ke WordPress** → **Run workflow** → mode `dry-run`, task `events`.
7. Tinjau log Actions, halaman Posts di WordPress, dan status penerbitan. Jika terdapat 401/403, cek hak akses pengguna, Application Password, dan firewall.
8. Untuk menghentikan penerbitan segera, **disable workflow** di GitHub Actions (atau cabut Application Password di WordPress).

## Pembatasan penting

- Kunci deduplikasi berbasis waktu/koordinat adalah heuristik karena feed JSON BMKG yang digunakan tidak menyertakan ID kejadian permanen. Perubahan waktu/koordinat besar dapat memerlukan rekonsiliasi manual.
- REST API (khususnya `/media`) bisa diblokir konfigurasi hosting Dataloka; integrasi belum membuktikan kemampuan mengunggah gambar dan menerbitkan hingga diuji dengan Secrets asli.
- Untuk publikasi otomatis dengan gambar, akun WordPress memerlukan kapabilitas `upload_files` dan `publish_posts`.
- Peta menunjukkan lokasi secara ilustratif; bukan peta intensitas guncangan, dampak, atau bahaya tsunami.
- Draf ringkasan bukan angka total resmi harian; datanya hanya kejadian terpantau.
- Tidak memodifikasi kode CMS, dashboard, ataupun konten Pirsadata.
- **Jangan pernah** menyimpan password dalam source code, PR, issue, log, maupun file ZIP.

## Referensi
https://developer.wordpress.org/rest-api/reference/posts/
https://developer.wordpress.org/rest-api/reference/media/
https://www.naturalearthdata.com/downloads/110m-cultural-vectors/
https://developer.wordpress.org/advanced-administration/security/application-passwords/
