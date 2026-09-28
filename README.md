# v0.1.8 - Profit/Loss 500 Fix + Native PDF Export

- Fix Internal Server Error pada `/profit-loss` untuk akun aktif.
- Export PDF Neraca dan Laba Rugi memakai report object yang sama dengan tampilan layar.
- PDF mengikuti filter Department, Project, kombinasi dimensi, tanggal/as-of, subtotal, total dan trial masking.
- Tambah dependency `reportlab==4.4.4`.
- Tidak ada perubahan schema PostgreSQL.

# SUPERTOOLS BALANCE SHEET DEPARTEMENT/PROJECT AOL

Starter source v0.1.7 untuk web app SaaS **Accurate Online Edition**, siap dipush ke GitHub dan dideploy ke Railway.

## Fitur yang sudah disiapkan

- Login page modern + self registration trial.
- Trial otomatis **7 hari**.
- Trial hanya dapat membaca akun **CASH_BANK / Kas-Bank**. Pos lain **dimasking di backend** dan diblur di UI.
- User aktif dapat menyimpan maksimal **5 database Accurate Online**.
- OAuth 2.0 Authorization Code Accurate Online.
- Db List + Open DB + penyimpanan `host` dan `X-Session-ID` terenkripsi.
- Sync master:
  - `/api/glaccount/list.do`
  - `/api/department/list.do`
  - `/api/project/list.do`
- Sync Journal Voucher:
  - `/api/journal-voucher/list.do`
  - `/api/journal-voucher/detail.do`
  - membaca `accountNo`, `amount`, `amountType`, `departmentName`, `projectNo`, `memo` dari detail jurnal.
- Neraca per Department.
- Neraca per Project.
- Neraca Project + Department.
- Filter multi-select Department / Project pada Neraca (All atau pilihan tertentu).
- Subtotal Neraca: Aset Lancar, Aset Tetap/Tidak Lancar, Liabilitas Jangka Pendek, Liabilitas Jangka Panjang, Ekuitas, Total Aktiva, Total Pasiva.
- Laba Rugi per Department, per Project, dan Project + Department.
- Filter periode Dari/Sampai dan filter multi-select dimensi pada Laba Rugi.
- Current Earnings dari akun Revenue / COGS / Expense / Other Income / Other Expense.
- Export Excel; trial tetap dimasking pada export.
- Admin Control Center:
  - lihat semua user
  - aktivasi langganan N hari
  - suspend user
  - extend trial
  - reset password menjadi temporary password
  - lihat database user
- PostgreSQL-ready untuk Railway, SQLite untuk local development.
- OAuth token dan database session disimpan terenkripsi dengan Fernet.
- CSRF token untuk form POST dan session cookie `SameSite=Lax`.

## Scope Accurate Online

Gunakan scope read-only berikut pada app developer AOL:

```text
glaccount_view department_view project_view journal_voucher_view
```

Aplikasi starter ini **tidak meminta scope save/delete**.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

FastAPI tidak otomatis membaca `.env`, jadi untuk lokal export variable melalui shell atau gunakan tooling Anda. Contoh Linux/macOS:

```bash
export DATABASE_URL="sqlite:///./supertools_aol.sqlite3"
export SECRET_KEY="..."
export TOKEN_ENCRYPTION_KEY="..."
export ADMIN_EMAIL="admin@example.com"
export ADMIN_PASSWORD="..."
export AOL_CLIENT_ID="..."
export AOL_CLIENT_SECRET="..."
export AOL_REDIRECT_URI="http://localhost:8000/accurate/oauth/callback"
uvicorn app.main:app --reload
```

Generate secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Deploy Railway

1. Push folder ini ke GitHub.
2. Railway → **New Project** → deploy repository GitHub.
3. Tambahkan service **PostgreSQL**.
4. Di Variables service aplikasi, set:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
APP_ENV=production
APP_BASE_URL=https://DOMAIN-ANDA
COOKIE_SECURE=true
SECRET_KEY=<random>
TOKEN_ENCRYPTION_KEY=<Fernet key>
ADMIN_EMAIL=<email admin>
ADMIN_PASSWORD=<password admin awal>
AOL_CLIENT_ID=<client id Accurate>
AOL_CLIENT_SECRET=<client secret Accurate>
AOL_REDIRECT_URI=https://DOMAIN-ANDA/accurate/oauth/callback
AOL_SCOPES=glaccount_view department_view project_view journal_voucher_view
```

5. Generate public domain di Railway.
6. Pastikan **URL OAuth Callback** yang terdaftar di Area Developer Accurate sama persis dengan `AOL_REDIRECT_URI`.
7. Deploy ulang setelah variables disimpan.

`railway.toml` dan `Dockerfile` sudah disertakan.

## Catatan arsitektur

### Subscription

Status user:

```text
TRIAL      -> 7 hari, max 1 DB, hanya CASH_BANK terlihat
ACTIVE     -> max 5 DB, semua akun terlihat
SUSPENDED  -> login ditolak
EXPIRED    -> report tidak dapat digunakan sampai diaktifkan admin
```

Belum ada payment gateway. Aktivasi dilakukan manual dari Admin Control Center, sesuai kebutuhan starter saat ini.

### Masking trial

Non-Cash/Bank tidak sekadar disembunyikan CSS. Nilainya diubah menjadi `None` di server sebelum template dirender. UI hanya menambahkan blur sebagai preview visual. Detail GL trial juga hanya mengembalikan baris `CASH_BANK`.

### Sync job

Starter memakai FastAPI `BackgroundTasks`. Untuk volume produksi yang sangat besar, tahap berikutnya sebaiknya pindahkan job sinkronisasi ke worker terpisah (Redis + RQ/Celery/Arq) agar job tidak hilang jika web container restart.

### Database schema

Pada starter, tabel dibuat otomatis via `Base.metadata.create_all()` saat startup. Untuk production jangka panjang, langkah berikutnya adalah menambahkan Alembic migration sebelum banyak user mulai memakai aplikasi.

## Struktur project

```text
app/
  main.py
  config.py
  database.py
  models.py
  core/
    auth.py
    security.py
  services/
    accurate_client.py
    sync_service.py
  reporting/
    balance_sheet.py
    profit_loss.py
  templates/
  static/
Dockerfile
railway.toml
requirements.txt
.env.example
```

## Yang perlu dites dengan akun AOL live

Dokumentasi Anda sudah menunjukkan `detailJournalVoucher` memiliki `accountNo`, `amount`, `amountType`, `departmentName`, dan `projectNo`. Yang tetap perlu dites pada database AOL nyata adalah bentuk response aktual `detail.do` dan apakah endpoint Journal Voucher yang tersedia pada akun Anda benar-benar merepresentasikan seluruh posting jurnal transaksi yang ingin dimasukkan ke Neraca. Parser dibuat toleran terhadap beberapa nama container detail, tetapi test live tetap diperlukan sebelum release komersial.

## Railway PORT fix (v0.1.4)

Railway memberikan port runtime melalui environment variable `PORT`. Pada versi sebelumnya, `railway.toml` menggunakan `--port $PORT` sebagai Start Command langsung, sehingga pada beberapa deploy Railway nilai `$PORT` diteruskan sebagai teks literal dan Uvicorn gagal dengan `Invalid value for --port: $PORT`.

v0.1.4 menghapus override `startCommand` dari `railway.toml` dan membiarkan Dockerfile menjalankan:

```sh
sh -c "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
```

Jika Railway Service Anda pernah memiliki **Custom Start Command** manual, kosongkan/hapus field tersebut agar Dockerfile `CMD` dipakai. Alternatifnya isi manual dengan command shell di atas.


## Railway PostgreSQL driver fix (v0.1.4)
This build uses `psycopg2-binary`, which matches SQLAlchemy's driver for Railway's normal `postgresql://...` `DATABASE_URL`. The previous `PORT` fix remains unchanged.

## v0.1.4 — OAuth encryption key fix
`TOKEN_ENCRYPTION_KEY` may now be either a canonical Fernet key **or** an ordinary long random secret. SUPERTOOLS derives a valid Fernet key automatically when necessary.

Recommended Railway variable:

```env
TOKEN_ENCRYPTION_KEY=put-a-long-random-secret-here-and-never-change-it
```

Do not rotate this value casually after users have connected Accurate Online, because stored OAuth tokens are encrypted with it.

## v0.1.5 - Load All Jurnal & Sync Inspector

Jika Neraca kosong, buka **Load All Jurnal** dari sidebar. Halaman ini menampilkan data yang benar-benar sudah masuk ke cache PostgreSQL SUPERTOOLS:

- jumlah Journal Header dari `journal-voucher/list.do`
- jumlah baris Detail GL dari `journal-voucher/detail.do`
- jumlah baris dengan Department
- jumlah baris dengan Project
- jumlah baris account type `CASH_BANK`
- jumlah nomor akun jurnal yang belum match ke master GL Account

Tombol **Load All Jurnal** melakukan refresh master GL Account lalu memuat ulang seluruh Journal Voucher yang dikembalikan oleh API. Tabel inspector menampilkan maksimal 1.000 baris terbaru dengan kolom tanggal, nomor jurnal, akun, nama akun, type, debit, kredit, department, project, dan memo.

Jika `Journal Header > 0` tetapi `Detail GL = 0`, parser/detail response adalah titik masalah. Jika `Journal Header = 0` padahal ada transaksi pembelian/kas-bank di AOL, verifikasi apakah endpoint `journal-voucher` pada akun/database tersebut memang mengembalikan jurnal yang dibentuk oleh transaksi modul lain; inspector ini sengaja dibuat agar perbedaannya terlihat sebelum report dihitung.

## v0.1.6 - Journal Detail Loader Fix + Raw API Diagnostic

Perubahan:
- parser response `journal-voucher/detail.do` dibuat case-insensitive dan recursive;
- support wrapper/list/indexed-dict dan variasi field account/debit/credit;
- bila detail biasa kosong, aplikasi mencoba ulang `detail.do` dengan field `detailJournalVoucher` secara eksplisit;
- `Load All Jurnal` menampilkan strategi parser pada progress;
- tombol **API Detail Diagnostic** menampilkan struktur response asli jurnal pertama tanpa token/credential, agar variasi response Accurate Online dapat didiagnosis langsung dari UI.

Jika `Journal Header > 0` tetapi `Detail GL = 0`, klik **API Detail Diagnostic** dan kirim bagian `Detail Top Keys` + `Raw response shape` untuk penyesuaian parser berikutnya.


## v0.1.7 - Balance Sheet Totals + Dimension Filters + Profit & Loss

- Neraca sekarang menampilkan subtotal Aset Lancar, Aset Tetap/Tidak Lancar, Liabilitas Jangka Pendek, Liabilitas Jangka Panjang, Ekuitas, serta Total Aktiva dan Total Pasiva.
- Report Department / Project / Project+Department mempunyai filter checkbox multi-select. Jika tidak ada pilihan spesifik, report membaca semua dimensi.
- Ditambahkan Laporan Laba Rugi per Department, Project, dan kombinasi Project+Department dengan filter tanggal Dari/Sampai.
- Laba Rugi menghitung Pendapatan Usaha, HPP, Laba Kotor, Beban Operasional, Laba Usaha, Pendapatan Lain, Beban Lain, dan Laba Bersih.
- Export Excel mengikuti filter aktif.
- Untuk user trial, nilai Laba Rugi tetap dimasking server-side.
