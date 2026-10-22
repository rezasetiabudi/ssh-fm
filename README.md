# ssh-fm — SSH Connection Manager & SFTP File Browser

Terminal UI untuk mengelola koneksi SSH dan transfer file dalam satu aplikasi: pilih host dari kartu, lalu jelajahi file remote dengan browser 3 panel dan transfer ber-progress. Dibangun dengan [Textual](https://github.com/Textualize/textual).

## Fitur

- **Pemilih host bergaya kartu** — nama, `user@host:port`, dan key/password tiap host; filter dengan `/`.
- **Browser 3 panel** — host di kiri, isi folder remote di tengah, info file (ukuran, permission, owner, tanggal, tipe) di kanan, dan antrean transfer di bawah.
- **Transfer dengan progress langsung** — upload/download satu atau banyak file (tandai dengan `space`), progress bar, kecepatan, dan ETA. Memakai `rsync`.
- **Sync direktori** dua arah (local ↔ remote) dengan rsync.
- **View file** kecil (50 baris pertama) tanpa download, plus panel SFTP split (server di atas, lokal di bawah, drag & drop), SFTP terminal, dan SSH shell — semuanya berjalan di dalam jendela ssh-fm (terminal tertanam, `Ctrl+]` untuk menutup).
- **Command palette** (`alt+p`) untuk semua aksi.
- **Manajemen host** lewat form — tambah, edit, rename, hapus. Disimpan di `~/.ssh/config`.
- **Key `.pem` / `.key`** — pilih dari `~/.ssh` atau ketik path bebas; permission otomatis di-`chmod 600`.
- **Password / passphrase** — ssh meminta langsung di terminal saat connect, lalu koneksi dipakai ulang (ControlMaster) untuk semua operasi.

## Shortcut Keyboard

Huruf biasa dipakai untuk **quick select** (ketik `f` → lompat ke file berawalan f), jadi semua shortcut aksi memakai `alt+`. Di macOS aktifkan *Use Option as Meta key* di terminal agar `alt` berfungsi.

### Daftar host
| Key | Aksi |
| --- | --- |
| `Enter` | Connect |
| `alt+n` / `alt+e` / `alt+d` | Host baru / edit / hapus |
| `alt+i` | Import host dari teks ssh config yang di-paste |
| *huruf biasa* | Quick select: lompat ke host berawalan huruf itu |
| `/` | Filter |
| `alt+p` / `ctrl+p` / `super+p` | Command palette |
| `alt+q` / `ctrl+q` | Keluar |

### Browser
| Key | Aksi |
| --- | --- |
| `Enter` | Masuk folder |
| `backspace` | Naik satu level |
| `space` | Tandai file (multi-select) |
| *huruf biasa* | Quick select: lompat ke file/folder berawalan huruf itu (ketik lagi untuk prefix; huruf sama diulang = berikutnya) |
| `alt+u` / `alt+d` | Upload / download (yang ditandai atau yang disorot) |
| `alt+v` | Lihat isi file |
| `alt+s` | Sync direktori (rsync) |
| `alt+x` / `alt+r` (`F2`) / `alt+n` / `alt+m` | Hapus / rename / folder baru / chmod file di server |
| `alt+t` | Panel SFTP split: file lokal di bawah, drag & drop antar panel |
| `alt+f` / `alt+h` | Sesi sftp terminal / SSH shell (tertanam, `Ctrl+]` menutup) |
| `.` | Tampil/sembunyikan dotfiles |
| `/` | Filter file |
| `F5` / `ctrl+r` | Refresh |
| `esc` | Kembali ke daftar host |

## Kebutuhan (Requirements)

- Python 3.9+
- Library Python: `textual` (di-install otomatis oleh `install.sh` ke virtualenv sendiri)
- Tool sistem: `ssh`, `rsync`, `sftp` (sudah ada di macOS/Linux default)

## Instalasi

```bash
./install.sh
```

Script ini akan:
1. Menyalin aplikasi ke `~/.local/share/ssh-fm/` dan membuat virtualenv di sana (pakai `uv` jika ada), jadi tidak menyentuh Python sistem.
2. Membuat launcher `~/bin/ssh-fm`.
3. Menambahkan `~/bin` ke `PATH` di file config shell kamu (`.zshrc`/`.bashrc`/dll).

Restart terminal (atau `source ~/.zshrc`), lalu jalankan `ssh-fm`.

Untuk development:

```bash
uv venv && uv pip install -r requirements.txt pytest pytest-asyncio
.venv/bin/pytest
.venv/bin/python ssh-fm.py
```

## Konfigurasi

- Semua host disimpan di **`~/.ssh/config`** — bisa dibaca, diedit, dan dikelola oleh tool ini, dan tetap kompatibel dengan perintah `ssh` biasa.
- SSH key dideteksi otomatis dari direktori `~/.ssh`.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'textual'`** — jalankan ulang `./install.sh`; dependency dipasang ke virtualenv di `~/.local/share/ssh-fm/venv`.
- **`UNPROTECTED PRIVATE KEY FILE`** — pilih key lewat form host; permission-nya otomatis diperbaiki ke 600.
- **Host tidak muncul** — pastikan ada entri Host di `~/.ssh/config`.
- **Koneksi minta password terus** — pastikan SSH key sudah di-`ssh-copy-id`, atau pilih autentikasi password saat menambah host.

## Teknis

| Item | Detail |
| --- | --- |
| Bahasa | Python 3 |
| UI Framework | Textual |
| Dependensi Python | `textual` |
| Dependensi sistem | `ssh`, `rsync`, `sftp` |
| Struktur | Package `ssh_fm/` + entry point `ssh-fm.py` |
| Konfigurasi | `~/.ssh/config` |
| Kompatibilitas | macOS, Linux, WSL |

## Lisensi

MIT — lihat file [LICENSE](LICENSE).
