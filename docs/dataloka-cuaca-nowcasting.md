# Eksperimen peringatan dini cuaca ekstrem — Dataloka.id

Status: **live-publish aktif untuk Dataloka**, berdasarkan konfirmasi pemilik bahwa izin tertulis penggunaan CAP BMKG telah diperoleh pada 22 November 2026. Isi izin belum ditinjau secara independen di sini. Tidak mengubah otomatisasi gempa atau Pirsadata.

Sumber resmi: https://data.bmkg.go.id/peringatan-dini-cuaca/ (RSS + CAP XML nowcasting); endpoint RSS utama: https://www.bmkg.go.id/alerts/nowcast/id; fallback yang dicontohkan BMKG: https://www.bmkg.go.id/alerts/nowcast/id/rss.xml. Contoh data dalam tests/fixtures/nowcast-sample.xml adalah **sintetis**, bukan peringatan nyata.

## Tujuan

- Mengikuti pola WordPress gempa Dataloka: artikel **5 paragraf isi + 1 paragraf kredit sumber terpisah**, ringkasan/SEO Yoast, kategori Berita, tag satu kata, tautan BMKG, featured image editorial 1200 x 675 JPEG <500KB, dan proteksi perubahan manual.
- Paragraf pertama menautkan kata **cuaca** ke `https://dataloka.id/tag/cuaca`; baris **Sumber: BMKG** selalu ditempatkan setelah paragraf penutup, tidak digabung ke kalimat penutup.
- Setiap peringatan CAP mendapat satu slug stabil dari identitas peringatan; CAP references dipakai untuk menautkan revisi ke identitas awal jika tersedia.
- Hanya memproses peringatan Actual+Public yang masih berlaku. Tidak memublikasikan peringatan yang sudah kedaluwarsa atau menebak dampak.
- Mode WordPress **live**: artikel baru dibuat sebagai draf sementara untuk validasi Yoast, featured image (tanpa tag Featured); bila semua terverifikasi, baru berstatus publish. Jika editor menyunting artikel, pembaruan otomatis dilewati, bukan menimpa.
- Ledger terpisah data/dataloka-cuaca-state.json, workflow dan media terpisah dari gempa serta dari Pirsadata.

## Mode dan aktivasi

fixture (default): uji parser dan desain gambar menggunakan XML sintetis, tanpa HTTP eksternal. dry-run: ambil RSS+CAP resmi dan tampilkan calon judul tanpa WordPress. live: terbitkan artikel ke WordPress setelah semua pemeriksaan, featured image dan validasi SEO (tanpa tag Featured) berhasil.

Workflow: .github/workflows/dataloka-wp-cuaca.yml, dapat dijalankan manual lewat Actions dan memiliki jadwal **15 menit**. Mode dry-run dapat memvalidasi API resmi tanpa menghubungi WordPress. Publikasi live terjadwal diaktifkan berdasarkan konfirmasi izin tertulis oleh pemilik situs pada 22 November 2026. Untuk menghentikan semua pemeriksaan cuaca terjadwal, set GitHub Actions repository variable `BMKG_NOWCAST_PAUSED=true`. Akses publikasi tetap memakai dua secret WordPress Dataloka yang sudah ada. Gunakan DATALOKA_WP_USERNAME dan DATALOKA_WP_APP_PASSWORD yang sudah dipakai WordPress Dataloka; kredensial tidak disalin ke kode. Pirsadata tidak dihubungi.

**Perhatian perizinan:** Per 8 Juli 2026, Ketentuan Penggunaan BMKG mensyaratkan izin tertulis untuk penggunaan komersial/integrasi pihak ketiga. Pemilik Dataloka menyatakan sudah mempunyai izin tertulis. Pengelola bertanggung jawab memastikan cakupannya meliputi API CAP nowcasting, publikasi berita otomatis, serta monetisasi situs; rujukan: https://www.bmkg.go.id/ketentuan-penggunaan.

## Pengujian

    python -m pip install Pillow==12.0.0
    python -m unittest discover -s tests -p 'test_dataloka_wp_cuaca.py' -v
    python scripts/dataloka_wp_cuaca.py --mode fixture

Antrean disimpan di GitHub sebelum WordPress dihubungi. Semua URL RSS diambil dengan jeda permintaan. Maksimal lima percobaan penerbitan per putaran, dengan giliran untuk provinsi berbeda. Peringatan baru boleh berumur lebih dari 90 menit jika masih aktif. Bot mengecek ulang RSS, isi CAP dan waktu kedaluwarsa sebelum mengirim status publish. Data pending, alasan dilewati, serta waktu pemeriksaan lengkap terakhir tersedia pada ledger. Timeout alur live 25 menit. HTML artikel memakai seluruh deskripsi resmi CAP, termasuk nama kecamatan sebagaimana tertulis, sehingga versi uji tidak mengubah istilah atau menambahkan prediksi.

Kriteria produksi: respons API BMKG nyata perlu lulus (mode manual dry-run), metadata Yoast di WP wajib tervalidasi, hak akses bot, gambar di WP Media Library wajib ada sebelum artikel berstatus publish; tag Featured tidak lagi dipasang. Mode live di workflow menyetel `BMKG_NOWCAST_AUTHORIZED=true` berdasarkan konfirmasi pemilik; bila BMKG tidak merespons valid, WordPress tidak diubah.

## Keandalan WordPress

Eksekusi awal pada 22 November 2026 melampaui batas 9 menit dan melaporkan `WordPress network error on POST posts: TimeoutError`. Antrean tersimpan dan penyimpanan hasil pada langkah `always()` membantu mengurangi beban dan memungkinkan pemulihan yang aman. Jika WordPress masih tidak merespons, artikel **tidak diklaim telah terbit** dan integrasi perlu pemeriksaan performa REST API/hosting Dataloka. Tidak ada perubahan pada gempa atau Pirsadata.

Perubahan format editorial versi 2 dicoba satu kali untuk artikel lama yang masih aktif dan memiliki ledger bot. Editan manual pada artikel WordPress tidak ditimpa; pembaruan lama di luar feed aktif tidak dibackfill otomatis.

## Kebijakan tag (22 November 2026)

Artikel peringatan dini cuaca tidak lagi memakai **tag `Featured`**. Tag yang tersisa: `BMKG`, `Cuaca`, dan `Peringatan`. **Featured image tetap wajib** sebelum publikasi, termasuk validasi Yoast. Khusus artikel cuaca lama yang masih ada dalam ledger bot, workflow akan menghapus tag Featured secara bertahap (maksimal satu artikel per siklus) setelah memeriksa kepemilikan bot dan hash konten; suntingan manual editor tidak ditimpa. Artikel gempa dan Pirsadata tidak diubah.

## Pemicu eksternal tiap 10 menit

Pada panel hosting yang mendukung cron, simpan `scripts/trigger-cuaca.py` di direktori privat di luar web root. Skrip hanya memerlukan Python 3. Simpan fine-grained GitHub token khusus repo ini dengan izin Actions: write dalam file privat `~/.config/dataloka/actions-token` (mode 600). Kredensial WordPress sudah tersimpan di GitHub Actions.

Atur alamat email cron di panel hosting atau melalui MAILTO pada crontab. Sesuaikan path dengan direktori pengguna hosting:

```cron
*/10 * * * * /usr/bin/python3 /path/privat/trigger-cuaca.py
```

Setiap pemanggilan meminta eksekusi live kecuali sudah ada run aktif. Jika pengambilan lengkap terakhir lebih dari 30 menit yang lalu, skrip mengeluarkan pesan untuk email cron. Jika cron host sendiri berhenti, pemantauan ini juga berhenti. Jadwal GitHub 15 menit tetap tersedia sebagai cadangan.
