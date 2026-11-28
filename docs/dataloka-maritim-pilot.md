# Dataloka maritim — pilot, belum produksi

Sumber: https://maritim.bmkg.go.id/apidoc
Pemilik Dataloka mengonfirmasi izin penggunaan banjir rob dan gelombang tinggi pada 28 November 2026. Jangan menyimpan dokumen izin di repo publik. Ketentuan penggunaan tetap berlaku.

- Workflow PR menguji data sintetis tanpa jaringan, tanpa WordPress, menghasilkan dua JPEG orisinal 1600×900.
- Workflow jadwal 30 menit hanya melakukan akses API apabila repository variable BMKG_MARITIM_AUTHORIZED=true setelah izin tertulis yang mencakup **kedua produk** diverifikasi. Default tidak mengakses API. Jalur WordPress gelombang tinggi terpisah, hanya aktif jika BMKG_MARITIM_LIVE=true; jangan aktifkan sebelum akses produksi terverifikasi.
- Gelombang: schema teramati 28 November 2026 dari warning/warnings.json. Filter masa berlaku menurut WIB/WITA/WIT; minimal kategori tinggi, tampilkan juga kategori sedang jika ada. Artikel wilayah dan Indonesia dipratinjau terpisah; sebelum publikasi perlu aturan prioritas nasional/lokal untuk mencegah tumpang tindih. Fingerprint stabil untuk bulletin identik; publisher gelombang memiliki ledger persisten, slug stabil, dan batas dua artikel per putaran.
- Rob: endpoint gabungan tidak berhasil diakses saat verifikasi. Adapter live belum dibuat; jangan mengasumsikan schema. Setelah izin, gunakan diagnostic untuk melihat schema, verifikasi detail provinsi, cakupan tanggal, pembatalan dan area, kemudian buat fixture yang tervalidasi.
- Input rob editorial lokal (bukan schema BMKG): array objek region, start, end (YYYY-MM-DD), zone (WIB/WITA/WIT), areas (array nama lokasi), description (narasi resmi yang sudah diperiksa). Contoh uji ada pada tests; jangan menerbitkan fixture.
- Jalankan lokal: python scripts/dataloka_maritim.py --wave-json path.json --reviewed-rob-json reviewed.json. Hasil JSON, HTML dan dua gambar di maritim-preview/.
- Prasyarat go-live: akses resmi dari GitHub runner, konfirmasi persyaratan atribusi/logo/keutuhan produk sesuai izin, validasi schema rob dan pengujian produksi terbatas. Publisher gelombang memeriksa kategori/tag/Yoast/media, revalidasi sumber sebelum publish, dan menjaga draf editorial. Tidak ada publisher live rob sampai schema dikonfirmasi.
- Tidak mengubah cuaca, gempa, harga emas atau Pirsadata.

## Hasil diagnosis 28 November 2026

GitHub Actions run 46097378486, job 140831747639: endpoint gabungan rob, detail 31.json, dan warning/warnings.json masing-masing HTTP 403 Forbidden. Jangan mencoba mengganti identitas klien, proksi, atau melewati kontrol akses. Minta BMKG memastikan akses API dari runner GitHub atau memberikan endpoint/kredensial resmi yang disetujui. Jangan memasukkan kredensial dalam repo publik. Sakelar BMKG_MARITIM_LIVE tetap tidak diaktifkan.
