#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import tempfile
import urllib.request
from typing import Optional
from urllib.error import HTTPError, URLError

from lib.registry import load_registry
from lib.status import record_status
from lib.validators import validate_content

def env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    return value if (value is not None and value != "") else default


def http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        status = response.status
        response_headers = {k.lower(): v for k, v in response.headers.items()}
        body = response.read()
        return status, response_headers, body


def atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False) as temp_file:
        temp_file.write(data)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_name = temp_file.name
    os.replace(temp_name, str(path))


def main() -> int:
    gist_id = env("GIST_ID")
    if not gist_id:
        print("Missing GIST_ID", file=sys.stderr)
        return 2

    gist_file = env("GIST_FILE")
    token = env("GITHUB_TOKEN")

    output_base = pathlib.Path(env("OUTPUT_BASE", "/var/www/sub"))
    path_token = env("PATH_TOKEN")
    if not path_token:
        print("Missing PATH_TOKEN (generate once: openssl rand -hex 16)", file=sys.stderr)
        return 2

    output_name = env("OUTPUT_NAME", "proxies.yaml")
    out_path = output_base / path_token / output_name
    etag_path = out_path.with_suffix(out_path.suffix + ".etag")
    status_path = out_path.with_suffix(out_path.suffix + ".status.json")

    _registry = load_registry(env("REGISTRY_PATH", "/etc/gist-sub.users.json"))

    api_url = f"https://api.github.com/gists/{gist_id}"
    headers = {
        "User-Agent": "gist-sub-fetcher/1.0",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if etag_path.exists():
        try:
            headers["If-None-Match"] = etag_path.read_text().strip()
        except Exception:
            pass

    try:
        _, response_headers, body = http_get(api_url, headers)
    except HTTPError as exc:
        if exc.code == 304:
            print("No change (304) - skip")
            return 0
        print(f"HTTPError: {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1

    new_etag = response_headers.get("etag")
    if new_etag:
        atomic_write(etag_path, new_etag.encode("utf-8"))

    meta = json.loads(body.decode("utf-8"))
    files = meta.get("files", {})
    if not files:
        print("No files in gist", file=sys.stderr)
        return 1

    if gist_file:
        file_meta = files.get(gist_file)
        if not file_meta:
            print(
                f"GIST_FILE '{gist_file}' not found. Available: {list(files.keys())}",
                file=sys.stderr,
            )
            return 1
    else:
        file_meta = next(iter(files.values()))

    raw_url = file_meta.get("raw_url")
    if not raw_url:
        print("Missing raw_url in gist file metadata", file=sys.stderr)
        return 1

    raw_headers = {"User-Agent": "gist-sub-fetcher/1.0"}
    if token:
        raw_headers["Authorization"] = f"Bearer {token}"

    try:
        _, _, raw = http_get(raw_url, raw_headers)
    except Exception as exc:
        print(f"Failed to download raw: {exc}", file=sys.stderr)
        return 1

    if raw.lstrip().startswith(b"<!doctype html") or raw.lstrip().startswith(b"<html"):
        print("Raw looks like HTML; refusing to write.", file=sys.stderr)
        record_status(str(status_path), {"status": "invalid", "reason": "html"})
        return 1

    ok, reason = validate_content(raw)
    if not ok:
        record_status(str(status_path), {"status": "invalid", "reason": reason})
        return 1

    atomic_write(out_path, raw)
    record_status(str(status_path), {"status": "success", "bytes": len(raw)})
    print(f"Updated: {out_path} ({len(raw)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
