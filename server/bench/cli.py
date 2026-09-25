"""模型对比工具：同一批测试用例，逐个实现单独运行，输出效果、耗时和费用报告。

用法（在 server 目录下）：
  python -m bench.cli --cases bench/cases.example.json --compare tryon=aliyun-tryon,aliyun-tryon-plus
  python -m bench.cli --cases my.json --compare tryon=local-gpu,aliyun-tryon --turntable aliyun-wan --no-analyze
  python -m bench.cli --links bench/links.example.txt           # 只测链接解析
  python -m bench.cli --status                                   # 查看各实现是否可用
"""
import argparse
import json
import logging
import time
from pathlib import Path

from outfit_core.bootstrap import SERVER_ROOT, build, setup_console
from outfit_core.pipeline import OutfitPipeline
from outfit_core.registry import AllProvidersFailed
from outfit_core.types import Asset, Category, TryOnOptions, TurntableOptions

from .report import write_report

log = logging.getLogger("outfit.bench")


def parse_compare(values: list[str]) -> dict[str, list[str]]:
    out = {}
    for v in values or []:
        route, _, names = v.partition("=")
        out[route] = [n.strip() for n in names.split(",") if n.strip()]
    return out


def run_links(rt, path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        start = time.time()
        try:
            p = rt.pipeline.resolve_link(line)
            rows.append({"input": line, "ok": True, "product": p.model_dump(), "seconds": round(time.time() - start, 2)})
            log.info("✅ %s %s（%d 张图）", p.platform, p.title, len(p.images))
        except AllProvidersFailed as e:
            rows.append({"input": line, "ok": False, "error": str(e), "seconds": round(time.time() - start, 2)})
            log.info("❌ %s", str(e).splitlines()[-1])
    return rows


def run_case(rt, case: dict, compare: dict[str, list[str]], turntables: list[str], analyze: bool) -> dict:
    store = rt.store
    out = {"name": case["name"], "garments": [], "tryon": [], "turntable": [], "errors": []}
    person = store.ensure_local(store.from_source(case["model"]))
    out["model"] = person.model_dump()

    garments = []
    for g in case["garments"]:
        hint = Category(g["category"]) if g.get("category") else None
        try:
            image = store.ensure_local(store.from_source(g["src"]))
            garment, metrics = rt.pipeline.prepare_garment(
                image, hint, analyze_route="analyzer" if analyze else "__none__")
            garments.append(garment)
            out["garments"].append({**garment.model_dump(), "metrics": [m.model_dump() for m in metrics]})
            log.info("  服装 %s → %s", g["src"][-40:], garment.category.value)
        except Exception as e:
            out["errors"].append(f"服装 {g['src']}: {e}")
            log.warning("  ⚠️ 跳过服装 %s：%s", g["src"], e)
    if not garments:
        return out

    options = TryOnOptions(**case.get("options", {}))
    for route, names in compare.items():
        for name in names:
            pipe = OutfitPipeline(rt.registry.with_route(route, [name]), store, rt.cache)
            log.info("  [%s] %s 试衣中…", route, name)
            try:
                r = pipe.tryon(person, garments, options, route=route)
                out["tryon"].append({"route": route, "provider": name, "ok": True, **r.model_dump(),
                                     "total_seconds": r.total_seconds, "total_cost": r.total_cost})
                log.info("  [%s] %s 完成：%ss，%s 元%s", route, name, r.total_seconds, r.total_cost,
                         "（缓存）" if r.cached else "")
            except Exception as e:
                out["tryon"].append({"route": route, "provider": name, "ok": False, "error": str(e)})
                log.warning("  [%s] %s 失败：%s", route, name, e)

    best = next((t for t in out["tryon"] if t["ok"]), None)
    for name in turntables if best else []:
        pipe = OutfitPipeline(rt.registry.with_route("turntable", [name]), store, rt.cache)
        log.info("  [turntable] %s 生成中（首帧来自 %s）…", name, best["provider"])
        try:
            r = pipe.turntable(Asset.model_validate(best["image"]), TurntableOptions(**case.get("turntable", {})))
            out["turntable"].append({"provider": name, "source": best["provider"], "ok": True, **r.model_dump()})
        except Exception as e:
            out["turntable"].append({"provider": name, "ok": False, "error": str(e)})
            log.warning("  [turntable] %s 失败：%s", name, e)
    return out


def main():
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--cases")
    ap.add_argument("--only")
    ap.add_argument("--compare", action="append", help="route=实例1,实例2，可重复")
    ap.add_argument("--turntable", default="", help="逗号分隔的 turntable 实例")
    ap.add_argument("--links")
    ap.add_argument("--no-analyze", action="store_true", help="不调用识别模型，只用用例里的 category")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    rt = build(args.config)
    if args.status:
        print(json.dumps(rt.registry.status(), ensure_ascii=False, indent=2))
        return

    run_dir = SERVER_ROOT / "data" / "bench" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "links": [], "cases": []}
    if args.links:
        results["links"] = run_links(rt, Path(args.links))
    if args.cases:
        compare = parse_compare(args.compare) or {"tryon": rt.registry.routes.get("tryon", [])}
        turntables = [t.strip() for t in args.turntable.split(",") if t.strip()]
        cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
        for case in cases:
            if args.only and case["name"] != args.only:
                continue
            log.info("=== %s ===", case["name"])
            results["cases"].append(run_case(rt, case, compare, turntables, not args.no_analyze))

    (run_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report = write_report(results, run_dir)
    log.info("报告：%s", report)


if __name__ == "__main__":
    main()
