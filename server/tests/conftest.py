import pytest

from outfit_core.assets import AssetStore
from outfit_core.cache import ResultCache
from outfit_core.capabilities import (GarmentAnalyzer, GarmentSegmenter, Provider, ProviderError, TryOnEngine,
                                      TryOnSpec, TurntableGenerator, Upscaler)
from outfit_core.registry import load_builtin_providers, register, registered_types
from outfit_core.types import Asset, Category, Garment, GarmentAnalysis, Shot

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"

load_builtin_providers()


def fake_image(store: AssetStore, tag: str) -> Asset:
    return store.put_bytes(PNG + tag.encode(), "image/png")


if "fake_tryon" not in registered_types():
    @register("fake_tryon")
    class FakeTryOn(Provider, TryOnEngine):
        """记录每次调用；config.fail=True 时抛错；config.max 控制一次几件。"""
        def __init__(self, name, config, store):
            super().__init__(name, config, store)
            self.spec = TryOnSpec(max_garments_per_call=config.get("max", 1),
                                  supports_layering=config.get("layering", True))
            self.calls = []

        def available(self):
            return (False, "关闭") if self.config.get("offline") else (True, "ok")

        def tryon(self, person, garments, options):
            if self.config.get("fail"):
                raise ProviderError("故意失败")
            self.calls.append([g.category.value for g in garments])
            return fake_image(self.store, f"{self.name}-{len(self.calls)}-{person.key}")

    @register("fake_analyzer")
    class FakeAnalyzer(Provider, GarmentAnalyzer):
        def analyze(self, image):
            if self.config.get("fail"):
                raise ProviderError("识别失败")
            return GarmentAnalysis(category=self.config.get("category", "top"),
                                   shot=self.config.get("shot", "flat_lay"), tryon_ready=True)

    @register("fake_segmenter")
    class FakeSegmenter(Provider, GarmentSegmenter):
        def segment(self, image, category):
            return fake_image(self.store, "cutout-" + image.key)

    @register("fake_upscaler")
    class FakeUpscaler(Provider, Upscaler):
        def upscale(self, image, scale=2):
            return fake_image(self.store, "hd-" + image.key)

    @register("fake_turntable")
    class FakeTurntable(Provider, TurntableGenerator):
        def generate(self, image, options):
            return self.store.put_bytes(b"\x00\x00\x00\x18ftypmp42" + image.key.encode(), "video/mp4"), []


@pytest.fixture
def store(tmp_path):
    return AssetStore(tmp_path / "assets")


@pytest.fixture
def cache(tmp_path):
    c = ResultCache(tmp_path / "cache.sqlite3")
    yield c
    c.close()


@pytest.fixture
def garment(store):
    def make(category: str, tag: str | None = None) -> Garment:
        return Garment(image=fake_image(store, tag or category), category=Category(category))
    return make
