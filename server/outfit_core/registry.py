"""适配器注册、配置加载和路由（按顺序尝试，失败自动切换到下一个）。"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .capabilities import CAPABILITY_BASES, Provider, ProviderError
from .types import CallMetrics

log = logging.getLogger("outfit.registry")

_TYPES: dict[str, type[Provider]] = {}


def register(type_name: str):
    def deco(cls):
        if type_name in _TYPES and _TYPES[type_name] is not cls:
            raise ValueError(f"适配器类型重复注册：{type_name}")
        cls.type_name = type_name
        cls.capabilities = tuple(c for c, base in CAPABILITY_BASES.items() if issubclass(cls, base))
        _TYPES[type_name] = cls
        return cls
    return deco


def registered_types() -> dict[str, type[Provider]]:
    return dict(_TYPES)


def load_builtin_providers():
    """导入 providers/ 和 resolvers/ 下的所有模块，触发 @register。"""
    for pkg_name in ("providers", "resolvers"):
        pkg = importlib.import_module(pkg_name)
        for mod in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module(f"{pkg_name}.{mod.name}")


class AllProvidersFailed(RuntimeError):
    def __init__(self, capability: str, errors: list[tuple[str, str]]):
        detail = "\n".join(f"  - {n}: {e}" for n, e in errors) or "  （路由为空）"
        super().__init__(f"能力 {capability} 的所有实现都失败或不可用：\n{detail}")
        self.errors = errors


@dataclass
class Registry:
    providers: dict[str, Provider] = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict, store) -> "Registry":
        reg = cls()
        for name, conf in (config.get("providers") or {}).items():
            conf = dict(conf or {})
            if conf.pop("enabled", True) is False:
                continue
            type_name = conf.get("type")
            if type_name not in _TYPES:
                raise ValueError(f"providers.{name}: 未知类型 {type_name!r}，可用类型：{sorted(_TYPES)}")
            reg.providers[name] = _TYPES[type_name](name, conf, store)

        for route, names in (config.get("routes") or {}).items():
            capability = route.split(".")[0]  # 例如 tryon.hd 属于 tryon 能力
            if capability not in CAPABILITY_BASES:
                raise ValueError(f"routes.{route}: 未知能力 {capability}")
            valid = []
            for n in names or []:
                p = reg.providers.get(n)
                if p is None:
                    reg.warnings.append(f"routes.{route}: 实例 {n} 不存在或已禁用，已忽略")
                    continue
                if capability not in p.capabilities:
                    raise ValueError(f"routes.{route}: {n}（{p.type_name}）不具备 {capability} 能力")
                if not p.info.commercial_ok:
                    reg.warnings.append(f"routes.{route}: {n} 标记为不可商用（{p.info.license}），仅限内部测试")
                valid.append(n)
            reg.routes[route] = valid
        for w in reg.warnings:
            log.warning(w)
        return reg

    @classmethod
    def from_file(cls, path: str | Path, store) -> "Registry":
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_config(yaml.safe_load(os.path.expandvars(text)) or {}, store)

    def route(self, name: str) -> list[Provider]:
        if name not in self.routes:
            raise KeyError(f"配置里没有路由 {name}")
        return [self.providers[n] for n in self.routes[name]]

    def with_route(self, name: str, provider_names: list[str]) -> "Registry":
        """复制一份只替换某条路由的 Registry（bench 逐个对比实现时使用）。"""
        clone = Registry(dict(self.providers), dict(self.routes), list(self.warnings))
        clone.routes[name] = list(provider_names)
        return clone

    def run(self, route: str, fn: Callable[[Provider], Any], metrics: list[CallMetrics] | None = None,
            accept: Callable[[Provider], bool] | None = None):
        """依次用路由中的实现执行 fn(provider)，返回 (结果, provider)。

        accept 可以进一步过滤实现（例如只要支持某个服装位置的试衣引擎）。
        """
        capability = route.split(".")[0]
        errors: list[tuple[str, str]] = []
        for p in self.route(route):
            ok, why = p.available()
            if not ok:
                errors.append((p.name, f"不可用：{why}"))
                continue
            if accept and not accept(p):
                errors.append((p.name, "不满足本次请求的能力要求"))
                continue
            start = time.time()
            try:
                result = fn(p)
            except Exception as e:  # 任何实现出错都不应中断整个流程，交给下一个实现
                errors.append((p.name, f"{type(e).__name__}: {e}"))
                if metrics is not None:
                    metrics.append(CallMetrics(capability=capability, provider=p.name, ok=False,
                                               seconds=round(time.time() - start, 2), note=str(e)[:300]))
                log.warning("%s 调用 %s 失败，尝试下一个：%s", route, p.name, e)
                continue
            return result, p
        raise AllProvidersFailed(route, errors)

    def status(self) -> dict:
        return {
            "providers": {n: {"type": p.type_name, "capabilities": list(p.capabilities),
                              "available": p.available()[0], "reason": p.available()[1],
                              **p.info.model_dump()} for n, p in self.providers.items()},
            "routes": self.routes,
            "warnings": self.warnings,
        }
