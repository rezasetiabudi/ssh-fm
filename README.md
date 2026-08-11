# ssh-fm — SSH Connection Manager & SFTP File Browser

Terminal UI untuk mengelola koneksi SSH dan transfer file (SFTP/scp/rsync) dalam satu layar, dengan layout dua panel ber-bor (hosts di kiri, remote file browser di kanan). Dibangun dengan [Textual](https://github.com/Textualize/textual).

## Fitur

- **Manajemen host SSH** — tambah, edit, hapus, dan connect ke host yang tersimpan.
- **Auto-detect SSH config** — baca & tulis langsung ke `~/.ssh/config`, termasuk profile yang sudah ada.
- **Remote file browser** — jelajahi direktori remote dengan warna dan ikon, sama seperti file manager.
- **Upload & download** — single atau multiple file, dengan seleksi range seperti `1,3-7,9`.
- **Rsync** — sinkronisasi direktori dua arah (local ↔ remote).
- **View file** — lihat isi file remote tanpa download.
- **Destination presets** — unduh ke current directory, Desktop, Downloads, atau path custom.
- **Auto-detect SSH key** — daftar key dari `~/.ssh` ditawarkan saat menambah host.

## Shortcut Keyboard

### Global
| Key | Aksi |
| --- | --- |
| `q` | Quit / Back (keluar dari browser dulu, lalu keluar app) |
| `esc` | Back / Cancel |
| `ctrl+q` | Keluar app (berfungsi dari state mana pun, termasuk di dalam dialog) |
| `tab` | Pindah panel (hosts ↔ browser) |

### Panel Hosts
| Key | Aksi |
| --- | --- |
| `Enter` | Connect ke host (ssh) |
| `b` | Browse file host |
| `a` | Tambah host |
| `e` | Edit host |
| `x` | Hapus host |
| `r` | Rsync (host-level) |

### Panel Browser
| Key | Aksi |
| --- | --- |
| `Enter` | Buka file / masuk direktori |
| `backspace` | Naik satu level |
| `p` | Set path manual |
| `u` / `U` | Upload single / multi |
| `d` / `D` | Download single / multi |
| `v` | View isi file |
| `i` | Info file |
| `r` | Rsync direktori |

> Catatan: di dalam dialog form, `q` akan terisi ke kolom input (bukan menutup dialog). Gunakan `esc` untuk cancel dialog, atau `ctrl+q` untuk keluar app.

## Kebutuhan (Requirements)

- Python 3.8+
- Library Python: `textual`
- Tool sistem: `ssh`, `scp`, `rsync` (sudah ada di macOS/Linux default)

## Instalasi

### 1. Otomatis (disarankan)

```bash
./install.sh
```

Script ini akan:
1. Menginstall library `textual` (dengan fallback `--break-system-packages` untuk sistem dengan PEP 668).
2. Menyalin `ssh-fm.py` ke `~/bin/ssh-fm`.
3. Menambahkan `~/bin` ke `PATH` di file config shell kamu (`.zshrc`/`.bashrc`/dll).

Setelah selesai, restart terminal atau jalankan `source ~/.zshrc`, lalu:

```bash
ssh-fm
```

### 2. Manual

```bash
# Install dependency
python3 -m pip install textual

# Jika error "externally-managed-environment" (PEP 668):
python3 -m pip install --user --break-system-packages textual

# Copy script
mkdir -p ~/bin
cp ssh-fm.py ~/bin/ssh-fm
chmod +x ~/bin/ssh-fm
export PATH="$HOME/bin:$PATH"
```

## Cara Pakai

1. Jalankan `ssh-fm`. Daftar host dari `~/.ssh/config` otomatis muncul di panel kiri.
2. Pilih host lalu tekan `b` untuk masuk ke file browser remote.
3. Navigasi dengan `Enter` (masuk) / `backspace` (naik), atau `p` untuk lompat ke path tertentu.
4. Gunakan `u`/`d`/`v`/`r` untuk upload, download, view, dan rsync.
5. Tekan `q` untuk kembali ke daftar host, lalu `q` lagi untuk keluar.

### Seleksi Range File

| Contoh | Arti |
| --- | --- |
| `1,3,5` | File nomor 1, 3, dan 5 |
| `1-5` | File nomor 1 sampai 5 |
| `1,3-7,9` | File nomor 1, 3–7, dan 9 |

## Konfigurasi

- Semua host disimpan di **`~/.ssh/config`** — bisa dibaca, diedit, dan dikelola oleh tool ini, dan tetap kompatibel dengan perintah `ssh` biasa.
- SSH key dideteksi otomatis dari direktori `~/.ssh`.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'textual'`** — install textual (lihat Instalasi di atas). Ini penyebab paling umum, terutama di macOS yang memakai Homebrew Python (terkena PEP 668).
- **Host tidak muncul** — pastikan ada entri Host di `~/.ssh/config`.
- **Koneksi minta password terus** — pastikan SSH key sudah di-`ssh-copy-id`, atau pilih autentikasi password saat menambah host.

## Teknis

| Item | Detail |
| --- | --- |
| Bahasa | Python 3 |
| UI Framework | Textual |
| Dependensi Python | `textual` |
| Dependensi sistem | `ssh`, `scp`, `rsync` |
| Ukuran | Single file `ssh-fm.py` (~45 KB) |
| Konfigurasi | `~/.ssh/config` |
| Kompatibilitas | macOS, Linux, WSL |

## Lisensi

MIT — lihat file [LICENSE](LICENSE).
