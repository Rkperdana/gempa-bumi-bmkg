# Eksperimen peringatan dini cuaca ekstrem — Dataloka.id

Status: **prototype live-publish dengan gerbang izin BMKG; tidak mengubah otomatisasi gempa**.

Sumber resmi: https://data.bmkg.go.id/peringatan-dini-cuaca/ (RSS + CAP XML nowcasting); endpoint RSS utama: https://www.bmkg.go.id/alerts/nowcast/id; fallback yang dicontohkan BMKG: https://www.bmkg.go.id/alerts/nowcast/id/rss.xml. Contoh data dalam tests/fixtures/nowcast-sample.xml adalah **sintetis**, bukan peringatan nyata.

## Tujuan

- Mengikuti pola WordPress gempa Dataloka: artikel 5 paragraf, ringkasan/SEO Yoast, kategori Berita, tag satu kata, tautan BMKG, featured image editorial 1200 x 675 JPEG <500KB, dan proteksi perubahan manual.
- Setiap peringatan CAP mendapat satu slug stabil dari identitas peringatan; CAP references dipakai untuk menautkan revisi ke identitas awal jika tersedia.
- Hanya memproses peringatan Actual+Public yang masih berlaku. Tidak memublikasikan peringatan yang sudah kedaluwarsa atau menebak dampak.
- Mode WordPress **live**: artikel baru dibuat sebagai draf sementara untuk validasi Yoast, tag Featured, dan featured image; bila semua terverifikasi, baru berstatus publish. Jika editor menyunting artikel, pembaruan otomatis dilewati, bukan menimpa.
- Ledger terpisah data/dataloka-cuaca-state.json, workflow dan media terpisah dari gempa serta dari Pirsadata.

## Mode dan aktivasi

fixture (default): uji parser dan desain gambar menggunakan XML sintetis, tanpa HTTP eksternal. dry-run: ambil RSS+CAP resmi dan tampilkan calon judul tanpa WordPress. live: terbitkan artikel ke WordPress setelah semua pemeriksaan, featured image, tag Featured dan validasi SEO berhasil.

Workflow: .github/workflows/dataloka-wp-cuaca.yml, dapat dijalankan manual lewat Actions dan memiliki jadwal **15 menit**. Mode dry-run dapat memvalidasi API resmi tanpa menghubungi WordPress. Publikasi live terjadwal tetap dinonaktifkan sampai pengelola menetapkan GitHub Actions repository variable BMKG_NOWCAST_AUTHORIZED=true setelah izin pemanfaatan yang sesuai dikonfirmasi. Gunakan DATALOKA_WP_USERNAME dan DATALOKA_WP_APP_PASSWORD yang sudah dipakai WordPress Dataloka; kredensial tidak disalin ke kode. Pirsadata tidak dihubungi.

**Perhatian perizinan:** Per 8 Juli 2026, Ketentuan Penggunaan BMKG menyebut pengemasan ulang/integrasi pihak ketiga/penggunaan komersial memerlukan izin tertulis. Konfirmasi cakupan izin di https://www.bmkg.go.id/ketentuan-penggunaan sebelum mengaktifkan integrasi ini.

## Pengujian

    python -m pip install Pillow==12.0.0
    python -m unittest discover -s tests -p 'test_dataloka_wp_cuaca.py' -v
    python scripts/dataloka_wp_cuaca.py --mode fixture

Batas awal: maksimal lima peringatan per eksekusi, dan tidak membuat draf perdana untuk alert yang diterbitkan lebih dari 90 menit sebelumnya. Jadwal GitHub Actions bersifat best effort. HTML artikel memakai seluruh deskripsi resmi CAP, termasuk nama kecamatan sebagaimana tertulis, sehingga versi uji tidak mengubah istilah atau menambahkan prediksi.

Kriteria produksi: pengujian respons API BMKG nyata (manual dry-run), metadata Yoast di WP, hak akses bot, gambar di WP Media Library, dan izin tertulis BMKG. Tanpa BMKG_NOWCAST_AUTHORIZED=true, jadwal live tidak berjalan.
