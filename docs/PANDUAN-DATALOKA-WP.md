# Integrasi gempa BMKG → WordPress Dataloka.id

Integrasi ini **hanya** mengakses REST API Posts dan Media Dataloka di https://dataloka.id/wp-json/wp/v2/. Tidak menggunakan API, database, atau credentials Pirsadata. Workflow dashboard BMKG yang sudah ada tidak diubah.

## Aturan redaksi
- BMKG dipantau sekitar setiap 10 menit lewat satu pemicu terjadwal (GitHub Actions schedule bersifat *best effort*). Pemantauan berlangsung di GitHub; permintaan ke WordPress hanya saat ada artikel baru/pembaruan fakta yang belum diterbitkan atau percobaan terbit yang sebelumnya gagal.
- **Cakupan global termasuk luar Indonesia**: penerbit menggunakan salinan resmi terbaru tabel real-time BMKG dari `data/gempa.json` yang dihasilkan workflow dashboard independen, ditambah tiga feed JSON BMKG. Salinan real-time harus berstatus `live`, beridentitas sumber `https://www.bmkg.go.id/gempabumi/gempabumi-realtime`, dan diperiksa maksimum 180 menit lalu; data simulasi atau snapshot lama tidak boleh menghasilkan artikel. Gempa M5,8 di Romania pada 18 November 2026 pukul 07.48.42 WIB menjadi contoh kejadian yang sebelumnya terlewat karena tidak ada di feed JSON nasional.
- **Hanya gempa M5,5 ke atas**: dalam mode `live`, setiap kejadian terverifikasi dari BMKG dengan magnitudo minimal 5,5 langsung diproses untuk **publish** (termasuk luar Indonesia, status tsunami belum tersedia atau berpotensi tsunami). Kejadian baru harus berumur maksimal 120 menit saat pertama dideteksi. Revisi parameter yang tetap M5,5+ dapat menghasilkan **artikel pembaruan baru**.
- **Keterangan tsunami tidak menentukan kelayakan publikasi M5,5+**. Artikel menyampaikan status yang tercantum dalam data resmi BMKG secara apa adanya. Jika belum tersedia, artikel menuliskan bahwa keterangannya belum tercantum. Jangan menyimpulkan aman, mengarang peringatan tsunami, korban, ataupun kerusakan.
- **Semua gempa M5,4 ke bawah diabaikan** tanpa membuat artikel/draf, meskipun dilaporkan dirasakan. Ringkasan harian otomatis, mode `drafts`, dan tugas `daily` dinonaktifkan; jadwal otomatis hanya setiap 10 menit untuk M5,5+.
- Setiap gempa baru M5,5+ dibuat sebagai artikel baru; perubahan parameter BMKG yang substantif dan **tetap M5,5+** menghasilkan **artikel pembaruan baru dengan slug tersendiri**, bukan menyunting artikel lama. Bila magnitudo direvisi menjadi di bawah 5,5, bot mengabaikan revisinya dan tidak menyentuh artikel lama. Perubahan feed atau pengecekan tanpa perubahan fakta **tidak** mengakses REST API WordPress.
- Kejadian yang sudah berumur lebih dari 120 menit ketika pertama kali terlihat tidak dipublikasikan ulang.
- Ledger publikasi terpisah: `data/dataloka-wp-state.json`.
- **Kategori WordPress: Berita** untuk seluruh artikel bot. Skrip mencari ID kategori yang sudah ada lewat REST API `/wp/v2/categories?search=Berita`, mencocokkan nama/slug persis, lalu mengirim hanya kategori tersebut. Bila kategori tidak ditemukan, otomatisasi gagal tertutup dan **tidak menerbitkan ke Uncategorized**.
- **Judul SEO**: `Gempa M5,6 di Selatan Jawa, 17 November 2026 - BMKG` (contoh simulasi). Angka, wilayah, dan tanggal berasal dari BMKG.
- **Slug SEO**: `gempa-selatan-jawa-2026-11-17-xxxxxxxx`. Akhiran ID ringkas mencegah tabrakan URL jika terjadi beberapa gempa berlokasi dan bertanggal sama. Slug artikel yang sudah terbit **tidak diubah** untuk menghindari kerusakan URL/SEO.
- **Excerpt**: ringkasan faktual maksimal sekitar 160 karakter, mencakup lokasi, magnitudo, waktu WIB, kedalaman, serta status tsunami hanya bila diverifikasi. Field WordPress `excerpt` bukan otomatis meta description milik Yoast/Rank Math.
- **Yoast SEO (otomatis dan diverifikasi)**: `Focus keyphrase` → `_yoast_wpseo_focuskw`; `SEO title` → `_yoast_wpseo_title`; `Meta description` → `_yoast_wpseo_metadesc`; `Slug` → field `slug` bawaan WordPress. Seluruh nilai berasal dari data kejadian BMKG; Yoast meta description disimpan secara terpisah dari excerpt, meskipun teks dasarnya sama.
- **Verifikasi Yoast sebelum terbit**: post baru dibuat sebagai draf terlebih dahulu. Skrip melakukan pembacaan kembali tiga meta Yoast dari `/wp-json/wp/v2/posts/{id}?context=edit`. Hanya jika semuanya persis tersimpan, status diganti menjadi `publish`. Jika belum, post tetap draf untuk pemeriksaan (workflow menunjukkan error yang jelas).
- **Mempertahankan suntingan manusia**: artikel yang pernah dibuat tetap tidak disunting lagi oleh bot, termasuk judul, isi, permalink, gambar, dan Yoast. Bila BMKG menerbitkan koreksi substantif, bot membuat artikel pembaruan baru dengan permalink unik. Ledger menyimpan sidik fakta dan setiap versi untuk mencegah penerbitan ganda.

- **Tag WordPress**: tag satu kata yang relevan, seperti `Gempa`, `BMKG`, `Episentrum`, `Seismik`, dan wilayah bila bisa dipetakan dari nama BMKG. Skrip mencari tag berdasarkan nama dan mencoba membuatnya bila belum tersedia. Bila hak akun tidak cukup, artikel tetap diproses dan log memberi peringatan; editor dapat memasang tag secara manual.
- Sumber resmi: https://data.bmkg.go.id/gempabumi/
- Semua artikel gempa M5,5+ mempunyai minimal **empat paragraf**. Pada akhir kalimat di paragraf terakhir tertulis **(RK/D-1)** tanpa pindah baris atau paragraf baru.
- **Gaya naskah**: awal paragraf pertama menggunakan `<strong>Dataloka.id</strong>`; kata `Gempa` ditautkan satu kali ke `https://dataloka.id/tag/gempa/`. Informasi sumber pada paragraf terakhir artikel menjadi teks biasa `bersumber dari data BMKG` tanpa tautan eksternal. Metadata SEO tidak berisi HTML.
- Artikel yang diterbitkan otomatis mendapatkan **featured image JPEG 1200×675 (16:9), di bawah 500 KB**, berupa peta posisi episentrum dari koordinat BMKG.
- Batas daratan peta berasal dari Natural Earth (domain publik), terbundel lokal dalam `assets/natural-earth-110m-land.json`. Tidak ada API peta pihak ketiga saat runtime.
- Gambar diunggah ke WordPress Media Library dengan teks alternatif dan ditetapkan sebagai `featured_media` sebelum artikel dipublikasikan. Jika proses gambar gagal, artikel baru tidak dipublikasikan otomatis.
- Artikel pembaruan baru mendapat gambar episentrum sendiri. Artikel dan gambar lama tidak disentuh oleh bot.

## Pengaktifan (hanya setelah peninjauan PR)

1. Pastikan akun WordPress yang dipilih memang mempunyai izin membuat dan **menerbitkan** artikel. Lebih aman membuat akun Author khusus bot daripada menggunakan akun admin umum.
2. Di WordPress buat **Application Password** khusus untuk koneksi ini. Jangan gunakan password login utama.
3. GitHub → repository **Rkperdana/gempa-bumi-bmkg** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:
   - `DATALOKA_WP_USERNAME`: nama pengguna WordPress untuk bot.
   - `DATALOKA_WP_APP_PASSWORD`: Application Password untuk bot.
4. Pastikan di WordPress → **Posts → Categories** sudah ada kategori bernama **Berita**. Tidak perlu mengisi ID kategori di GitHub; skrip akan menemukannya otomatis.
5. Gabungkan PR ke `main`. Scheduled workflow akan menjalankan mode **live**; sebelum Secrets terisi, workflow gagal tertutup tanpa menulis ke WordPress.
6. Untuk uji manual: GitHub → **Actions** → **Dataloka | Gempa BMKG ke WordPress** → **Run workflow** → mode `dry-run`.
7. Tinjau log Actions, halaman Posts di WordPress, dan status penerbitan. Jika terdapat 401/403, cek hak akses pengguna, Application Password, dan firewall.
8. Untuk menghentikan penerbitan segera, **disable workflow** di GitHub Actions (atau cabut Application Password di WordPress).

## Dukungan Yoast REST API

Yoast menyediakan endpoint `/yoast/v1/get_head` yang **hanya bisa membaca**. Beberapa versi Yoast sudah mengekspos tiga field di atas dalam `meta` pada REST API WordPress bawaan; versi lain belum. Skrip memeriksa benar-benar tersimpan, bukan hanya mengandalkan status HTTP 200.

Jika log Actions menyatakan *Yoast metadata belum tersedia pada REST API WordPress*:

1. Pastikan Yoast SEO aktif dan mutakhir. Periksa apakah ketiga field Yoast ada dalam objek `meta` ketika mengambil artikel via WordPress REST API dengan akun yang berhak mengedit.
2. Jika masih tidak tersedia, instal bridge khusus Dataloka: `wordpress/dataloka-yoast-rest-bridge/dataloka-yoast-rest-bridge.php`. Unggah dalam format ZIP lewat **WordPress → Plugins → Add New → Upload Plugin**, lalu **Activate**. Plugin bridge hanya mendaftarkan tiga meta Yoast untuk tipe konten `post`, dengan kontrol akses `edit_post`; ia tidak mengubah konten lain, Pirsadata, atau file tema.
3. Jalankan satu siklus otomatisasi/pengujian penerbitan. Periksa panel Yoast pada draf dan pastikan **Focus keyphrase**, **SEO title**, dan **Meta description** terisi. Slug diperiksa dari permalink WordPress.
4. Jika data Yoast tidak terlihat tetapi API menyatakan tersimpan, coba menyimpan artikel secara manual atau fitur optimasi data SEO Yoast dan periksa tampilan frontend; indexables Yoast mungkin memerlukan sinkronisasi.

**Jangan** menaruh kata sandi aplikasi dalam kode, plugin, atau PR. Bot menggunakan dua GitHub Secrets yang sudah disiapkan.

## Pembatasan penting

- Kunci deduplikasi berbasis waktu/koordinat adalah heuristik karena feed JSON BMKG yang digunakan tidak menyertakan ID kejadian permanen. Perubahan waktu/koordinat besar dapat memerlukan rekonsiliasi manual.
- REST API (khususnya `/media`) bisa diblokir konfigurasi hosting Dataloka; integrasi belum membuktikan kemampuan mengunggah gambar dan menerbitkan hingga diuji dengan Secrets asli.
- Untuk publikasi otomatis dengan gambar, akun WordPress memerlukan kapabilitas `upload_files` dan `publish_posts`.
- Peta menunjukkan lokasi secara ilustratif; bukan peta intensitas guncangan, dampak, atau bahaya tsunami.
- Bot tidak lagi membuat draf atau ringkasan harian gempa di bawah M5,5. Draf sementara di WordPress hanya digunakan untuk verifikasi metadata sebelum artikel M5,5+ dipublikasikan.
- Jangan mengubah slug artikel yang sudah terbit tanpa strategi redirect 301. Bot secara sengaja mempertahankan slug lama pada pembaruan artikel bot.
- Tidak memodifikasi kode CMS, dashboard, ataupun konten Pirsadata.
- **Jangan pernah** menyimpan password dalam source code, PR, issue, log, maupun file ZIP.

## Referensi
https://developer.wordpress.org/rest-api/reference/posts/
https://developer.wordpress.org/rest-api/reference/media/
https://www.naturalearthdata.com/downloads/110m-cultural-vectors/
https://developer.wordpress.org/advanced-administration/security/application-passwords/

https://developer.yoast.com/customization/apis/rest-api/
https://developer.wordpress.org/rest-api/extending-the-rest-api/modifying-responses/
