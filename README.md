# Silvia Ping — portfolio CMS

An editorial portfolio and private, self-hosted CMS. The public site is served by the included Python service; project records live in SQLite and uploaded artwork is resized and encoded as WebP with `ffmpeg` before being served.

## Local development

```bash
export SILVIA_ADMIN_PASSWORD='choose-a-long-password'
python3 app.py
```

Open `http://localhost:5188`. The CMS is at `/admin`. See `deploy/deploy.sh` for the Macserver deployment path.

## Security and operation

- The password is never stored in the repository. The deployment script creates a server-only environment file with a generated password if one does not exist.
- Sessions use signed, HTTP-only cookies. Set `SILVIA_SESSION_SECRET` for a persistent custom signing key.
- Back up `/home/bruno/apps/silviaping/data/portfolio.sqlite3` and `/home/bruno/apps/silviaping/uploads/`.
- The preview uses an IP address and therefore has no TLS. Before mapping `SilviaPing.com`, add DNS and a Caddy host block so Caddy can issue HTTPS.
