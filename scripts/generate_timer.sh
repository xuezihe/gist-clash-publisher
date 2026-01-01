#!/bin/sh
set -eu

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

env_file="${1:-}"
output_file="${2:-}"

if [ -z "$env_file" ]; then
  if [ -f "$repo_root/config/gist-sub.env" ]; then
    env_file="$repo_root/config/gist-sub.env"
  elif [ -f "$repo_root/config/gist-sub.env.example" ]; then
    env_file="$repo_root/config/gist-sub.env.example"
  else
    env_file=""
  fi
fi

if [ -z "$output_file" ]; then
  output_file="$repo_root/config/systemd/gist-sub.timer"
fi

if [ ! -f "$env_file" ]; then
  echo "Env file not found: $env_file" >&2
  exit 1
fi

set -a
. "$env_file"
set +a

interval_minutes="${INTERVAL_MINUTES:-5}"

content="[Unit]
Description=Run gist-sub fetch periodically

[Timer]
OnBootSec=30
OnUnitActiveSec=${interval_minutes}min
Persistent=true

[Install]
WantedBy=timers.target
"

if [ "$output_file" = "-" ]; then
  printf "%s" "$content"
  exit 0
fi

output_dir="$(dirname "$output_file")"
if [ -n "$output_dir" ]; then
  mkdir -p "$output_dir"
fi

printf "%s" "$content" > "$output_file"
