"""服装识别（analyzer）准确率评测：新旧提示词对比。

用法（需要 llama-server 已经在 127.0.0.1:8080 跑起来，见 worker/scripts/start_llama_server.ps1）：
  cd server
  .venv\\Scripts\\python -m bench.analyzer_eval

评测集：server/data/bench/ 里的真实图片（用户提供的商品图/试衣结果图），人工标注了正确的 category 和 shot
（见下面 CASES；ambiguous=True 的是"一张图里有不止一件衣服"的合影/试衣结果图，这类图没有唯一正确答案，
只检查新提示词要求的"不要因为多件衣服返回 other + note 里提一下画面还有什么"这两条软性标准，
不做单一 category 的精确匹配）。
"""
from __future__ import annotations

import json
import sys
import time

# Windows 控制台默认编码常常是 gbk，print() 里带表情/特殊符号会直接抛 UnicodeEncodeError 中断整个评测；
# 这里不影响色彩/中文本身（gbk 能编码常见汉字），只是让极端情况下也不中断、把编不出的字符替换掉。
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass
from dataclasses import dataclass
from pathlib import Path

from outfit_core.assets import AssetStore
from outfit_core.types import Category

import providers.openai_compat_vlm as vlm_mod
from providers._prompts import ANALYZE_PROMPT as NEW_PROMPT

BENCH_DATA_DIR = Path(__file__).parent.parent / "data" / "bench"

# H 任务改进前的提示词（server/providers/_prompts.py 里 2026-09-18 之前的版本），仅用于对比评测。
OLD_PROMPT = """你是电商服装图片分析器。判断这张商品图，只输出 JSON，不要任何解释：
{"category": "top|outer|bottom|skirt|dress|shoes|bag|other",
 "layer": "inner|outer|none",
 "shot": "flat_lay|worn_by_model|mannequin|detail|poster|other",
 "tryon_ready": true,
 "color": "主色",
 "note": "一句话描述款式"}
说明：top 指 T 恤、衬衫、毛衣等上衣；outer 指外套、夹克、开衫、西装、大衣等穿在最外层的衣服；
bottom 指裤子和短裤；skirt 指半身裙；dress 指连衣裙和连体衣；
tryon_ready 表示这张图是否是单件服装、主体清晰、适合直接用于虚拟试穿。"""


@dataclass
class Case:
    file: str
    category: str | None      # None 表示 ambiguous（多件衣服合影/试衣结果），不做精确匹配
    shot: str
    note_should_mention: str | None = None   # ambiguous 用例：note 里应该提到的关键词（松散包含检查）
    desc: str = ""


CASES = [
    Case("clo-1.jpg", "outer", "worn_by_model", desc="男装夹克单品图"),
    Case("clo-2.jpg", "top", "worn_by_model", desc="男装T恤单品图"),
    Case("clo-1.avif", "outer", "worn_by_model", desc="同 clo-1，测试 avif 解码"),
    Case("clo-2.avif", "top", "worn_by_model", desc="同 clo-2，测试 avif 解码"),
    Case("clo-3.avif", None, "worn_by_model", "裙", desc="同 clo-3，测试 avif 解码"),
    Case("uniqlo_model.jpg", "top", "worn_by_model", desc="模特上身图：棕色T恤+卡其裤"),
    Case("case_dress_result.png", "dress", "worn_by_model", desc="米白色无袖连衣裙，单品清晰"),
    Case("case5_cutout.png", "top", "worn_by_model", desc="BiRefNet 抠图后的人物前景（同 uniqlo_model 人物）"),
    Case("case5_worn_by_model_result.png", "top", "worn_by_model", desc="棕色上衣+卡其短裤试衣结果"),
    Case("case_tuck_out.png", None, "worn_by_model", "上衣|T恤|衬衫", desc="蓝色牛仔裤为主，配蓝色上衣"),
    Case("case_3layer_result.png", "outer", "worn_by_model", desc="三层叠穿结果：卡其外套最显眼"),
    Case("e2e_result_hd.jpg", None, "worn_by_model", "裤|牛仔", desc="蓝色T恤+牛仔裤，高清版"),
    # 多件衣服合影的复现用例：黑色针织开衫 + 白色百褶裙 + 黑色马丁靴 整体穿搭合影
    Case("clo-3.jpg", None, "worn_by_model", "裙", desc="多件合影：开衫+半裙+靴子"),
    Case("case_top_skirt.png", None, "worn_by_model", "上衣|T恤", desc="蓝色上衣+黑色半身裙试衣结果"),
    Case("case_tuck_in.png", None, "worn_by_model", "上衣|T恤", desc="同 case_tuck_out，tuck=in"),
]


def _make_provider(prompt_text, resize_long_edge=768):
    vlm_mod.ANALYZE_PROMPT = prompt_text
    store = AssetStore(BENCH_DATA_DIR.parent / "_analyzer_eval_assets")
    cfg = {"base_url": "http://127.0.0.1:8080/v1", "model": "qwen3-vl-4b",
           "resize_long_edge": resize_long_edge, "timeout": 240}
    return vlm_mod.OpenAICompatVLM("qwen-local-eval", cfg, store), store


def _grade(case: Case, analysis):
    if case.category is None:
        ok_category = analysis.category != Category.other and analysis.tryon_ready
        note = analysis.note or ""
        ok_note = case.note_should_mention is None or any(
            kw in note for kw in case.note_should_mention.split("|"))
        return ok_category and ok_note, f"category={analysis.category.value} note命中关键词={ok_note}"
    ok = analysis.category.value == case.category and analysis.shot.value == case.shot
    return ok, f"category={analysis.category.value}(期望{case.category}) shot={analysis.shot.value}(期望{case.shot})"


def run(prompt_name: str, prompt_text: str):
    provider, store = _make_provider(prompt_text)
    rows = []
    for case in CASES:
        path = BENCH_DATA_DIR / case.file
        if not path.exists():
            print(f"  跳过（文件不存在）：{case.file}")
            continue
        image = store.put_file(path)
        t0 = time.time()
        try:
            analysis = provider.analyze(image)
            ok, detail = _grade(case, analysis)
            elapsed = time.time() - t0
            rows.append({"file": case.file, "ok": ok, "detail": detail, "elapsed": round(elapsed, 1),
                        "color": analysis.color, "note": analysis.note})
        except Exception as e:
            rows.append({"file": case.file, "ok": False, "detail": f"异常：{e}", "elapsed": round(time.time() - t0, 1),
                        "color": None, "note": None})
        r = rows[-1]
        mark = "OK" if r["ok"] else "NG"
        print(f"  [{mark}] {case.file:35s} {r['elapsed']:6.1f}s  {r['detail']}")
    acc = sum(r["ok"] for r in rows) / len(rows) if rows else 0.0
    print(f"  {prompt_name} 总准确率：{sum(r['ok'] for r in rows)}/{len(rows)} = {acc:.0%}")
    return rows, acc


def main():
    print("=== 旧提示词 ===")
    old_rows, old_acc = run("旧提示词", OLD_PROMPT)
    print("\n=== 新提示词（H 任务改进） ===")
    new_rows, new_acc = run("新提示词", NEW_PROMPT)

    print("\n=== 逐条对比 ===")
    for o, n in zip(old_rows, new_rows):
        assert o["file"] == n["file"]
        changed = "→有变化" if o["ok"] != n["ok"] else ""
        print(f"  {o['file']:35s} 旧:{'OK' if o['ok'] else 'NG'} 新:{'OK' if n['ok'] else 'NG'} {changed}")

    print(f"\n总准确率：旧 {old_acc:.0%} → 新 {new_acc:.0%}")
    out = {"old": old_rows, "new": new_rows, "old_accuracy": old_acc, "new_accuracy": new_acc}
    (BENCH_DATA_DIR / "analyzer_eval_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
