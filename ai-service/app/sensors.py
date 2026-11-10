"""
What sensor metadata does this video actually contain? Reads container tags and stream names with ffprobe. Nothing is guessed or invented.

Honest scope: this REPORTS what exists (GPS location tag, motion-data tracks such as GoPro 'gpmd' or Apple 'mebx'). It does not decode IMU samples or
fuse them: the pose estimate stays purely visual, which is also what an ordinary phone MP4 allows.
"""
import json
import re
import subprocess

_LOC = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def inspect(path):
    out = {"gps": None, "motion_streams": [], "compass_heading": None, "ffprobe": False, "fusion_used": False,
           "note": "Camera orientation is estimated visually (structure from motion). No sensor data is invented."}
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                           capture_output=True, text=True, timeout=30)
        info = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return out
    out["ffprobe"] = bool(info)
    tags = {k.lower(): str(v) for k, v in (info.get("format", {}).get("tags") or {}).items()}
    for k in ("location", "com.apple.quicktime.location.iso6709"):
        m = _LOC.match(tags.get(k, ""))
        if m:
            out["gps"] = {"latitude": float(m.group(1)), "longitude": float(m.group(2)), "source": f"container tag {k}"}
            break
    for s in info.get("streams", []):
        tag = (s.get("codec_tag_string") or "") + " " + str((s.get("tags") or {}).get("handler_name", ""))
        if s.get("codec_type") in ("data", "subtitle") and re.search(r"gpmd|mebx|camm|gyro|accel|imu|motion", tag, re.I):
            out["motion_streams"].append(tag.strip())
    return out
