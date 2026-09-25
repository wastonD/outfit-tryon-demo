import pytest

from outfit_core.pipeline import OutfitPipeline
from outfit_core.registry import AllProvidersFailed, Registry
from outfit_core.types import Category, Shot, TryOnOptions, TurntableOptions

from .conftest import fake_image


def make(store, cache, providers, routes):
    reg = Registry.from_config({"providers": providers, "routes": routes}, store)
    return OutfitPipeline(reg, store, cache), reg


def test_single_garment_engine_runs_multiple_steps(store, cache, garment):
    pipe, reg = make(store, cache, {"e": {"type": "fake_tryon", "max": 1}}, {"tryon": ["e"]})
    person = fake_image(store, "model")
    result = pipe.tryon(person, [garment("top"), garment("bottom"), garment("outer")])
    assert reg.providers["e"].calls == [["bottom"], ["top"], ["outer"]]
    assert len(result.steps) == 3 and result.image == result.steps[-1].image
    assert result.provider == "e" and not result.cached


def test_progress_callback_reports_each_step(store, cache, garment):
    pipe, _ = make(store, cache, {"e": {"type": "fake_tryon", "max": 1}, "up": {"type": "fake_upscaler"}},
                   {"tryon": ["e"], "upscaler": ["up"]})
    events = []
    pipe.tryon(fake_image(store, "m"), [garment("top"), garment("bottom")], TryOnOptions(upscale=True),
               on_progress=lambda done, total, note: events.append((done, total)))
    assert events[0] == (0, 3) and events[-1] == (3, 3)
    assert [d for d, _ in events] == sorted(d for d, _ in events)


def test_cache_hit_skips_engine(store, cache, garment):
    pipe, reg = make(store, cache, {"e": {"type": "fake_tryon", "max": 2}}, {"tryon": ["e"]})
    person, items = fake_image(store, "model"), [garment("top"), garment("bottom")]
    first = pipe.tryon(person, items)
    second = pipe.tryon(person, items)
    assert len(reg.providers["e"].calls) == 1
    assert second.cached and second.image.sha256 == first.image.sha256


def test_fallback_to_next_engine_keeps_failure_metrics(store, cache, garment):
    pipe, _ = make(store, cache, {"bad": {"type": "fake_tryon", "fail": True}, "ok": {"type": "fake_tryon"}},
                   {"tryon": ["bad", "ok"]})
    result = pipe.tryon(fake_image(store, "m"), [garment("dress")])
    assert result.provider == "ok"
    assert [(m.provider, m.ok) for m in result.metrics] == [("bad", False), ("ok", True)]


def test_upscale_is_applied_and_cached(store, cache, garment):
    pipe, _ = make(store, cache, {"e": {"type": "fake_tryon"}, "up": {"type": "fake_upscaler"}},
                   {"tryon": ["e"], "upscaler": ["up"]})
    person, items = fake_image(store, "m"), [garment("top")]
    first = pipe.tryon(person, items, TryOnOptions(upscale=True))
    assert first.image != first.steps[-1].image
    assert pipe.tryon(person, items, TryOnOptions(upscale=True)).image.sha256 == first.image.sha256


def test_prepare_garment_segments_model_photos(store, cache):
    pipe, _ = make(store, cache,
                   {"a": {"type": "fake_analyzer", "category": "skirt", "shot": "worn_by_model"},
                    "s": {"type": "fake_segmenter"}},
                   {"analyzer": ["a"], "segmenter": ["s"]})
    g, metrics = pipe.prepare_garment(fake_image(store, "photo"))
    assert g.category == Category.skirt and g.analysis.shot == Shot.worn_by_model
    assert g.cutout is not None and g.tryon_image == g.cutout
    assert [m.capability for m in metrics] == ["analyzer", "segmenter"]


@pytest.mark.parametrize("shot", ["flat_lay", "worn_by_model"])
def test_force_segment_calls_segmenter_exactly_once(store, cache, shot):
    pipe, reg = make(store, cache,
                     {"a": {"type": "fake_analyzer", "category": "top", "shot": shot}, "s": {"type": "fake_segmenter"}},
                     {"analyzer": ["a"], "segmenter": ["s"]})
    calls = []
    original = reg.providers["s"].segment
    reg.providers["s"].segment = lambda image, category: calls.append(category) or original(image, category)
    g, _ = pipe.prepare_garment(fake_image(store, "photo"), Category.skirt, force_segment=True)
    assert calls == [Category.skirt] and g.cutout is not None


def test_prepare_garment_uses_hint_when_analyzer_fails(store, cache):
    pipe, _ = make(store, cache, {"a": {"type": "fake_analyzer", "fail": True}}, {"analyzer": ["a"]})
    g, _ = pipe.prepare_garment(fake_image(store, "x"), category=Category.outer)
    assert g.category == Category.outer and g.analysis is None
    with pytest.raises(AllProvidersFailed):
        pipe.prepare_garment(fake_image(store, "y"))


def test_turntable(store, cache):
    pipe, _ = make(store, cache, {"t": {"type": "fake_turntable"}}, {"turntable": ["t"]})
    result = pipe.turntable(fake_image(store, "front"), TurntableOptions(duration=4))
    assert result.video and result.video.mime == "video/mp4" and result.provider == "t"
