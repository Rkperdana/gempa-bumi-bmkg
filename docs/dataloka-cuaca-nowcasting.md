# Eksperimen peringatan dini cuaca ekstrem — Dataloka.id

Status: **live-publish aktif untuk Dataloka**, berdasarkan konfirmasi pemilik bahwa izin tertulis penggunaan CAP BMKG telah diperoleh pada 22 November 2026. Isi izin belum ditinjau secara independen di sini. Tidak mengubah otomatisasi gempa atau Pirsadata.

Sumber resmi: https://data.bmkg.go.id/peringatan-dini-cuaca/ (RSS + CAP XML nowcasting); endpoint RSS utama: https://www.bmkg.go.id/alerts/nowcast/id; fallback yang dicontohkan BMKG: https://www.bmkg.go.id/alerts/nowcast/id/rss.xml. Contoh data dalam tests/fixtures/nowcast-sample.xml adalah **sintetis**, bukan peringatan nyata.

## Tujuan

- Mengikuti pola WordPress gempa Dataloka: artikel 5 paragraf, ringkasan/SEO Yoast, kategori Berita, tag satu kata, tautan BMKG, featured image editorial 1200 x 675 JPEG <500KB, dan proteksi perubahan manual.
- Setiap peringatan CAP mendapat satu slug stabil dari identitas peringatan; CAP references dipakai untuk menautkan revisi ke identitas awal jika tersedia.
- Hanya memproses peringatan Actual+Public yang masih berlaku. Tidak memublikasikan peringatan yang sudah kedaluwarsa atau menebak dampak.
- Mode WordPress **live**: artikel baru dibuat sebagai draf sementara untuk validasi Yoast, tag Featured, dan featured image; bila semua terverifikasi, baru berstatus publish. Jika editor menyunting artikel, pembaruan otomatis dilewati, bukan menimpa.
- Ledger terpisah data/dataloka-cuaca-state.json, workflow dan media terpisah dari gempa serta dari Pirsadata.

## Mode dan aktivasi

fixture (default): uji parser dan desain gambar menggunakan XML sintetis, tanpa HTTP eksternal. dry-run: ambil RSS+CAP resmi dan tampilkan calon judul tanpa WordPress. live: terbitkan artikel ke WordPress setelah semua pemeriksaan, featured image, tag Featured dan validasi SEO berhasil.

Workflow: .github/workflows/dataloka-wp-cuaca.yml, dapat dijalankan manual lewat Actions dan memiliki jadwal **15 menit**. Mode dry-run dapat memvalidasi API resmi tanpa menghubungi WordPress. Publikasi live terjadwal diaktifkan berdasarkan konfirmasi izin tertulis oleh pemilik situs pada 22 November 2026. Untuk menghentikan semua pemeriksaan cuaca terjadwal, set GitHub Actions repository variable `BMKG_NOWCAST_PAUSED=true`. Akses publikasi tetap memakai dua secret WordPress Dataloka yang sudah ada. Gunakan DATALOKA_WP_USERNAME dan DATALOKA_WP_APP_PASSWORD yang sudah dipakai WordPress Dataloka; kredensial tidak disalin ke kode. Pirsadata tidak dihubungi.

**Perhatian perizinan:** Per 8 Juli 2026, Ketentuan Penggunaan BMKG mensyaratkan izin tertulis untuk penggunaan komersial/integrasi pihak ketiga. Pemilik Dataloka menyatakan sudah mempunyai izin tertulis. Pengelola bertanggung jawab memastikan cakupannya meliputi API CAP nowcasting, publikasi berita otomatis, serta monetisasi situs; rujukan: https://www.bmkg.go.id/ketentuan-penggunaan.

## Pengujian

    python -m pip install Pillow==12.0.0
    python -m unittest discover -s tests -p 'test_dataloka_wp_cuaca.py' -v
    python scripts/dataloka_wp_cuaca.py --mode fixture

Batas sementara: maksimal **satu** peringatan per eksekusi, dan tidak membuat draf perdana untuk alert yang diterbitkan lebih dari 90 menit sebelumnya. Batas waktu live 12 menit, pemeriksaan 15 menit; kegagalan WordPress menghentikan pemrosesan alert lain pada siklus tersebut. POST draf tidak diulang secara buta; jika WP sempat menerima draf saat koneksi timeout, bot mencoba pemulihan hanya jika slug dan konten identik. Jadwal GitHub Actions bersifat best effort. HTML artikel memakai seluruh deskripsi resmi CAP, termasuk nama kecamatan sebagaimana tertulis, sehingga versi uji tidak mengubah istilah atau menambahkan prediksi.

Kriteria produksi: respons API BMKG nyata perlu lulus (mode manual dry-run), metadata Yoast di WP wajib tervalidasi, hak akses bot, gambar di WP Media Library dan tag Featured harus ada sebelum artikel berstatus publish. Mode live di workflow menyetel `BMKG_NOWCAST_AUTHORIZED=true` berdasarkan konfirmasi pemilik; bila BMKG tidak merespons valid, WordPress tidak diubah.

## Keandalan WordPress

Eksekusi awal pada 22 November 2026 melampaui batas 9 menit dan melaporkan `WordPress network error on POST posts: TimeoutError`. Batas satu alert per siklus serta penyimpanan ledger pada langkah `always()` membantu mengurangi beban dan memungkinkan pemulihan yang aman. Jika WordPress masih tidak merespons, artikel **tidak diklaim telah terbit** dan integrasi perlu pemeriksaan performa REST API/hosting Dataloka. Tidak ada perubahan pada gempa atau Pirsadata.
