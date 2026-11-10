"""
Memory-aware reconstruction plan.

Picks image size, image count, feature cap and matcher strategy from the RAM that is actually free right now, instead of
refusing to start when RAM is merely tight. The tiers are heuristics (documented in docs/LOW_MEMORY.md), not measurements:
the real COLMAP peak depends on the footage. If a COLMAP stage still dies from memory exhaustion, reconstruct.py steps down
one tier and retries once.
"""
from dataclasses import dataclass, asdict

from . import config
from .errors import PipelineError

TIERS = ("normal", "low", "minimal")


@dataclass
class Plan:
    tier: str
    max_side: int
    max_images: int
    max_features: int
    threads: int
    exhaustive_limit: int
    overlap: int
    note: str

    def as_dict(self):
        return asdict(self)


def _scale(tier, threads):
    base_side, base_imgs, base_feat = config.SFM_MAX_SIDE, config.SFM_MAX_IMAGES, config.SFM_FEATURES
    if tier == "normal":
        return Plan("normal", base_side, base_imgs, base_feat, threads, 120, 12, "full configured quality")
    if tier == "low":
        return Plan("low", min(base_side, 720), min(base_imgs, 60), min(base_feat, 3000), min(threads, 2), 60, 10,
                    "low-memory mode: smaller images, fewer frames, 2 threads")
    return Plan("minimal", min(base_side, 512), min(base_imgs, 36), min(base_feat, 2000), 1, 36, 8,
                "minimal-memory mode: 512 px images, 36 frames, 1 thread (expect a coarser model)")


def choose_tier(free_mb):
    """free_mb None means unknown (psutil missing): assume the configured quality and let the OOM retry catch trouble."""
    mode = config.LOW_MEMORY_MODE
    if mode in TIERS:
        return mode
    if free_mb is None:
        return "normal"
    if free_mb >= config.MEMORY_NORMAL_MB:
        return "normal"
    if free_mb >= config.MEMORY_LOW_MB:
        return "low"
    return "minimal"


def make_plan(free_mb, threads, tier=None):
    if free_mb is not None and free_mb < config.MIN_FREE_RAM_MB:
        raise PipelineError(
            f"Only {free_mb} MB of RAM is free and at least {config.MIN_FREE_RAM_MB} MB is needed even in the smallest mode. "
            "Close browser tabs and other programs, then retry. If it is still tight, set LOW_MEMORY_MODE=minimal and "
            "FRAME_TARGET_FPS=1 in .env, restart the AI service, and upload the video again.", 503)
    return _scale(tier or choose_tier(free_mb), max(1, threads))


def step_down(tier):
    i = TIERS.index(tier)
    return TIERS[i + 1] if i + 1 < len(TIERS) else None


def subsample(frames, limit):
    """Evenly spaced subset in the original (time) order; every kept frame keeps its timestamp."""
    if limit <= 0 or len(frames) <= limit:
        return list(frames)
    step = (len(frames) - 1) / (limit - 1) if limit > 1 else 0
    idx = sorted({round(i * step) for i in range(limit)})
    return [frames[i] for i in idx]
