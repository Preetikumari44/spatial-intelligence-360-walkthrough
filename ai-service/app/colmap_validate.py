"""Checks on the COLMAP SQLite database between stages, so an empty or broken stage fails with advice instead of a vague mapper error."""
import sqlite3
from pathlib import Path

from .errors import PipelineError


def inspect_database(db) -> dict:
    """Counts only; opened read-only. Missing tables are reported as None rather than guessed."""
    db = Path(db)
    out = {"exists": db.is_file(), "images": None, "images_with_keypoints": None, "total_keypoints": None,
           "images_with_descriptors": None, "verified_pairs": None, "raw_match_pairs": None}
    if not out["exists"]:
        return out
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}

        def one(sql):
            try:
                v = con.execute(sql).fetchone()[0]
                return int(v or 0)
            except sqlite3.Error:
                return None
        if "images" in tables:
            out["images"] = one("select count(*) from images")
        if "keypoints" in tables:
            out["images_with_keypoints"] = one("select count(*) from keypoints where rows > 0")
            out["total_keypoints"] = one("select sum(rows) from keypoints")
        if "descriptors" in tables:
            out["images_with_descriptors"] = one("select count(*) from descriptors where rows > 0")
        if "two_view_geometries" in tables:
            out["verified_pairs"] = one("select count(*) from two_view_geometries where rows > 0")
        if "matches" in tables:
            out["raw_match_pairs"] = one("select count(*) from matches where rows > 0")
    finally:
        con.close()
    return out


def validate_features(db, n_images, min_fraction=0.8, min_keypoints_per_image=50) -> dict:
    info = inspect_database(db)
    if not info["exists"]:
        raise PipelineError("COLMAP feature extraction finished but created no database file. Check the COLMAP log in the job folder.", 500)
    got = info["images_with_keypoints"]
    if got is None:
        raise PipelineError("The COLMAP database has no readable 'keypoints' table after feature extraction (unexpected schema).", 500)
    if info["images"] is not None and info["images"] < n_images:
        raise PipelineError(f"COLMAP registered only {info['images']} of {n_images} images in its database; some images could not be read.", 422)
    if got < max(2, int(n_images * min_fraction)):
        raise PipelineError(f"Feature extraction found keypoints in only {got} of {n_images} frames. The footage is probably too dark, blurry "
                            "or low-texture (blank walls). Film slower with better light and textured surroundings.", 422)
    avg = (info["total_keypoints"] or 0) / max(1, got)
    info["average_keypoints_per_image"] = round(avg, 1)
    if avg < min_keypoints_per_image:
        raise PipelineError(f"Only {avg:.0f} keypoints per frame on average (need {min_keypoints_per_image}+). Use sharper, better lit footage.", 422)
    return info


def validate_matches(db, n_images, min_pairs=None) -> dict:
    info = inspect_database(db)
    pairs = info["verified_pairs"]
    if pairs is None:
        raise PipelineError("The COLMAP database has no readable 'two_view_geometries' table after matching (unexpected schema).", 500)
    need = min_pairs if min_pairs is not None else max(1, n_images // 4)
    if pairs < need:
        raise PipelineError(f"Feature matching verified only {pairs} overlapping frame pairs (need at least {need}). Consecutive frames do not "
                            "share enough visible detail: move more slowly, avoid fast turns and blank walls, or raise FRAME_TARGET_FPS.", 422)
    return info
