import math

import numpy as np

from app import geometry


def test_quaternion_identity():
    assert np.allclose(geometry.quat_to_rot(1, 0, 0, 0), np.eye(3))


def test_normalisation_makes_y_up_and_is_a_rotation():
    # world where "up" is +Z: cameras look along +X with image-y pointing down (-Z)
    n = 12
    centers = np.array([[i * 0.5, 0.2 * math.sin(i), 1.5] for i in range(n)])
    axes = np.array([[[0, -1, 0], [0, 0, -1], [1, 0, 0]]] * n, dtype=float)
    rng = np.random.default_rng(1)
    points = np.column_stack([rng.uniform(0, 6, 400), rng.uniform(-2, 2, 400), rng.uniform(0, 2.5, 400)])
    Rn, origin = geometry.world_normalisation(centers, axes, points)
    assert np.allclose(Rn[1], [0, 0, 1], atol=1e-6)
    assert np.isclose(np.linalg.det(Rn), 1.0)
    # the long axis of the scene (world X) should land on the new X axis
    assert abs(Rn[0] @ np.array([1, 0, 0])) > 0.95


def test_projection_and_hotspot_side():
    from app.tour import hotspot
    cam = {"w": 1000, "h": 800, "fx": 800, "fy": 800, "cx": 500, "cy": 400}
    # normalised frame: facing +X, so right-hand side is +Z
    axes = np.array([[0, 0, 1], [0, -1, 0], [1, 0, 0]], dtype=float)
    a = {"center": np.zeros(3), "heading": 0.0, "axes": axes, "camera": cam, "landmarks": {0}}
    b_right = {"center": np.array([2.0, 0.0, 0.5]), "heading": 0.0, "axes": axes, "camera": cam, "landmarks": {0}}
    h = hotspot(a, b_right, np.array([[5.0, 0.0, 1.25]]))
    assert h["visible"] and h["x"] > 0.5 and h["bearing"] > 0
    behind = {"center": np.array([-2.0, 0.0, 0.0]), "heading": 0.0, "axes": axes, "camera": cam, "landmarks": {0}}
    assert hotspot(a, behind, np.array([[5.0, 0.0, 1.25]]))["visible"] is False


def test_panorama_hotspot_yaw_is_clockwise_positive():
    from app.tour import hotspot
    a = {"center": np.zeros(3), "heading": 0.0, "axes": None, "camera": None}
    b = {"center": np.array([1.0, 0.0, 1.0]), "heading": 0.0, "axes": None, "camera": None}
    assert math.isclose(hotspot(a, b)["yaw"], math.pi / 4, abs_tol=1e-6)


def test_equirect_face_yaw_matches_marzipano_convention():
    h, w = 360, 720
    img = np.zeros((h, w, 3), np.uint8)
    u = int((0.25 + 0.5) * w)  # longitude +90 degrees: to the right of the panorama centre
    img[:, u - 4:u + 4] = 255
    right = geometry.equirect_to_persp(img, yaw_deg=90, size=200)
    front = geometry.equirect_to_persp(img, yaw_deg=0, size=200)
    assert right[100, 100].mean() > 200
    assert front[100, 100].mean() < 20


def test_camera_parser_handles_simple_radial():
    cams = geometry.parse_cameras("# c\n1 SIMPLE_RADIAL 1600 900 1200.0 800.0 450.0 -0.01\n")
    assert cams[1]["fx"] == cams[1]["fy"] == 1200.0 and cams[1]["cx"] == 800.0
