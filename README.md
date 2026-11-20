# ssh-fm — SSH Connection Manager & SFTP File Browser

Terminal UI untuk mengelola koneksi SSH dan transfer file dalam satu aplikasi: pilih host dari kartu, lalu jelajahi file remote dengan browser 3 panel dan transfer ber-progress. Ditulis dengan Rust ([ratatui](https://ratatui.rs)), satu binary tanpa dependensi runtime selain `ssh`, `rsync`, dan `sftp`.

## Instalasi

```bash
curl -sSf https://raw.githubusercontent.com/rezasetiabudi/ssh-fm/main/install.sh | sh
```

Mengunduh binary siap pakai untuk OS/arsitektur kamu (Linux & macOS, x86_64 & arm64) ke `~/.local/bin`, lengkap dengan verifikasi checksum. Tidak perlu Rust. Lalu jalankan `ssh-fm`.

Dari source:

```bash
git clone https://github.com/rezasetiabudi/ssh-fm && cd ssh-fm
cargo build --release        # binary: target/release/ssh-fm
# atau: cargo install --git https://github.com/rezasetiabudi/ssh-fm --locked ssh-fm
```

## Fitur

- **Pemilih host bergaya kartu** — nama, `user@host:port`, key/password, jump host dan jumlah port forward; filter dengan `/`.
- **Browser 3 panel** — host di kiri, isi folder remote di tengah, info file di kanan, antrean transfer di bawah.
- **Transfer dengan progress langsung** — upload/download satu atau banyak file (tandai dengan `space`), progress bar, kecepatan, dan ETA. Memakai `rsync`; ada prompt overwrite / skip / cancel.
- **Sync direktori** dua arah (local ↔ remote).
- **Operasi file remote** — hapus, rename, folder baru, chmod, lihat 50 baris pertama file.
- **Terminal tertanam** — SSH shell dan sftp berjalan di dalam jendela ssh-fm, termasuk prompt password / passphrase / host key. Mode console menampilkan info server (IP, OS, kernel, uptime, load, memori, disk) di sebelah terminal.
- **Panel SFTP split** — file remote di atas, lokal di bawah, **drag & drop** antar panel.
- **Jump host (`ProxyJump`) dan port forward (`LocalForward`)** per host, disimpan di `~/.ssh/config`.
- **Copy SSH key ke server** (`ssh-copy-id`), duplicate host, reconnect.
- **Command palette** fuzzy (`alt+p`) untuk semua aksi.
- **Import host** dari teks ssh config yang di-paste.
- **Key `.pem` / `.key`** — pilih dari `~/.ssh` atau ketik path bebas; permission otomatis di-`chmod 600`.
- Koneksi dipakai ulang (ControlMaster): password/passphrase cukup sekali.

### Terminal: copy & paste dengan mouse

- **Drag dengan tombol kiri** untuk memilih teks — otomatis **ter-copy** saat tombol dilepas.
- **Klik kanan** untuk **paste** (bracketed paste bila program remote mendukung). Klik kanan juga paste ke form dan dialog import.
- Copy masuk ke clipboard sistem dan juga dikirim lewat OSC 52, jadi tetap jalan lewat ssh/tmux.
- Scroll mouse menggulung riwayat terminal.
- `Ctrl+]` atau `Ctrl+C` dua kali menutup terminal.

## Shortcut Keyboard

Huruf biasa dipakai untuk **quick select** (ketik `f` → lompat ke file berawalan f), jadi semua shortcut aksi memakai `alt+`. Di macOS aktifkan *Use Option as Meta key* di terminal agar `alt` berfungsi.

### Daftar host
| Key | Aksi |
| --- | --- |
| `Enter` | Connect |
| `alt+n` / `alt+e` / `alt+d` | Host baru / edit / hapus |
| `alt+y` | Duplicate host |
| `alt+i` | Import host dari teks ssh config |
| `alt+k` | Copy SSH key ke server |
| *huruf biasa* | Quick select |
| `/` | Filter |
| `alt+p` / `ctrl+p` | Command palette |
| `alt+q` / `ctrl+q` | Keluar |

### Browser
| Key | Aksi |
| --- | --- |
| `Enter` / `backspace` | Masuk folder / naik satu level |
| `space` | Tandai file (multi-select) |
| `alt+u` / `alt+d` | Upload / download |
| `alt+v` | Lihat isi file |
| `alt+s` | Sync direktori (rsync) |
| `alt+x` (`Del`) / `alt+r` (`F2`) / `alt+n` / `alt+m` | Hapus / rename / folder baru / chmod |
| `alt+t` | Panel SFTP split (`Tab` pindah panel) |
| `alt+f` / `alt+h` | Sesi sftp terminal / SSH shell |
| `alt+k` / `alt+c` | Copy SSH key / reconnect |
| `.` / `/` | Tampil-sembunyikan dotfiles / filter |
| `F5` / `ctrl+r` | Refresh |
| `esc` | Kembali ke daftar host |

## Kebutuhan

`ssh`, `rsync`, `sftp` (sudah ada di macOS/Linux default). Untuk build dari source: Rust stable.

## Rilis (maintainer)

```bash
git tag v3.0.1 && git push --tags
```

GitHub Actions menjalankan test, build 4 target, dan melampirkan tarball + checksum ke halaman Release.

## Lisensi

Lihat [LICENSE](LICENSE).
