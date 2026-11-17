# Dataloka Publisher — penerbitan artikel umum dari ChatGPT

**Status:** jalur teknis siap dipakai; pengujian otomatis berhasil. Publikasi artikel baru harus diminta secara eksplisit dan diuji dengan permintaan sungguhan. Penambahan kode/workflow sendiri **tidak** memposting artikel.

## Arsitektur

ChatGPT → GitHub connector → tambah JSON pada branch \`dataloka-publisher\`
→ GitHub Actions \`Dataloka | Publisher Artikel Umum\`
→ WordPress REST API di \`https://dataloka.id\` → artikel terbit.

Dua rahasia repository yang sudah dipakai bot gempa dapat digunakan tanpa dibocorkan:
- \`DATALOKA_WP_USERNAME\`
- \`DATALOKA_WP_APP_PASSWORD\`

Kode **tidak pernah menyimpan** password dalam file. Plugin Github yang terhubung belum menyediakan endpoint untuk menulis Actions Secrets; pengelolaan dilakukan oleh pemilik akun melalui GitHub.

## Batasan keamanan yang sengaja diterapkan

Repository \`Rkperdana/gempa-bumi-bmkg\` **PUBLIC**. Berkas queue yang di-commit akan bisa dilihat siapa pun **sebelum** artikel terbit di WordPress. Maka:

- Hanya artikel yang sudah disetujui untuk **publikasi terbuka** boleh masuk ke queue.
- **Draf rahasia, embargo, data pribadi, atau materi belum disetujui tidak boleh dimasukkan** ke branch ini. Untuk draf pribadi, diperlukan repo privat atau koneksi WordPress langsung.
- Hanya target tetap \`dataloka.id\`; permintaan ke Pirsadata ditolak.
- Hanya operasi \`publish\`; tidak boleh menghapus atau mengubah artikel lain.
- Setiap file yang ditambahkan adalah satu permintaan. Pengeditan file yang sudah ada tidak memicu permintaan ulang.
- Publisher mengecek slug WordPress. Jika sudah dipakai artikel lain, proses berhenti agar tidak membuat atau menimpa konten ganda.
- Sebelum terbit, WordPress membuat draf sementara, lalu memastikan \`slug\`, isi, dan metadata Yoast terpasang. Jika gagal, artikel **tidak dipublikasikan**.
- API REST tidak memiliki jaminan transaksi atomik; bila langkah setelah pembuatan draf gagal, draf sementara dapat tertinggal dan harus ditinjau.

## Cara meminta publikasi dari percakapan

Sampaikan: **"Karmel, terbitkan artikel ini ke Dataloka"** beserta tulisan final atau dokumen yang ingin diterbitkan. Asisten akan:

1. Menyiapkan judul, slug, ringkasan (maksimum 300 karakter), body HTML, kategori, 0–8 tag, Yoast SEO title, focus keyphrase, meta description (maksimum 160 karakter).
2. Memastikan konten sudah final dan memang diminta **langsung terbit**.
3. Membuat file \`publisher/outbox/<request_id>.json\` baru di branch \`dataloka-publisher\`, bukan \`main\`.
4. Menilai log GitHub Actions dan mengonfirmasi URL/ID WordPress setelah proses selesai.

Konteks Pirsadata tidak digunakan.

## Contoh bentuk request (contoh fiktif, BUKAN artikel yang dikirim)

\`\`\`json
{
  "request_id": "artikel-contoh-20261117-001",
  "site": "dataloka.id",
  "operation": "publish",
  "title": "Contoh Berita Data yang Siap Diterbitkan",
  "slug": "contoh-berita-data",
  "summary": "Contoh ringkasan berita data untuk memperlihatkan format publikasi di Dataloka.",
  "content_html": "<p>Paragraf pertama hasil verifikasi redaksi.</p><p>Paragraf kedua membahas perbandingan angkanya.</p><p>Paragraf ketiga menempatkan data dalam konteks.</p><p>Paragraf keempat menguraikan sumber primer.</p>",
  "category_slug": "berita",
  "tags": ["Data", "Ekonomi"],
  "seo": {
    "focus_keyphrase": "contoh berita data",
    "seo_title": "Contoh Berita Data untuk Dataloka",
    "meta_description": "Contoh berita berbasis data yang sudah diperiksa redaksi serta dilengkapi judul, ringkasan, sumber, dan metadata pencarian."
  }
}
\`\`\`

Tambahkan \`featured_media_id\` (bilangan positif) bila gambar unggulan sudah ada dalam Media Library WordPress. Tidak ada upload gambar otomatis pada versi pertama.

Kategori di-resolve dari \`category_slug\`, misalnya \`berita\`. Nama tag yang sudah ada dicocokkan; tag yang belum dibuat dilewati tanpa membuang artikel. Meta Yoast harus dapat ditulis/dibaca lewat REST API; jika tidak, penerbitan berhenti sebagai draf sementara.

## Meninjau eksekusi

- Kode dan permintaan: https://github.com/Rkperdana/gempa-bumi-bmkg/tree/dataloka-publisher
- Workflow: https://github.com/Rkperdana/gempa-bumi-bmkg/actions
- Dokumentasi WordPress: https://developer.wordpress.org/rest-api/reference/posts/
- Autentikasi WordPress: https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/

**Penting:** jalur ini berbeda dari sinkronisasi BMKG. Mengubah atau menambah file pada branch \`dataloka-publisher\` tidak menyentuh branch \`main\` dan tidak menjalankan workflow dashboard BMKG dengan pemicu \`push\` untuk main.
