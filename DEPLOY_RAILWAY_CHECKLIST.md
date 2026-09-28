# Railway Deploy Checklist

- [ ] Push repository ke GitHub.
- [ ] Railway: New Project → Deploy from GitHub Repo.
- [ ] Tambahkan PostgreSQL service.
- [ ] Set `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
- [ ] Set `APP_ENV=production`.
- [ ] Set `APP_BASE_URL=https://<railway-domain>`.
- [ ] Set `COOKIE_SECURE=true`.
- [ ] Generate dan set `SECRET_KEY`.
- [ ] Generate dan set `TOKEN_ENCRYPTION_KEY`.
- [ ] Set `ADMIN_EMAIL` dan `ADMIN_PASSWORD`.
- [ ] Set `AOL_CLIENT_ID` dan `AOL_CLIENT_SECRET`.
- [ ] Set `AOL_REDIRECT_URI=https://<railway-domain>/accurate/oauth/callback`.
- [ ] Set `AOL_SCOPES=glaccount_view department_view project_view journal_voucher_view`.
- [ ] Daftarkan URL callback yang sama di Area Developer Accurate Online.
- [ ] Generate public domain Railway.
- [ ] Deploy ulang.
- [ ] Login admin dan ganti password admin bila perlu.
- [ ] Buat akun trial test.
- [ ] Test OAuth AOL → pilih DB → sync → Neraca Department/Project.
- [ ] Verify trial hanya melihat CASH_BANK.
- [ ] Activate user dari Admin → verify full balance sheet + max 5 DB.

## Jika muncul `Invalid value for --port: $PORT`

1. Railway → service aplikasi → **Settings / Deploy**.
2. Hapus **Custom Start Command** jika berisi `uvicorn ... --port $PORT`.
3. Redeploy agar Railway memakai `Dockerfile CMD`.
4. Jika ingin memakai custom command, gunakan:
   `sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'`
5. Cek `/health` setelah deploy.
