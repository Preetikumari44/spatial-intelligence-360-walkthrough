import os
import tempfile

# must be set before the app package is imported
os.environ.setdefault("STORAGE_ROOT", tempfile.mkdtemp(prefix="spatial-test-"))
os.environ.setdefault("MEMORY_RESERVE_MB", "500")   # CI boxes are small; the guard itself is tested explicitly
os.environ.setdefault("SPLAT_MAX_SIDE", "96")

import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))        # lets tests import synth.py
