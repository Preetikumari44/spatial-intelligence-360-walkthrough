from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_capabilities_are_booleans():
    caps = client.get("/health").json()["capabilities"]
    assert all(isinstance(v, bool) for v in caps.values())
    assert {"opencv_sfm", "open3d", "open3d_sycl_xpu", "gaussian_splatting"} <= set(caps)
    assert caps["open3d"] is True
    assert caps["open3d_sycl_xpu"] is False
    assert caps["torch_xpu"] is False


def test_capabilities_report():
    r = client.get("/capabilities").json()
    assert r["cuda_required"] is False and "devices" in r


def test_cancel_and_status_round_trip():
    assert client.get("/jobs/abc/status").json()["known"] is False
    client.post("/jobs/abc/cancel")
    st = client.get("/jobs/abc/status").json()
    assert st["known"] and st["cancelled"]
