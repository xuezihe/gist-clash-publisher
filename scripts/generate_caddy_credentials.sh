#!/bin/sh
set -eu

host="${1:-}"
username="${2:-user}"
output_file="${3:-/etc/gist-sub-credentials.md}"

if [ -z "$host" ]; then
  echo "Usage: $0 <host> [username] [output_md]" >&2
  exit 1
fi

if [ ! -f /etc/gist-sub.env ]; then
  echo "Missing /etc/gist-sub.env" >&2
  exit 1
fi

if ! command -v caddy >/dev/null 2>&1; then
  echo "Missing caddy in PATH" >&2
  exit 1
fi

set -a
. /etc/gist-sub.env
set +a

path_token="${PATH_TOKEN:-}"
output_name="${OUTPUT_NAME:-}"

if [ -z "$path_token" ]; then
  echo "Missing PATH_TOKEN in /etc/gist-sub.env" >&2
  exit 1
fi

if [ -z "$output_name" ]; then
  echo "Missing OUTPUT_NAME in /etc/gist-sub.env" >&2
  exit 1
fi

password="${PASSWORD:-}"
if [ -z "$password" ]; then
  if command -v openssl >/dev/null 2>&1; then
    password="$(openssl rand -base64 18 | tr -d '\n' | tr -d '/+=')"
  else
    password="$(python3 - <<'PY'
import secrets
import string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(24)))
PY
)"
  fi
fi

hash="$(caddy hash-password --plaintext "$password")"

subscription_url="https://${username}:${password}@${host}/${path_token}/${output_name}"

content="# Subscription Credentials

Host: ${host}
Username: ${username}
Password: ${password}

Subscription URL:
${subscription_url}

Caddyfile snippet:
@sub path /${path_token}/${output_name}
basicauth @sub {
    ${username} ${hash}
}
"

printf "%s" "$content" > "$output_file"
chmod 600 "$output_file"

echo "Saved: $output_file"
