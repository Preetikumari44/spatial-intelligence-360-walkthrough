"""
Writes a synthetic test video.

  python make_test_video.py [out.mp4]                  a walk through a textured 3D room (default, kind=room)
  python make_test_video.py out.mp4 --kind pan         a flat pan across a texture (ingestion / blur / duplicate tests only)
  python make_test_video.py out.mp4 --kind static      the camera never moves (must be rejected by the pipeline)
  python make_test_video.py out.mp4 --kind blurry      every frame heavily blurred (must be rejected by the pipeline)

kind=room renders a real 3D scene with true parallax from known camera poses, so structure from motion CAN reconstruct it. It
includes a short stationary hold at the start (duplicates) and a short motion-blur burst, which frame extraction should drop.
It is a test fixture, not a property: a real walkthrough of a real home is the only valid acceptance test.
"""
import argparse
import os
import sys

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("out", nargs="?", default="synthetic_room.mp4")
ap.add_argument("--kind", choices=("room", "pan", "static", "blurry"), default="room")
ap.add_argument("--frames", type=int, default=150)
ap.add_argument("--fps", type=int, default=15)
ap.add_argument("--width", type=int, default=960)
a = ap.parse_args()

W = a.width
H = W * 3 // 4
F = 0.875 * W
vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (W, H))
if not vw.isOpened():
    sys.exit("cv2.VideoWriter could not open the output file (no mp4v encoder in this OpenCV build)")

if a.kind in ("room", "static", "blurry"):
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "..", "ai-service", "tests"))
    import synth  # the renderer the unit tests use: known poses, known depth
    path = synth.camera_path(a.frames)
    for i, (c, R) in enumerate(path):
        if a.kind == "static":
            c, R = path[0]
        img, _ = synth.render(c, R, W, H, F)
        if a.kind == "blurry" or (a.kind == "room" and 70 <= i < 76):
            img = cv2.GaussianBlur(img, (0, 0), 14)
        if a.kind == "room" and i < 10:
            c0, R0 = path[0]                      # stationary hold: near-duplicate frames
            img, _ = synth.render(c0, R0, W, H, F)
        vw.write(img)
else:
    rng = np.random.default_rng(7)
    scene = cv2.GaussianBlur(rng.integers(0, 255, (H * 2, W * 3, 3), dtype=np.uint8), (0, 0), 1)
    n = a.frames
    for i in range(n):
        x = int(i * (W * 2) / n)
        frame = scene[100:100 + H, x:x + W].copy()
        if 90 * n // 240 <= i < 110 * n // 240:
            frame = cv2.GaussianBlur(frame, (0, 0), 12)
        vw.write(frame)
vw.release()
print("wrote", a.out, f"({a.kind}, {W}x{H}, {a.frames} frames @ {a.fps} fps)")
