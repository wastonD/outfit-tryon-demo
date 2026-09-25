"""业务流程：链接解析 → 服装分析 → 抠图 → 叠穿试衣 → 超分 → 360°。只依赖能力接口，不依赖具体模型。"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from .assets import AssetStore
from .cache import ResultCache, make_key
from .capabilities import Provider
from .layering import plan_steps, slots_of
from .registry import AllProvidersFailed, Registry
from .types import (Asset, BodySpec, CallMetrics, Category, Garment, Product, Shot, TryOnOptions,
                    TryOnResult, TryOnStepResult, TurntableOptions, TurntableResult)

log = logging.getLogger("outfit.pipeline")


class OutfitPipeline:
    def __init__(self, registry: Registry, store: AssetStore, cache: ResultCache | None = None):
        self.registry = registry
        self.store = store
        self.cache = cache

    # ---------- 工具 ----------
    @staticmethod
    def _timed(capability: str, provider: Provider, fn, metrics: list[CallMetrics]):
        start = time.time()
        result = fn()
        metrics.append(CallMetrics(capability=capability, provider=provider.name,
                                   seconds=round(time.time() - start, 2), cost=provider.info.cost_per_call))
        return result

    def _cached(self, kind: str, key: str, model):
        if not self.cache:
            return None
        data = self.cache.get(key)
        if not data:
            return None
        result = model.model_validate(data)
        assets = [getattr(result, "image", None), getattr(result, "video", None)]
        if any(a and a.path and not Path(a.path).exists() for a in assets):
            return None
        return result.model_copy(update={"cached": True})

    # ---------- 链接解析 ----------
    def resolve_link(self, text: str, route: str = "resolver") -> Product:
        metrics: list[CallMetrics] = []
        product, _ = self.registry.run(
            route, lambda p: self._timed("resolver", p, lambda: p.resolve(text), metrics),
            metrics, accept=lambda p: p.can_handle(text))
        return product

    # ---------- 服装准备 ----------
    def prepare_garment(self, image: Asset, category: Category | None = None, product: Product | None = None,
                        analyze_route: str = "analyzer", segment_route: str = "segmenter",
                        force_segment: bool = False) -> tuple[Garment, list[CallMetrics]]:
        """识别并在需要时抠图。默认只在模特上身图时抠图；force_segment=True 时总是按最终类型抠图。"""
        metrics: list[CallMetrics] = []
        analysis = None
        if analyze_route in self.registry.routes:
            try:
                analysis, _ = self.registry.run(
                    analyze_route, lambda p: self._timed("analyzer", p, lambda: p.analyze(image), metrics), metrics)
            except AllProvidersFailed as e:
                if category is None:
                    raise
                log.warning("服装分析失败，使用指定类型 %s：%s", category, e)
        final_category = category or (analysis.category if analysis else None)
        if final_category is None:
            raise ValueError("无法确定服装类型：没有配置 analyzer，也没有指定 category")
        garment = Garment(image=image, category=final_category, analysis=analysis, product=product)

        worn = analysis is not None and analysis.shot == Shot.worn_by_model
        if (force_segment or worn) and segment_route in self.registry.routes:
            try:
                cutout, _ = self.registry.run(
                    segment_route,
                    lambda p: self._timed("segmenter", p, lambda: p.segment(image, final_category), metrics), metrics)
                garment.cutout = cutout
            except AllProvidersFailed as e:
                log.warning("抠图失败，使用原图：%s", e)
        return garment, metrics

    # ---------- 试衣 ----------
    def tryon(self, person: Asset, garments: list[Garment], options: TryOnOptions | None = None,
              route: str = "tryon", upscale_route: str = "upscaler",
              on_progress: Callable[[int, int, str], None] | None = None) -> TryOnResult:
        """on_progress(已完成步数, 总步数, 说明)：每个试衣步骤开始和结束时调用，供接口层显示进度。"""
        options = options or TryOnOptions()
        failures: list[CallMetrics] = []
        wanted = slots_of(garments)
        report = on_progress or (lambda done, total, note: None)

        def run_engine(engine: Provider) -> TryOnResult:
            key = make_key("tryon", engine.name, engine.type_name, engine.config.get("model"), person.key,
                           [(g.category.value, g.tryon_image.key) for g in garments], options.model_dump())
            if cached := self._cached("tryon", key, TryOnResult):
                return cached
            steps, skipped = plan_steps(garments, engine.spec, options)
            if not steps:
                raise ValueError("没有该引擎能试穿的服装")
            result = TryOnResult(provider=engine.name, image=person, skipped=skipped)
            current = person
            total = len(steps) + (1 if options.upscale and upscale_route in self.registry.routes else 0)
            for i, step in enumerate(steps):
                report(i, total, f"{engine.name}: " + "+".join(g.category.value for g in step))
                step_metrics: list[CallMetrics] = []
                output = self._timed("tryon", engine, lambda: engine.tryon(current, step, options), step_metrics)
                current = self.store.ensure_local(output)
                result.steps.append(TryOnStepResult(garments=[g.id for g in step], image=current,
                                                    metrics=step_metrics[0]))
                result.metrics += step_metrics
                report(i + 1, total, f"{engine.name}: 第 {i + 1} 步完成")
            result.image = current
            if options.upscale and upscale_route in self.registry.routes:
                report(len(steps), total, "upscale")
                try:
                    up, _ = self.registry.run(
                        upscale_route,
                        lambda p: self._timed("upscaler", p, lambda: p.upscale(current), result.metrics),
                        result.metrics)
                    result.image = self.store.ensure_local(up)
                except AllProvidersFailed as e:
                    log.warning("超分失败，保留原图：%s", e)
                report(total, total, "done")
            if self.cache:
                self.cache.set(key, "tryon", result.model_dump())
            return result

        result, _ = self.registry.run(
            route, run_engine, failures,
            accept=lambda p: bool(wanted & p.spec.slots))
        result.metrics = failures + result.metrics
        return result

    # ---------- 360° ----------
    def turntable(self, image: Asset, options: TurntableOptions | None = None,
                  route: str = "turntable") -> TurntableResult:
        options = options or TurntableOptions()
        failures: list[CallMetrics] = []

        def run(gen: Provider) -> TurntableResult:
            key = make_key("turntable", gen.name, gen.config.get("model"), image.key, options.model_dump())
            if cached := self._cached("turntable", key, TurntableResult):
                return cached
            metrics: list[CallMetrics] = []
            video, frames = self._timed("turntable", gen, lambda: gen.generate(image, options), metrics)
            result = TurntableResult(provider=gen.name, metrics=metrics,
                                     video=self.store.ensure_local(video) if video else None,
                                     frames=[self.store.ensure_local(f) for f in frames])
            if self.cache:
                self.cache.set(key, "turntable", result.model_dump())
            return result

        result, _ = self.registry.run(route, run, failures)
        result.metrics = failures + result.metrics
        return result

    # ---------- 预设模特 ----------
    def generate_model(self, body: BodySpec, prompt: str, seed: int | None = None,
                       route: str = "model_generator") -> tuple[Asset, list[CallMetrics]]:
        metrics: list[CallMetrics] = []
        asset, _ = self.registry.run(
            route, lambda p: self._timed("model_generator", p, lambda: p.generate_model(body, prompt, seed), metrics),
            metrics)
        return self.store.ensure_local(asset), metrics
