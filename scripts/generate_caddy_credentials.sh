#!/bin/sh
set -eu

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

host="${1:-}"
username="${2:-user}"
output_file="${3:-$repo_root/credentials.md}"
caddyfile_path="${4:-$repo_root/config/caddy/Caddyfile.generated}"
env_file="${ENV_FILE:-$repo_root/config/gist-sub.env}"

if [ -z "$host" ]; then
  echo "Usage: $0 <host> [username] [output_md] [caddyfile_path]" >&2
  exit 1
fi

if [ ! -f "$env_file" ]; then
  echo "Missing env file: $env_file" >&2
  exit 1
fi

if ! command -v caddy >/dev/null 2>&1; then
  echo "Missing caddy in PATH" >&2
  exit 1
fi

set -a
. "$env_file"
set +a

path_token="${PATH_TOKEN:-}"
output_name="${OUTPUT_NAME:-}"
output_base="${OUTPUT_BASE:-$repo_root/data/sub}"

if [ -z "$path_token" ]; then
  echo "Missing PATH_TOKEN in $env_file" >&2
  exit 1
fi

if [ -z "$output_name" ]; then
  echo "Missing OUTPUT_NAME in $env_file" >&2
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
Output base: ${output_base}
Username: ${username}
Password: ${password}

Subscription URL:
${subscription_url}

Caddyfile snippet:
root * ${output_base}
@sub path /${path_token}/${output_name}
handle @sub {
    basicauth {
        ${username} ${hash}
    }
    file_server
}
"

output_dir="$(dirname "$output_file")"
if [ -n "$output_dir" ]; then
  mkdir -p "$output_dir"
fi

printf "%s" "$content" > "$output_file"
chmod 600 "$output_file"

output_dir="$(dirname "$caddyfile_path")"
if [ -n "$output_dir" ]; then
  mkdir -p "$output_dir"
fi

cat > "$caddyfile_path" <<EOF
${host} {
    root * ${output_base}

    @sub path /${path_token}/${output_name}
    handle @sub {
        basicauth {
            ${username} ${hash}
        }
        file_server
    }

    handle {
        respond 404
    }
}
EOF

echo "Saved: $output_file"
echo "Generated: $caddyfile_path"
