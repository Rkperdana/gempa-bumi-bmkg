# Dataloka maritim — pilot, belum produksi

Sumber: https://maritim.bmkg.go.id/apidoc
Ketentuan: https://ppid.bmkg.go.id/ketentuan-penggunaan (izin tertulis untuk pengemasan ulang, integrasi dan komersial).

- Workflow PR menguji data sintetis tanpa jaringan, tanpa WordPress, menghasilkan dua JPEG orisinal 1600×900.
- Workflow jadwal 30 menit hanya melakukan akses API apabila repository variable BMKG_MARITIM_AUTHORIZED=true setelah izin tertulis yang mencakup **kedua produk** diverifikasi. Default tidak mengakses API. Tidak ada kredensial WordPress atau publikasi otomatis pada pilot ini.
- Gelombang: schema teramati 28 November 2026 dari warning/warnings.json. Filter masa berlaku menurut WIB/WITA/WIT; minimal kategori tinggi, tampilkan juga kategori sedang jika ada. Artikel wilayah dan Indonesia dipratinjau terpisah; sebelum publikasi perlu aturan prioritas nasional/lokal untuk mencegah tumpang tindih. Fingerprint stabil untuk bulletin identik, belum ada ledger persisten.
- Rob: endpoint gabungan tidak berhasil diakses saat verifikasi. Adapter live belum dibuat; jangan mengasumsikan schema. Setelah izin, gunakan diagnostic untuk melihat schema, verifikasi detail provinsi, cakupan tanggal, pembatalan dan area, kemudian buat fixture yang tervalidasi.
- Input rob editorial lokal (bukan schema BMKG): array objek region, start, end (YYYY-MM-DD), zone (WIB/WITA/WIT), areas (array nama lokasi), description (narasi resmi yang sudah diperiksa). Contoh uji ada pada tests; jangan menerbitkan fixture.
- Jalankan lokal: python scripts/dataloka_maritim.py --wave-json path.json --reviewed-rob-json reviewed.json. Hasil JSON, HTML dan dua gambar di maritim-preview/.
- Prasyarat go-live: persetujuan BMKG termasuk persyaratan atribusi/logo/keutuhan produk, validasi schema rob, revalidasi sumber sebelum publikasi, ledger persisten dan slug idempoten, batas artikel per putaran, pemeriksaan kategori/tag/Yoast/media, verifikasi draf sebelum publish, pengujian WordPress mock dan produksi terbatas.
- Tidak mengubah cuaca, gempa, harga emas atau Pirsadata.
