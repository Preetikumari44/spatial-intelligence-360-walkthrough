"""work/report.json: the single honest record of what each stage of a reconstruction did, with the device it really used."""
import json
import threading
import time
from pathlib import Path

_lock = threading.Lock()
STATUSES = ("ok", "failed", "skipped", "unavailable")


def _path(work: Path) -> Path:
    return work / "report.json"


def load(work: Path) -> dict:
    p = _path(work)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {"stages": {}, "outputs": [], "execution": {}}


def _save(work: Path, data: dict):
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _path(work).write_text(json.dumps(data, indent=1))


def set_execution(work: Path, **fields):
    with _lock:
        d = load(work)
        d["execution"].update(fields)
        _save(work, d)


def stage(work: Path, name: str, status: str, message: str = "", **details):
    assert status in STATUSES
    with _lock:
        d = load(work)
        d["stages"][name] = {"status": status, "message": message, **details}
        _save(work, d)


def output(work: Path, key: str, rel_path: str, kind: str, size_bytes: int, label: str, **extra):
    """Register a produced file. Only call this after the file exists on disk."""
    with _lock:
        d = load(work)
        d["outputs"] = [o for o in d["outputs"] if o["key"] != key]
        d["outputs"].append({"key": key, "path": rel_path, "kind": kind, "size_bytes": size_bytes, "label": label, **extra})
        _save(work, d)
