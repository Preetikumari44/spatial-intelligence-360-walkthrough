"""
Optional: calibrate your own camera from photos of a printed chessboard, then point CAMERA_INTRINSICS_FILE at the result.

    python scripts\\calibrate_camera.py --images "C:\\calib\\*.jpg" --pattern 9x6 --square-mm 25 --out camera.json

Use at least 10 sharp photos of the board from different angles, taken at the same resolution and zoom as the video you will
film. Without this file the AI service estimates the focal length from the footage itself.
"""
import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-service"))
from app.sfm import calibrate_chessboard  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="glob of chessboard photos")
    ap.add_argument("--pattern", default="9x6", help="inner corners, columns x rows")
    ap.add_argument("--square-mm", type=float, default=25.0)
    ap.add_argument("--out", default="camera.json")
    a = ap.parse_args()
    cols, rows = (int(x) for x in a.pattern.lower().split("x"))
    result = calibrate_chessboard(sorted(glob.glob(a.images)), (cols, rows), a.square_mm)
    Path(a.out).write_text(json.dumps(result, indent=2))
    print(f"Wrote {a.out}: fx={result['fx']:.1f} fy={result['fy']:.1f} RMS reprojection {result['rms_reprojection_px']:.2f}px")


if __name__ == "__main__":
    main()
