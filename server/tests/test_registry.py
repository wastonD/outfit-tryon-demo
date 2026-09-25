from pathlib import Path

import pytest

from outfit_core.registry import AllProvidersFailed, Registry
from outfit_core.types import CallMetrics

from .conftest import fake_image

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_example_config_loads(store):
    reg = Registry.from_file(CONFIG_DIR / "providers.example.yaml", store)
    assert reg.routes["tryon"] == ["local-gpu", "aliyun-tryon"]
    assert "kling-tryon" not in reg.providers           # enabled: false
    assert set(reg.providers["local-gpu"].capabilities) >= {"tryon", "turntable"}
    assert reg.status()["routes"]["tryon.hd"][0] == "aliyun-tryon-plus"


def test_unknown_type_and_wrong_capability(store):
    with pytest.raises(ValueError, match="未知类型"):
        Registry.from_config({"providers": {"x": {"type": "nope"}}}, store)
    with pytest.raises(ValueError, match="不具备 tryon"):
        Registry.from_config({"providers": {"a": {"type": "fake_analyzer"}}, "routes": {"tryon": ["a"]}}, store)


def test_warnings_for_missing_and_non_commercial(store):
    reg = Registry.from_config({
        "providers": {"nc": {"type": "fake_tryon", "info": {"commercial_ok": False, "license": "CC BY-NC"}}},
        "routes": {"tryon": ["nc", "ghost"]}}, store)
    assert reg.routes["tryon"] == ["nc"]
    assert any("ghost" in w for w in reg.warnings) and any("不可商用" in w for w in reg.warnings)


def test_fallback_skips_offline_and_failed(store):
    reg = Registry.from_config({
        "providers": {"off": {"type": "fake_tryon", "offline": True},
                      "bad": {"type": "fake_tryon", "fail": True},
                      "good": {"type": "fake_tryon"}},
        "routes": {"tryon": ["off", "bad", "good"]}}, store)
    metrics: list[CallMetrics] = []
    person = fake_image(store, "m")
    result, provider = reg.run("tryon", lambda p: p.tryon(person, [], None), metrics)
    assert provider.name == "good"
    assert [m.provider for m in metrics if not m.ok] == ["bad"]


def test_all_failed_lists_reasons(store):
    reg = Registry.from_config({"providers": {"bad": {"type": "fake_tryon", "fail": True}},
                                "routes": {"tryon": ["bad"]}}, store)
    with pytest.raises(AllProvidersFailed, match="故意失败"):
        reg.run("tryon", lambda p: p.tryon(None, [], None))


def test_with_route_does_not_mutate_original(store):
    reg = Registry.from_config({"providers": {"a": {"type": "fake_tryon"}, "b": {"type": "fake_tryon"}},
                                "routes": {"tryon": ["a", "b"]}}, store)
    clone = reg.with_route("tryon", ["b"])
    assert clone.routes["tryon"] == ["b"] and reg.routes["tryon"] == ["a", "b"]
