from app import hardware, config


def test_report_never_requires_cuda_and_names_a_device():
    r = hardware.report()
    assert r["cuda_required"] is False
    assert r["devices"]["open3d_device"] in ("CPU:0", "SYCL:0")
    assert r["devices"]["torch_device"] in ("cpu", "xpu")
    assert r["cpu"]["threads_used"] >= 1


def test_xpu_mode_zero_forces_cpu(monkeypatch):
    monkeypatch.setattr(config, "XPU_MODE", "0")
    d = hardware.select_devices()
    assert d["open3d_device"] == "CPU:0" and d["torch_device"] == "cpu"
    assert any("disabled" in n for n in d["notes"])


def test_cpu_mode_cannot_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("XPU_MODE", "auto")
    assert config.XPU_MODE == "0"


def test_open3d_cpu_capability_requires_a_real_cpu_operation():
    info = hardware.open3d_info()
    assert info["installed"]
    assert info["cpu_smoke_ok"] is True
    assert hardware.probe()["open3d"] is True
    assert hardware.probe()["open3d_sycl"] is False
    assert hardware.probe()["torch_xpu"] is False


def test_successful_pipeline_stage_updates_cached_capability():
    hardware.reset_cache()
    assert hardware.runtime_test("test_stage", lambda: False) is False
    hardware.record_runtime_success("test_stage")
    assert hardware.runtime_test("test_stage", lambda: False) is True


def test_thread_limit_respects_config(monkeypatch):
    monkeypatch.setattr(config, "CPU_THREADS", 3)
    assert hardware.cpu_threads() == 3
