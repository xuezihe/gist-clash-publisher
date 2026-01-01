#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import tempfile
import time
import urllib.request
from typing import Optional
from urllib.error import HTTPError, URLError

from lib.registry import load_registry
from lib.status import log_event, record_status
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
    start_time = time.monotonic()
    attempt_ts = int(time.time())

    gist_id = env("GIST_ID")
    if not gist_id:
        log_event(
            "config_error",
            {"status": "error", "error": "missing_gist_id"},
        )
        return 2

    gist_file = env("GIST_FILE")
    token = env("GITHUB_TOKEN")

    default_output_base = pathlib.Path(__file__).resolve().parents[1] / "data" / "sub"
    output_base = pathlib.Path(env("OUTPUT_BASE", str(default_output_base)))
    path_token = env("PATH_TOKEN")
    if not path_token:
        log_event(
            "config_error",
            {"status": "error", "error": "missing_path_token"},
        )
        return 2

    output_name = env("OUTPUT_NAME", "proxies.yaml")
    out_path = output_base / path_token / output_name
    etag_path = out_path.with_suffix(out_path.suffix + ".etag")
    status_path = out_path.parent / "status.json"

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

    record_status(
        str(status_path),
        {
            "last_attempt_ts": attempt_ts,
            "status": "started",
        },
    )
    log_event(
        "fetch_start",
        {"gist_id": gist_id, "user_token": path_token, "status": "started"},
    )

    try:
        _, response_headers, body = http_get(api_url, headers)
    except HTTPError as exc:
        if exc.code == 304:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            etag = None
            if exc.headers:
                etag = exc.headers.get("ETag")
            status_payload = {
                "last_attempt_ts": attempt_ts,
                "status": "not_modified",
                "duration_ms": duration_ms,
                "last_error": None,
            }
            if etag:
                status_payload["etag"] = etag
            record_status(str(status_path), status_payload)
            log_event(
                "fetch_not_modified",
                {
                    "gist_id": gist_id,
                    "user_token": path_token,
                    "etag": etag,
                    "duration_ms": duration_ms,
                    "status": "not_modified",
                },
            )
            return 0
        duration_ms = int((time.monotonic() - start_time) * 1000)
        error_message = f"http_error:{exc.code}:{exc.reason}"
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "error",
                "last_error": error_message,
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_error",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "error",
                "error": error_message,
                "duration_ms": duration_ms,
            },
        )
        return 1
    except (URLError, TimeoutError) as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        error_message = f"network_error:{exc}"
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "error",
                "last_error": error_message,
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_error",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "error",
                "error": error_message,
                "duration_ms": duration_ms,
            },
        )
        return 1

    new_etag = response_headers.get("etag")
    if new_etag:
        atomic_write(etag_path, new_etag.encode("utf-8"))

    meta = json.loads(body.decode("utf-8"))
    files = meta.get("files", {})
    if not files:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        error_message = "no_files_in_gist"
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "error",
                "last_error": error_message,
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_error",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "error",
                "error": error_message,
                "duration_ms": duration_ms,
            },
        )
        return 1

    if gist_file:
        file_meta = files.get(gist_file)
        if not file_meta:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_message = f"gist_file_not_found:{gist_file}"
            record_status(
                str(status_path),
                {
                    "last_attempt_ts": attempt_ts,
                    "status": "error",
                    "last_error": error_message,
                    "duration_ms": duration_ms,
                },
            )
            log_event(
                "fetch_error",
                {
                    "gist_id": gist_id,
                    "user_token": path_token,
                    "status": "error",
                    "error": error_message,
                    "duration_ms": duration_ms,
                },
            )
            return 1
    else:
        file_meta = next(iter(files.values()))

    raw_url = file_meta.get("raw_url")
    if not raw_url:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        error_message = "missing_raw_url"
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "error",
                "last_error": error_message,
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_error",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "error",
                "error": error_message,
                "duration_ms": duration_ms,
            },
        )
        return 1

    raw_headers = {"User-Agent": "gist-sub-fetcher/1.0"}
    if token:
        raw_headers["Authorization"] = f"Bearer {token}"

    try:
        _, _, raw = http_get(raw_url, raw_headers)
    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        error_message = f"raw_download_failed:{exc}"
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "error",
                "last_error": error_message,
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_error",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "error",
                "error": error_message,
                "duration_ms": duration_ms,
            },
        )
        return 1

    if raw.lstrip().startswith(b"<!doctype html") or raw.lstrip().startswith(b"<html"):
        duration_ms = int((time.monotonic() - start_time) * 1000)
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "invalid",
                "last_error": "html_response",
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_invalid",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "invalid",
                "error": "html_response",
                "duration_ms": duration_ms,
            },
        )
        return 1

    ok, reason = validate_content(raw)
    if not ok:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        record_status(
            str(status_path),
            {
                "last_attempt_ts": attempt_ts,
                "status": "invalid",
                "last_error": reason,
                "duration_ms": duration_ms,
            },
        )
        log_event(
            "fetch_invalid",
            {
                "gist_id": gist_id,
                "user_token": path_token,
                "status": "invalid",
                "error": reason,
                "duration_ms": duration_ms,
            },
        )
        return 1

    sha256 = hashlib.sha256(raw).hexdigest()
    atomic_write(out_path, raw)
    duration_ms = int((time.monotonic() - start_time) * 1000)
    status_payload = {
        "last_attempt_ts": attempt_ts,
        "last_success_ts": attempt_ts,
        "status": "success",
        "sha256": sha256,
        "bytes": len(raw),
        "duration_ms": duration_ms,
        "last_error": None,
    }
    if new_etag:
        status_payload["etag"] = new_etag
    record_status(str(status_path), status_payload)
    log_event(
        "fetch_success",
        {
            "gist_id": gist_id,
            "user_token": path_token,
            "etag": new_etag,
            "sha256": sha256,
            "bytes": len(raw),
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
