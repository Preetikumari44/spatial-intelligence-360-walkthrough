"""
Where COLMAP lives and how to start it.

Resolution order (first hit wins, and the choice is reported, never silent):
  1. COLMAP_BIN in .env, if it points at an existing file (an explicit override always beats the bundle)
  2. the bundled build:  <repo>/tools/colmap/bin/colmap.exe   (Windows)  or  <repo>/tools/colmap/bin/colmap  (other OS)
  3. COLMAP_BIN / "colmap" resolved through PATH

Windows resolves COLMAP's DLLs from the folder of the executable and from PATH, so every COLMAP child process gets the
bin folder prepended to PATH (see runtime_env). Nothing is installed globally and the user never edits PATH.

The bundled build is COLMAP 1.0 without CUDA. The Microsoft Visual C++ 2015-2022 runtime is NOT part of that package;
check_vc_runtime() reports whether it is installed.
"""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import config

IS_WINDOWS = os.name == "nt"
EXE = "colmap.exe" if IS_WINDOWS else "colmap"

# Windows NTSTATUS codes seen as process exit codes when the loader cannot start an executable
DLL_NOT_FOUND = {3221225781, -1073741515}          # 0xC0000135 STATUS_DLL_NOT_FOUND
ENTRYPOINT_NOT_FOUND = {3221225785, -1073741511}   # 0xC0000139
BAD_IMAGE = {3221225595, -1073741701}              # 0xC000007B (32/64 bit mismatch or damaged DLL)

# the runtime DLLs the bundled colmap.exe imports that are not shipped in its bin folder
VC_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcomp140.dll")


def project_root() -> Path:
    """<repo>: ai-service/app/colmap_locator.py -> three levels up."""
    return Path(__file__).resolve().parents[2]


def bundled_dir() -> Path:
    return Path(os.environ.get("COLMAP_BUNDLE_DIR") or (project_root() / "tools" / "colmap"))


def bundled_exe() -> Path:
    return bundled_dir() / "bin" / EXE


@dataclass
class Located:
    path: str | None
    source: str                      # override | bundled | path | none
    bin_dir: str | None = None
    tried: list = field(default_factory=list)

    @property
    def found(self):
        return self.path is not None

    def as_dict(self):
        return {"found": self.found, "path": self.path, "source": self.source, "bin_dir": self.bin_dir, "tried": self.tried}


def _usable(p) -> bool:
    return bool(p) and Path(p).is_file()


def locate(override: str | None = None) -> Located:
    """Find COLMAP without starting it. `override` defaults to config.COLMAP_BIN."""
    raw = (config.COLMAP_BIN if override is None else override or "").strip().strip('"')
    tried = []
    explicit = raw and raw.lower() not in ("colmap", "colmap.exe", "auto")
    if explicit:
        tried.append(f"COLMAP_BIN={raw}")
        p = Path(raw)
        if p.is_dir():                                   # tolerate COLMAP_BIN pointing at the folder
            for cand in (p / EXE, p / "bin" / EXE):
                if cand.is_file():
                    p = cand
                    break
        if p.is_file():
            return Located(str(p.resolve()), "override", str(p.resolve().parent), tried)
        hit = shutil.which(raw)
        if hit:
            return Located(str(Path(hit).resolve()), "override", str(Path(hit).resolve().parent), tried)
    b = bundled_exe()
    tried.append(f"bundled {b}")
    if _usable(b):
        return Located(str(b.resolve()), "bundled", str(b.resolve().parent), tried)
    tried.append("PATH colmap")
    hit = shutil.which("colmap")
    if hit:
        return Located(str(Path(hit).resolve()), "path", str(Path(hit).resolve().parent), tried)
    return Located(None, "none", None, tried)


def runtime_env(bin_dir=None, base=None) -> dict:
    """Environment for every COLMAP child process: bin dir first on PATH (DLL lookup), headless Qt, no GUI plugins needed."""
    env = dict(base if base is not None else os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    if bin_dir:
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        plugins = Path(bin_dir).parent / "plugins"
        if plugins.is_dir():
            env.setdefault("QT_PLUGIN_PATH", str(plugins))
    return env


def env_for(binary: str) -> dict:
    return runtime_env(Path(binary).resolve().parent if binary else None)


def describe_exit(code) -> str | None:
    """A plain explanation for loader failures, or None for ordinary exit codes."""
    if code in DLL_NOT_FOUND:
        return ("Windows could not load a DLL that colmap.exe needs (exit 0xC0000135). The most common cause is the missing "
                "Microsoft Visual C++ 2015-2022 Redistributable (x64): install it from https://aka.ms/vs/17/release/vc_redist.x64.exe "
                "or run scripts\\install-colmap.ps1. Also make sure tools\\colmap\\bin was not partly deleted.")
    if code in ENTRYPOINT_NOT_FOUND:
        return "A DLL was found but it is the wrong version (exit 0xC0000139). Another program's DLLs may be shadowing COLMAP's; use the bundled bin folder."
    if code in BAD_IMAGE:
        return "A DLL is damaged or the wrong architecture (exit 0xC000007B). Re-extract colmap-x64-windows-nocuda.zip into tools\\colmap."
    return None


def check_vc_runtime() -> dict:
    """Are the Visual C++ runtime DLLs resolvable? Only meaningful on Windows; elsewhere reports not_applicable."""
    if not IS_WINDOWS:
        return {"applicable": False, "ok": True, "missing": [], "note": "Windows-only check"}
    dirs = [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
    loc = locate()
    if loc.bin_dir:
        dirs.insert(0, Path(loc.bin_dir))
    missing = [d for d in VC_DLLS if not any((x / d).is_file() for x in dirs)]
    return {"applicable": True, "ok": not missing, "missing": missing,
            "fix": None if not missing else "Install https://aka.ms/vs/17/release/vc_redist.x64.exe (or run scripts\\install-colmap.ps1)"}


def bundle_report() -> dict:
    """Does the bundled folder look complete? Counts DLLs; cannot prove they all load (only starting colmap.exe proves that)."""
    b = bundled_dir()
    bin_dir = b / "bin"
    dlls = sorted(p.name for p in bin_dir.glob("*.dll")) if bin_dir.is_dir() else []
    return {"folder": str(b), "exe_present": (bin_dir / EXE).is_file(), "dll_count": len(dlls),
            "plugins_present": (b / "plugins").is_dir(),
            "has_core_dlls": all(any(d.lower().startswith(k) for d in dlls) for k in ("qt6core", "ceres", "boost_", "openimageio"))}


def start_check(binary: str, timeout=60) -> dict:
    """Start the executable (`colmap help`) and report what happened. Never raises."""
    out = {"binary": binary, "started": False, "exit_code": None, "explanation": None, "banner": None}
    try:
        p = subprocess.run([binary, "help"], capture_output=True, text=True, timeout=timeout, errors="replace", env=env_for(binary))
    except subprocess.TimeoutExpired:
        out["explanation"] = f"colmap did not answer 'help' within {timeout}s"
        return out
    except OSError as e:
        out["explanation"] = f"colmap could not be started: {e}"
        return out
    text = (p.stdout or "") + "\n" + (p.stderr or "")
    out["exit_code"] = p.returncode
    out["explanation"] = describe_exit(p.returncode)
    out["banner"] = next((ln.strip() for ln in text.splitlines() if "colmap" in ln.lower()), None)
    out["started"] = p.returncode == 0 and bool(text.strip())
    return out
