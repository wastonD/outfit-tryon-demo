"""真实接口联调脚本。通过 HTTP 走一遍 导入→识别→搭配→下载 的完整流程，
输出每一步的耗时，用来验证真实后端（含本地模型）是否按接口约定工作。可重复运行。

前置条件：worker（9001）、llama-server（8080）、`uvicorn api.main:app --port 8000` 均已启动。

用法（在 server 目录下）：
  .venv\\Scripts\\python -m bench.e2e_api
  .venv\\Scripts\\python -m bench.e2e_api --base-url http://127.0.0.1:8000 --token xxx
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

CASES = json.loads((Path(__file__).parent / "cases.example.json").read_text(encoding="utf-8"))["cases"]
TOP_URL = CASES[0]["garments"][0]["src"]
BOTTOM_URL = CASES[0]["garments"][1]["src"]
DRESS_URL = CASES[1]["garments"][0]["src"]

BENCH_DATA_DIR = Path(__file__).parent.parent / "data" / "bench"


def poll(client: httpx.Client, path: str, timeout: float = 180) -> tuple[dict, float]:
    start = time.time()
    while True:
        r = client.get(path)
        r.raise_for_status()
        body = r.json()
        if body.get("status") not in ("pending", "processing", "queued", "running"):
            return body, round(time.time() - start, 2)
        if time.time() - start > timeout:
            raise TimeoutError(f"{path} 超时未完成，最后状态：{body}")
        time.sleep(1.5)


def step(name: str) -> None:
    print(f"\n=== {name} ===")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    timings: dict[str, float] = {}
    BENCH_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as client:
        step("1. multipart 导入上衣 + 裤子")
        t0 = time.time()
        top_bytes = httpx.get(TOP_URL, timeout=30).content
        bottom_bytes = httpx.get(BOTTOM_URL, timeout=30).content
        files = [
            ("files", ("top.jpeg", top_bytes, "image/jpeg")),
            ("files", ("bottom.jpeg", bottom_bytes, "image/jpeg")),
        ]
        r = client.post("/api/import/images", files=files)
        r.raise_for_status()
        items = r.json()["items"]
        timings["import_multipart_request"] = round(time.time() - t0, 2)
        print(f"  创建 {len(items)} 件衣物：{[g['id'] for g in items]}，请求耗时 {timings['import_multipart_request']}s")

        ready_garments = []
        for g in items:
            body, secs = poll(client, f"/api/garments/{g['id']}")
            timings[f"garment_{g['id']}_ready"] = secs
            print(f"  衣物 {g['id']} → {body['status']}（category={body.get('category')}），等待 {secs}s")
            if body["status"] != "ready":
                raise RuntimeError(f"衣物 {g['id']} 未就绪：{body.get('error')}")
            ready_garments.append(body)

        step("2. JSON 从 URL 导入连衣裙")
        t0 = time.time()
        r = client.post("/api/import/images", json={
            "images": [{"url": DRESS_URL}],
            "source": {"url": DRESS_URL, "title": "阿里云示例连衣裙", "platform": "other", "price": None},
        })
        r.raise_for_status()
        dress_item = r.json()["items"][0]
        timings["import_json_request"] = round(time.time() - t0, 2)
        dress_body, secs = poll(client, f"/api/garments/{dress_item['id']}")
        timings["dress_ready"] = secs
        print(f"  连衣裙 {dress_item['id']} → {dress_body['status']}（category={dress_body.get('category')}），等待 {secs}s")

        step("3. 获取预设模特")
        r = client.get("/api/presets")
        r.raise_for_status()
        presets = r.json()["items"]
        if not presets:
            raise RuntimeError("没有可用的预设模特（/api/presets 返回空）")
        preset = presets[0]
        print(f"  使用模特 {preset['id']}")

        step("4. 创建搭配：上衣 + 裤子")
        garment_ids = [g["id"] for g in ready_garments]
        outfit_req = {"preset_id": preset["id"], "garment_ids": garment_ids,
                      "options": {"tuck": "auto", "upscale": False}}
        t0 = time.time()
        r = client.post("/api/outfits", json=outfit_req)
        r.raise_for_status()
        outfit = r.json()
        outfit_body, secs = poll(client, f"/api/outfits/{outfit['id']}", timeout=300)
        timings["outfit_first_ready"] = secs
        print(f"  搭配 {outfit['id']} → {outfit_body['status']}，耗时 {secs}s")
        if outfit_body["status"] != "ready":
            raise RuntimeError(f"搭配未就绪：{outfit_body.get('error')}")
        result = outfit_body["result"]
        print(f"  结果：provider={result['provider']} total_seconds={result['total_seconds']} "
              f"total_cost={result['total_cost']} cached={result['cached']} "
              f"skipped={result['skipped_garment_ids']}")

        step("5. 下载结果图")
        r = client.get(result["image"]["url"])
        r.raise_for_status()
        out_path = BENCH_DATA_DIR / "e2e_result_first.jpg"
        out_path.write_bytes(r.content)
        print(f"  已保存到 {out_path}（{len(r.content)} 字节）")

        step("6. 开启高清（upscale=true）再生成一次")
        t0 = time.time()
        r = client.post("/api/outfits", json={**outfit_req, "options": {"tuck": "auto", "upscale": True}})
        r.raise_for_status()
        outfit_hd = r.json()
        outfit_hd_body, secs = poll(client, f"/api/outfits/{outfit_hd['id']}", timeout=300)
        timings["outfit_hd_ready"] = secs
        result_hd = outfit_hd_body["result"]
        print(f"  高清搭配 {outfit_hd['id']} → {outfit_hd_body['status']}，耗时 {secs}s，"
              f"total_seconds={result_hd['total_seconds']} cached={result_hd['cached']}")
        r = client.get(result_hd["image"]["url"])
        out_path_hd = BENCH_DATA_DIR / "e2e_result_hd.jpg"
        out_path_hd.write_bytes(r.content)
        print(f"  已保存到 {out_path_hd}（{len(r.content)} 字节）")

        step("7. 重复第一次请求，确认命中缓存")
        t0 = time.time()
        r = client.post("/api/outfits", json=outfit_req)
        r.raise_for_status()
        outfit_repeat = r.json()
        outfit_repeat_body, secs = poll(client, f"/api/outfits/{outfit_repeat['id']}")
        timings["outfit_repeat_ready"] = secs
        cached = outfit_repeat_body["result"]["cached"]
        print(f"  重复搭配 {outfit_repeat['id']} → cached={cached}，耗时 {secs}s")
        assert cached is True, "预期与第一次完全相同的搭配请求应该命中缓存（result.cached=True）"

    print("\n=== 耗时汇总（秒）===")
    print(json.dumps(timings, ensure_ascii=False, indent=2))
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "timings": timings}
    (BENCH_DATA_DIR / "e2e_last_run.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n✅ e2e 流程全部通过")


if __name__ == "__main__":
    main()
