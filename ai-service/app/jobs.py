"""
In-process job registry for the AI service: progress, a log and cooperative cancellation.

The Java backend starts a job, then polls GET /jobs/{id}/status while a long stage runs. A cancel request sets an event that
the heavy loops check, and terminates any child process (COLMAP) the job registered.
"""
import threading
import time
from pathlib import Path

from .errors import Cancelled

_registry = {}
_guard = threading.Lock()


class JobContext:
    def __init__(self, job_id, log_file=None):
        self.job_id = job_id
        self.cancel_event = threading.Event()
        self.stage = "idle"
        self.progress = 0
        self.message = ""
        self.lines = []
        self.started = time.time()
        self.processes = []
        self.log_file = Path(log_file) if log_file else None

    def log(self, text):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        self.lines.append(line)
        self.lines = self.lines[-400:]
        if self.log_file:
            try:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                with self.log_file.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def update(self, stage=None, progress=None, message=None):
        if stage is not None:
            self.stage = stage
        if progress is not None:
            self.progress = int(max(0, min(100, progress)))
        if message is not None:
            self.message = message
            self.log(message)

    def check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    def cancel(self):
        self.cancel_event.set()
        for p in list(self.processes):
            try:
                p.terminate()
            except Exception:
                pass

    def snapshot(self):
        return {"job_id": self.job_id, "stage": self.stage, "progress": self.progress, "message": self.message,
                "cancelled": self.cancel_event.is_set(), "elapsed_sec": round(time.time() - self.started, 1),
                "log_tail": self.lines[-30:]}


def get(job_id, log_file=None, fresh=False):
    """Fetch (or create) the context for a job. A job id of None gets a throw-away context so callers never need a branch."""
    if not job_id:
        return JobContext(None, log_file)
    with _guard:
        ctx = _registry.get(job_id)
        if ctx is None or fresh:
            ctx = JobContext(job_id, log_file)
            _registry[job_id] = ctx
        elif log_file and ctx.log_file is None:
            ctx.log_file = Path(log_file)
        if len(_registry) > 50:  # keep memory flat: forget the oldest finished contexts
            for k in list(_registry)[:len(_registry) - 50]:
                _registry.pop(k, None)
        return ctx


def peek(job_id):
    with _guard:
        return _registry.get(job_id)
