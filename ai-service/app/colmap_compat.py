"""
COLMAP command-line compatibility.

COLMAP renamed many options between releases (for example --SiftExtraction.use_gpu became --FeatureExtraction.use_gpu in
the 4.x line). Instead of hard-coding one spelling, this module asks the installed binary what it supports
(`<command> -h`), then builds each command from the spellings that binary actually lists.

Rules:
  * A *required* option with no supported spelling raises ColmapCompatError that names the command, the spellings tried and
    the similar options the binary does list. Nothing is run with a guessed flag.
  * An *optional* option (thread counts, feature caps, ...) is silently left out when the binary does not list it, and the
    omission is recorded in `CommandSet.skipped` so the report can show it.
  * Only option names that appear in the help text are ever passed.
"""
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field

from . import colmap_locator, config
from .errors import PipelineError

HELP_COMMANDS = ("feature_extractor", "exhaustive_matcher", "sequential_matcher", "mapper", "model_converter")
# probed too, but a missing/unreadable help is not an error: only the dense-MVS path and extra refinement use them
OPTIONAL_HELP_COMMANDS = ("bundle_adjuster", "image_undistorter", "patch_match_stereo", "stereo_fusion")

# option group -> spellings, newest first. First one the binary lists wins.
GPU_EXTRACT = ("FeatureExtraction.use_gpu", "SiftExtraction.use_gpu")
MAX_SIZE = ("FeatureExtraction.max_image_size", "SiftExtraction.max_image_size")
MAX_FEATURES = ("SiftExtraction.max_num_features", "FeatureExtraction.max_num_features")
EXTRACT_THREADS = ("FeatureExtraction.num_threads", "SiftExtraction.num_threads")
GPU_MATCH = ("FeatureMatching.use_gpu", "SiftMatching.use_gpu")
MATCH_THREADS = ("FeatureMatching.num_threads", "SiftMatching.num_threads")
SEQ_OVERLAP = ("SequentialMatching.overlap",)
SEQ_LOOP = ("SequentialMatching.loop_detection",)
MAPPER_THREADS = ("Mapper.num_threads",)
MAPPER_BA_GPU = ("Mapper.ba_use_gpu",)
MAPPER_MAX_MODELS = ("Mapper.max_num_models",)

_OPT = re.compile(r"(?<![\w.-])--([A-Za-z_][\w.]*)")
_VERSION = re.compile(r"COLMAP\s+v?(\d+(?:\.\d+)*[\w.+-]*)", re.IGNORECASE)


class ColmapCompatError(PipelineError):
    """The installed COLMAP cannot do something this pipeline requires (HTTP 501: not implemented by that build)."""

    def __init__(self, message):
        super().__init__(message, 501)


@dataclass
class ColmapCaps:
    binary: str
    version: str | None
    options: dict = field(default_factory=dict)       # command -> set of option names (without the leading --)
    help_errors: dict = field(default_factory=dict)   # command -> why its help could not be read
    banner: str = ""                                  # first line(s) of `colmap help`, kept for the report
    cuda: bool | None = None                          # True/False when the banner says so, None when it does not

    def supports(self, command, *names):
        return any(n in self.options.get(command, ()) for n in names)

    def summary(self):
        return {"binary": self.binary, "version": self.version, "cuda": self.cuda, "banner": self.banner[:200], "commands_probed": {c: len(o) for c, o in self.options.items()}, "help_errors": self.help_errors}


@dataclass
class CommandSet:
    commands: list                                    # [(label, argv)]
    skipped: list = field(default_factory=list)       # optional options the binary does not have
    used: dict = field(default_factory=dict)          # logical name -> flag actually used


def parse_help(text: str) -> set:
    """Every --Option.name that appears in a help text."""
    return set(_OPT.findall(text or "")) - {"help", "version"}


def parse_cuda(text: str):
    """The banner of CUDA builds says "with CUDA"; CPU builds say "without CUDA". Anything else: unknown (None)."""
    low = (text or "").lower()
    if re.search(r"without\s+cuda|no\s+cuda|cuda\s*:\s*(off|disabled|no)", low):
        return False
    if re.search(r"with\s+cuda|cuda\s*:\s*(on|enabled|yes)", low):
        return True
    return None


def parse_version(text: str):
    m = _VERSION.search(text or "")
    return m.group(1) if m else None


def _run_help(binary, args, timeout=60, want_code=False):
    """Run `binary args` with COLMAP's own bin folder on PATH (Windows finds its DLLs there)."""
    p = subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout, env=colmap_locator.env_for(binary), errors="replace")
    text = (p.stdout or "") + "\n" + (p.stderr or "")
    return (text, p.returncode) if want_code else text


def probe(binary: str) -> ColmapCaps:
    """Ask the binary what it supports. Never raises for a missing option; raises ColmapCompatError only if it cannot run at all."""
    caps = ColmapCaps(binary=binary, version=None)
    try:
        top, code = _run_help(binary, ["help"], want_code=True)
        why = colmap_locator.describe_exit(code)
        if why:
            raise ColmapCompatError(f"COLMAP at '{binary}' failed to start: {why}")
        caps.version = parse_version(top)
        if caps.version is None:   # some builds only print the banner for -h
            top = _run_help(binary, ["-h"])
            caps.version = parse_version(top)
        caps.banner = "\n".join(top.strip().splitlines()[:3])
        caps.cuda = parse_cuda(top)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ColmapCompatError(f"COLMAP at '{binary}' could not be started: {e}. Check COLMAP_BIN in .env or re-run scripts\\install-colmap.ps1.") from e
    for cmd in HELP_COMMANDS:
        try:
            text = _run_help(binary, [cmd, "-h"])
        except (OSError, subprocess.TimeoutExpired) as e:
            caps.help_errors[cmd] = str(e)
            continue
        found = parse_help(text)
        if not found:
            caps.help_errors[cmd] = "help output listed no options"
        caps.options[cmd] = found
    for cmd in OPTIONAL_HELP_COMMANDS:
        try:
            found = parse_help(_run_help(binary, [cmd, "-h"]))
        except (OSError, subprocess.TimeoutExpired):
            found = set()
        if found:
            caps.options[cmd] = found
    return caps


_cache = {}
_cache_lock = threading.Lock()


def get_caps(binary: str, refresh=False) -> ColmapCaps:
    with _cache_lock:
        if not refresh and binary in _cache:
            return _cache[binary]
    caps = probe(binary)
    with _cache_lock:
        _cache[binary] = caps
    return caps


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _similar(caps, command, spelling):
    group = spelling.split(".")[0]
    near = sorted(o for o in caps.options.get(command, ()) if o.split(".")[0] == group or o.split(".")[-1] == spelling.split(".")[-1])
    return near[:8]


def _need(caps, command, spellings, logical):
    for s in spellings:
        if s in caps.options.get(command, ()):
            return s
    raise ColmapCompatError(
        f"The installed COLMAP {caps.version or '(unknown version)'} does not support any of {list(spellings)} for '{command}' "
        f"(needed for: {logical}). Options it lists with a similar name: {_similar(caps, command, spellings[0]) or 'none'}. "
        "Update this project's colmap_compat.py for your COLMAP release, or set SFM_BACKEND=opencv for flat video. "
        "Nothing was run with a guessed option.")


def _maybe(caps, command, spellings, logical, skipped):
    for s in spellings:
        if s in caps.options.get(command, ()):
            return s
    skipped.append({"command": command, "option": spellings[0], "purpose": logical})
    return None


def _require_command(caps, command):
    if command not in caps.options or not caps.options[command]:
        why = caps.help_errors.get(command, "its help text could not be read")
        raise ColmapCompatError(f"COLMAP {caps.version or ''} command '{command}' is unusable: {why}.")


def build_commands(caps: ColmapCaps, *, db, images, sparse, max_image_size, max_features, threads, n_images, exhaustive_limit,
                   overlap, single_camera=True, camera_model="SIMPLE_RADIAL") -> CommandSet:  # noqa: C901
    """Feature extraction, matching and mapping for CPU-only operation, using only options `caps` lists."""
    b = caps.binary
    skipped, used = [], {}
    cmds = []
    s = str

    _require_command(caps, "feature_extractor")
    fe = "feature_extractor"
    flag_gpu = _need(caps, fe, GPU_EXTRACT, "forcing CPU feature extraction (no CUDA on this machine)")
    flag_size = _need(caps, fe, MAX_SIZE, "limiting image size to save memory")
    for req in ("ImageReader.single_camera", "ImageReader.camera_model", "database_path", "image_path"):
        _need(caps, fe, (req,), req)
    used.update(extract_gpu=flag_gpu, extract_max_size=flag_size)
    args = [b, fe, "--database_path", s(db), "--image_path", s(images),
            "--ImageReader.single_camera", "1" if single_camera else "0", "--ImageReader.camera_model", camera_model,
            f"--{flag_gpu}", "0", f"--{flag_size}", s(max_image_size)]
    f_feat = _maybe(caps, fe, MAX_FEATURES, "capping features per image", skipped)
    if f_feat:
        args += [f"--{f_feat}", s(max_features)]
        used["max_features"] = f_feat
    f_thr = _maybe(caps, fe, EXTRACT_THREADS, "limiting extraction threads", skipped)
    if f_thr:
        args += [f"--{f_thr}", s(threads)]
    cmds.append(("feature_extractor", args))

    exhaustive = n_images <= exhaustive_limit
    mcmd = "exhaustive_matcher" if exhaustive else "sequential_matcher"
    _require_command(caps, mcmd)
    flag_mgpu = _need(caps, mcmd, GPU_MATCH, "forcing CPU feature matching")
    used["match_gpu"] = flag_mgpu
    margs = [b, mcmd, "--database_path", s(db), f"--{flag_mgpu}", "0"]
    f_mthr = _maybe(caps, mcmd, MATCH_THREADS, "limiting matcher threads", skipped)
    if f_mthr:
        margs += [f"--{f_mthr}", s(threads)]
    if not exhaustive:
        margs += [f"--{_need(caps, mcmd, SEQ_OVERLAP, 'sequential matching window')}", s(overlap)]
        f_loop = _maybe(caps, mcmd, SEQ_LOOP, "vocabulary-tree loop detection (needs a vocab file)", skipped)
        vocab = config.COLMAP_VOCAB_TREE
        f_vocab = _maybe(caps, mcmd, ("SequentialMatching.vocab_tree_path",), "vocabulary tree for loop closure", skipped) if vocab else None
        if f_loop and vocab and f_vocab and os.path.isfile(vocab):
            margs += [f"--{f_loop}", "1", f"--{f_vocab}", vocab]
            used["loop_detection"] = True
        elif f_loop:
            margs += [f"--{f_loop}", "0"]
            used["loop_detection"] = False
    cmds.append((mcmd, margs))

    _require_command(caps, "mapper")
    for req in ("database_path", "image_path", "output_path"):
        _need(caps, "mapper", (req,), req)
    aargs = [b, "mapper", "--database_path", s(db), "--image_path", s(images), "--output_path", s(sparse)]
    f_mt = _maybe(caps, "mapper", MAPPER_THREADS, "limiting mapper threads", skipped)
    if f_mt:
        aargs += [f"--{f_mt}", s(threads)]
    f_bag = _maybe(caps, "mapper", MAPPER_BA_GPU, "forcing CPU bundle adjustment", skipped)
    if f_bag:
        aargs += [f"--{f_bag}", "0"]
    cmds.append(("mapper", aargs))
    return CommandSet(commands=cmds, skipped=skipped, used=used)


def build_model_converter(caps: ColmapCaps, model_dir, out_dir):
    _require_command(caps, "model_converter")
    for req in ("input_path", "output_path", "output_type"):
        _need(caps, "model_converter", (req,), req)
    return [caps.binary, "model_converter", "--input_path", str(model_dir), "--output_path", str(out_dir), "--output_type", "TXT"]


def dense_mvs_support(caps: ColmapCaps) -> dict:
    """COLMAP's patch_match_stereo / stereo_fusion need CUDA in every release. A no-CUDA build lists the commands but cannot
    run them ("Dense stereo reconstruction requires CUDA"), so the pipeline must not try, and must say why."""
    have = all(caps.options.get(c) for c in ("image_undistorter", "patch_match_stereo", "stereo_fusion"))
    if not have:
        return {"supported": False, "reason": "this COLMAP build does not list image_undistorter / patch_match_stereo / stereo_fusion"}
    if caps.cuda is not True:
        state = "was built without CUDA" if caps.cuda is False else "does not report CUDA support (treated as CPU-only)"
        return {"supported": False, "reason": f"COLMAP {caps.version or ''} {state}; patch_match_stereo requires CUDA. "
                                              "Dense geometry comes from the Open3D depth-fusion path instead."}
    return {"supported": True, "reason": None}


def build_undistorter(caps: ColmapCaps, *, images, sparse_model, out_dir, max_image_size):
    _require_command(caps, "image_undistorter")
    for req in ("image_path", "input_path", "output_path"):
        _need(caps, "image_undistorter", (req,), req)
    argv = [caps.binary, "image_undistorter", "--image_path", str(images), "--input_path", str(sparse_model), "--output_path", str(out_dir),
            "--output_type", "COLMAP"] if "output_type" in caps.options["image_undistorter"] else \
           [caps.binary, "image_undistorter", "--image_path", str(images), "--input_path", str(sparse_model), "--output_path", str(out_dir)]
    flag = _maybe(caps, "image_undistorter", ("max_image_size", "Undistortion.max_image_size"), "limit undistorted size", [])
    if flag:
        argv += [f"--{flag}", str(max_image_size)]
    return argv


def build_patch_match(caps: ColmapCaps, *, workspace, max_image_size, threads):
    sup = dense_mvs_support(caps)
    if not sup["supported"]:
        raise ColmapCompatError(sup["reason"])
    _require_command(caps, "patch_match_stereo")
    _need(caps, "patch_match_stereo", ("workspace_path",), "workspace_path")
    argv = [caps.binary, "patch_match_stereo", "--workspace_path", str(workspace)]
    for names, val in ((("PatchMatchStereo.max_image_size",), max_image_size), (("PatchMatchStereo.num_threads",), threads)):
        f = _maybe(caps, "patch_match_stereo", names, "memory/thread limit", [])
        if f:
            argv += [f"--{f}", str(val)]
    return argv


def build_stereo_fusion(caps: ColmapCaps, *, workspace, out_ply, max_image_size, threads):
    sup = dense_mvs_support(caps)
    if not sup["supported"]:
        raise ColmapCompatError(sup["reason"])
    _require_command(caps, "stereo_fusion")
    for req in ("workspace_path", "output_path"):
        _need(caps, "stereo_fusion", (req,), req)
    argv = [caps.binary, "stereo_fusion", "--workspace_path", str(workspace), "--output_path", str(out_ply)]
    for names, val in ((("StereoFusion.max_image_size",), max_image_size), (("StereoFusion.num_threads",), threads)):
        f = _maybe(caps, "stereo_fusion", names, "memory/thread limit", [])
        if f:
            argv += [f"--{f}", str(val)]
    return argv


def build_bundle_adjuster(caps: ColmapCaps, *, model_in, model_out, threads=None):
    """Optional extra global refinement of a finished model (the mapper already runs bundle adjustment internally)."""
    _require_command(caps, "bundle_adjuster")
    for req in ("input_path", "output_path"):
        _need(caps, "bundle_adjuster", (req,), req)
    argv = [caps.binary, "bundle_adjuster", "--input_path", str(model_in), "--output_path", str(model_out)]
    f = _maybe(caps, "bundle_adjuster", ("BundleAdjustmentCeres.use_gpu", "BundleAdjustment.use_gpu"), "force CPU", [])
    if f:
        argv += [f"--{f}", "0"]
    return argv


# Exit codes / messages that mean "the process ran out of memory", so a smaller configuration is worth one automatic retry.
_OOM_CODES = {137, -9, 3221225477, -1073741819, 3221226505, -1073740791, 3221225786}
_OOM_WORDS = ("bad_alloc", "out of memory", "cannot allocate memory", "std::bad_alloc")


def looks_like_oom(returncode, text) -> bool:
    low = (text or "").lower()
    return returncode in _OOM_CODES or any(w in low for w in _OOM_WORDS)
