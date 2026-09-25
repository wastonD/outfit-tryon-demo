"""内测运营报表（契约 v1.4）：按用户统计导入/搭配/失败/试衣耗时/额度触顶，附最近反馈。

用法：
    python -m bench.usage_report                # 最近 7 天，输出文本到终端
    python -m bench.usage_report --days 30
    python -m bench.usage_report --html          # 额外把静态页面保存到 server/data/reports/
    python -m bench.usage_report --db path\to\api.sqlite3

统计窗口按 created_at（UTC）和"最近 N 天"比较，不追求和额度重置的北京时间口径完全一致（够报表
用途即可）；反馈列表不受天数窗口限制，返回全部。报表里不出现任何令牌（只可能出现 users.json
里配置的显示名，读取失败时退化为 user_id）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from outfit_core.bootstrap import SERVER_ROOT

from api.db import Database


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _percentile(values: list[float], pct: float) -> float | None:
    """线性插值百分位数（常见的"最近排名"定义之一），values 为空返回 None。"""
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def default_db_path() -> Path:
    return Path(os.environ.get("OUTFIT_DATA", SERVER_ROOT / "data")) / "api.sqlite3"


def _load_user_names() -> dict[str, str]:
    """尽力从 users.json 读出 user_id -> name 的展示名；只取名字，不返回令牌本身。"""
    path = Path(os.environ.get("OUTFIT_USERS_FILE", SERVER_ROOT / "config" / "users.json"))
    names: dict[str, str] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for info in (data.get("tokens") or {}).values():
            uid = info.get("user_id")
            if uid:
                names[uid] = info.get("name") or uid
    except (OSError, ValueError):
        pass
    return names


def collect_usage(db_path, days: int = 7, now: datetime | None = None) -> dict:
    """从数据库聚合最近 days 天的使用情况；now 可注入，便于测试固定时间。"""
    now = now or datetime.now(timezone.utc)
    since = _iso(now - timedelta(days=days))
    db = Database(db_path)  # 幂等：顺带补齐 usage_events/feedback 等新表（老库直接可用）
    conn = db.connection

    users: dict[str, dict] = {}

    def bucket(uid: str) -> dict:
        return users.setdefault(uid, {
            "user_id": uid, "imports": 0, "outfits": 0, "failures": 0,
            "failure_reasons": {}, "tryon_avg_seconds": None, "tryon_p90_seconds": None,
            "quota_hits": 0,
        })

    for row in conn.execute(
            "SELECT user_id, COUNT(*) AS c FROM garments WHERE created_at>=? GROUP BY user_id", (since,)):
        bucket(row["user_id"])["imports"] = row["c"]

    for row in conn.execute(
            "SELECT user_id, COUNT(*) AS c FROM outfits WHERE created_at>=? GROUP BY user_id", (since,)):
        bucket(row["user_id"])["outfits"] = row["c"]

    for row in conn.execute(
            "SELECT user_id, kind, error_code, COUNT(*) AS c FROM jobs "
            "WHERE status='failed' AND created_at>=? GROUP BY user_id, kind, error_code", (since,)):
        b = bucket(row["user_id"])
        b["failures"] += row["c"]
        reason = f"{row['kind']}:{row['error_code'] or 'unknown'}"
        b["failure_reasons"][reason] = b["failure_reasons"].get(reason, 0) + row["c"]

    for row in conn.execute(
            "SELECT user_id, COUNT(*) AS c FROM usage_events "
            "WHERE kind='quota_exceeded' AND created_at>=? GROUP BY user_id", (since,)):
        bucket(row["user_id"])["quota_hits"] = row["c"]

    durations: dict[str, list[float]] = {}
    for row in conn.execute(
            "SELECT user_id, result FROM outfits WHERE status='ready' AND result IS NOT NULL "
            "AND created_at>=?", (since,)):
        try:
            result = json.loads(row["result"])
            seconds = sum(m["seconds"] for m in result.get("metrics", []))
        except (ValueError, TypeError, KeyError):
            continue
        durations.setdefault(row["user_id"], []).append(seconds)
    for uid, values in durations.items():
        b = bucket(uid)
        b["tryon_avg_seconds"] = round(sum(values) / len(values), 1)
        p90 = _percentile(values, 0.9)
        b["tryon_p90_seconds"] = round(p90, 1) if p90 is not None else None

    names = _load_user_names()
    for uid, b in users.items():
        b["name"] = names.get(uid, uid)

    feedback = []
    for row in conn.execute("SELECT * FROM feedback ORDER BY created_at DESC"):
        item = dict(row)
        item["image_url"] = None
        if item["target_type"] == "outfit" and item["target_id"]:
            outfit = db.get_outfit(item["target_id"])
            image = (outfit or {}).get("result", {}) or {}
            image = image.get("image") if isinstance(image, dict) else None
            if image and image.get("sha256"):
                item["image_url"] = f"/files/{image['sha256']}"
        feedback.append(item)

    return {
        "generated_at": _iso(now), "days": days, "since": since,
        "users": sorted(users.values(), key=lambda u: u["user_id"]),
        "feedback": feedback,
    }


def render_text(data: dict) -> str:
    lines = [f"使用情况报表：最近 {data['days']} 天（生成于 {data['generated_at']}）", ""]
    if not data["users"]:
        lines.append("（没有用户活动数据）")
    for u in data["users"]:
        lines.append(
            f"- {u['name']}（{u['user_id']}）：导入 {u['imports']}，搭配 {u['outfits']}，失败 {u['failures']}，"
            f"额度触顶 {u['quota_hits']} 次，试衣耗时均值 {u['tryon_avg_seconds']}s / P90 {u['tryon_p90_seconds']}s")
        for reason, count in sorted(u["failure_reasons"].items(), key=lambda kv: -kv[1]):
            lines.append(f"    失败原因 {reason}：{count} 次")
    lines.append("")
    lines.append(f"反馈（共 {len(data['feedback'])} 条，按时间倒序）：")
    if not data["feedback"]:
        lines.append("（暂无反馈）")
    for f in data["feedback"]:
        rating = f["rating"] if f["rating"] is not None else "-"
        target = f["target_type"] + (f"({f['target_id']})" if f["target_id"] else "")
        suffix = f"  图片：{f['image_url']}" if f.get("image_url") else ""
        lines.append(f"- [{f['created_at']}] {f['user_id']} · {target} · 评分 {rating}：{f['text'] or ''}{suffix}")
    return "\n".join(lines)


_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1f;--text:#ededed;--muted:#a0a0a5;--line:#333}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.6 system-ui,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 12px}
.muted{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);border:1px solid var(--line);
border-radius:8px;overflow:hidden}
td,th{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0}
img.thumb{max-width:160px;border-radius:6px;display:block;margin-top:6px}
"""


def render_html(data: dict) -> str:
    esc = html.escape
    rows = []
    for u in data["users"]:
        reasons = "；".join(f"{k}×{v}" for k, v in sorted(u["failure_reasons"].items(), key=lambda kv: -kv[1])) or "-"
        avg = u["tryon_avg_seconds"] if u["tryon_avg_seconds"] is not None else "-"
        p90 = u["tryon_p90_seconds"] if u["tryon_p90_seconds"] is not None else "-"
        rows.append(
            f"<tr><td>{esc(u['name'])}<br><span class=muted>{esc(u['user_id'])}</span></td>"
            f"<td>{u['imports']}</td><td>{u['outfits']}</td><td>{u['failures']}</td>"
            f"<td class=muted>{esc(reasons)}</td><td>{avg}</td><td>{p90}</td><td>{u['quota_hits']}</td></tr>")
    users_table = (
        "<table><tr><th>用户</th><th>导入</th><th>搭配</th><th>失败</th><th>失败原因</th>"
        "<th>试衣均值(s)</th><th>P90(s)</th><th>额度触顶</th></tr>" + "".join(rows) + "</table>"
    ) if rows else "<p class=muted>没有用户活动数据</p>"

    cards = []
    for f in data["feedback"]:
        rating = f["rating"] if f["rating"] is not None else "-"
        target = esc(f["target_type"]) + (f" · {esc(f['target_id'])}" if f["target_id"] else "")
        img = f"<img class=thumb src='{esc(f['image_url'])}'>" if f.get("image_url") else ""
        cards.append(
            f"<div class=card><div class=muted>{esc(f['created_at'])} · {esc(f['user_id'])} · {target} · "
            f"评分 {rating}</div><div>{esc(f['text'] or '')}</div>{img}</div>")
    feedback_html = "".join(cards) or "<p class=muted>暂无反馈</p>"

    return (
        "<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'><title>内测使用情况报表</title>"
        f"<style>{_CSS}</style></head><body><main>"
        "<h1>内测使用情况报表</h1>"
        f"<p class=muted>最近 {data['days']} 天 · 生成于 {esc(data['generated_at'])}</p>"
        f"<h2>按用户统计</h2>{users_table}"
        f"<h2>反馈（{len(data['feedback'])} 条，按时间倒序）</h2>{feedback_html}"
        "</main></body></html>"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="内测使用情况报表（契约 v1.4）")
    parser.add_argument("--days", type=int, default=7, help="统计最近几天，默认 7")
    parser.add_argument("--db", type=str, default=None, help="sqlite 数据库路径，默认和服务端一致")
    parser.add_argument("--html", action="store_true", help="额外输出静态页面到 server/data/reports/")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else default_db_path()
    data = collect_usage(db_path, days=args.days)
    print(render_text(data))

    if args.html:
        out_dir = SERVER_ROOT / "data" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"usage-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.html"
        out_path.write_text(render_html(data), encoding="utf-8")
        print(f"\nHTML 报告已保存到 {out_path}")


if __name__ == "__main__":
    main()
