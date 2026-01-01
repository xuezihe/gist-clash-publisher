import json
import os
import tempfile
import time
from typing import Any, Dict


def load_status(status_path: str) -> Dict[str, Any]:
    try:
        with open(status_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp_file:
        temp_file.write(data)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_name = temp_file.name
    os.replace(temp_name, path)


def record_status(status_path: str, payload: Dict[str, Any]) -> None:
    current = load_status(status_path)
    current.update(payload)
    encoded = json.dumps(current, ensure_ascii=True, sort_keys=True).encode("utf-8") + b"\n"
    _atomic_write(status_path, encoded)


def log_event(event: str, payload: Dict[str, Any]) -> None:
    record = {"ts": int(time.time()), "event": event}
    record.update(payload)
    print(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
