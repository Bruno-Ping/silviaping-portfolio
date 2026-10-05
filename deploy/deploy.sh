#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${1:-bruno@192.168.1.23}"
REMOTE="/home/bruno/apps/silviaping"

ssh -o BatchMode=yes "$HOST" "mkdir -p '$REMOTE/public' '$REMOTE/data' '$REMOTE/uploads' '/home/bruno/.config/systemd/user'"
tar -C "$ROOT" --exclude='.git' --exclude='data' --exclude='uploads' --exclude='remote.env' -cf - app.py public deploy/silviaping.service | ssh -o BatchMode=yes "$HOST" "tar -xf - -C '$REMOTE'"
ssh -o BatchMode=yes "$HOST" "
  if [ ! -f '$REMOTE/remote.env' ]; then
    umask 077
    printf 'SILVIA_ADMIN_PASSWORD=%s\\nSILVIA_SESSION_SECRET=%s\\n' \"\$(openssl rand -base64 24)\" \"\$(openssl rand -hex 32)\" > '$REMOTE/remote.env'
    echo 'Generated a private admin password in server-only remote.env.'
  fi
  cp '$REMOTE/deploy/silviaping.service' '/home/bruno/.config/systemd/user/silviaping.service'
  systemctl --user daemon-reload
  systemctl --user enable --now silviaping.service
"
echo "Deployment complete. Add the Caddy route, then visit http://192.168.1.23/silvia/"
