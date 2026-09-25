"""契约 v1.4：反馈、每日额度（含北京时间重置）、Job.queue_position、usage_report 报表脚本。"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from outfit_core.assets import AssetStore
from outfit_core.bootstrap import Runtime
from outfit_core.cache import ResultCache
from outfit_core.pipeline import OutfitPipeline
from outfit_core.registry import Registry

from api.db import Database
from api.jobs import JobRunner
from api.main import create_app
from bench.usage_report import collect_usage, render_html, render_text

PRESET_ID = "female-medium-regular-light"


def make_png_bytes(color=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def build_runtime(tmp_path, provider_overrides: dict | None = None, route_overrides: dict | None = None) -> Runtime:
    store = AssetStore(tmp_path / "assets")
    cache = ResultCache(tmp_path / "cache.sqlite3")
    providers = {
        "tryon1": {"type": "fake_tryon"}, "analyzer1": {"type": "fake_analyzer"},
        "segmenter1": {"type": "fake_segmenter"}, "upscaler1": {"type": "fake_upscaler"},
        "turntable1": {"type": "fake_turntable"},
    }
    routes = {"tryon": ["tryon1"], "analyzer": ["analyzer1"], "segmenter": ["segmenter1"],
             "upscaler": ["upscaler1"], "turntable": ["turntable1"]}
    if provider_overrides:
        providers.update(provider_overrides)
    if route_overrides:
        routes.update(route_overrides)
    registry = Registry.from_config({"providers": providers, "routes": routes}, store)
    return Runtime(registry, store, cache, OutfitPipeline(registry, store, cache))


def make_client(tmp_path, runtime: Runtime | None = None, db_name: str = "api.sqlite3") -> TestClient:
    runtime = runtime or build_runtime(tmp_path)
    app = create_app(runtime=runtime, db_path=tmp_path / db_name, sync=True)
    return TestClient(app)


def auth(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def write_users_file(path, tokens: dict):
    path.write_text(json.dumps({"tokens": tokens}), encoding="utf-8")


def import_one(client: TestClient, token: str | None = None) -> dict:
    png = make_png_bytes()
    files = [("files", ("garment.png", png, "image/png"))]
    resp = client.post("/api/import/images", files=files, headers=auth(token))
    assert resp.status_code == 202, resp.text
    return resp.json()["items"][0]


def create_outfit_req(client: TestClient, token: str | None, garment_id: str):
    return client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment_id]},
                       headers=auth(token))


@pytest.fixture(autouse=True)
def _no_real_users_file(monkeypatch, tmp_path):
    """避免真实仓库里的 server/config/users.json 或环境变量影响测试。"""
    monkeypatch.delenv("OUTFIT_API_TOKEN", raising=False)
    monkeypatch.delenv("OUTFIT_DAILY_OUTFIT_LIMIT", raising=False)
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(tmp_path / "no-such-users.json"))


# ================= 反馈 POST /api/feedback =================

def test_feedback_success_outfit_with_image(tmp_path):
    client = make_client(tmp_path)
    g = import_one(client)
    outfit = create_outfit_req(client, None, g["id"]).json()
    assert outfit["status"] == "ready"

    resp = client.post("/api/feedback", json={"target_type": "outfit", "target_id": outfit["id"],
                                              "rating": 5, "text": "很棒"})
    assert resp.status_code == 201, resp.text
    assert "id" in resp.json()


def test_feedback_general_text_only(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/feedback", json={"target_type": "general", "text": "希望增加更多模特形象"})
    assert resp.status_code == 201


def test_feedback_general_rating_only(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/feedback", json={"target_type": "general", "rating": 4})
    assert resp.status_code == 201


def test_feedback_both_empty_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/feedback", json={"target_type": "general"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"

    # 纯空白 text 视同未提供
    resp2 = client.post("/api/feedback", json={"target_type": "general", "text": "   "})
    assert resp2.status_code == 400


def test_feedback_text_too_long_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/feedback", json={"target_type": "general", "text": "很长" * 600})
    assert resp.status_code == 400


def test_feedback_rating_out_of_range_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/feedback", json={"target_type": "general", "rating": 6})
    assert resp.status_code == 400


def test_feedback_target_id_required_when_not_general_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/feedback", json={"target_type": "outfit", "rating": 5})
    assert resp.status_code == 400


def test_feedback_foreign_resource_404(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王"},
                                  "tok-2": {"user_id": "u2", "name": "小李"}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)
    g1 = import_one(client, token="tok-1")
    outfit1 = create_outfit_req(client, "tok-1", g1["id"]).json()

    resp = client.post("/api/feedback", json={"target_type": "outfit", "target_id": outfit1["id"], "rating": 3},
                       headers=auth("tok-2"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ================= 额度 =================

def test_quota_open_mode_unlimited(tmp_path):
    client = make_client(tmp_path)
    g = import_one(client)
    for _ in range(5):
        assert create_outfit_req(client, None, g["id"]).status_code == 202
    me = client.get("/api/me").json()
    assert me["quota"] == {"daily_outfit_limit": None, "used_today": 5}


def test_quota_single_mode_env_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTFIT_API_TOKEN", "secret")
    monkeypatch.setenv("OUTFIT_DAILY_OUTFIT_LIMIT", "1")
    client = make_client(tmp_path)
    g = import_one(client, token="secret")

    assert create_outfit_req(client, "secret", g["id"]).status_code == 202
    resp = create_outfit_req(client, "secret", g["id"])
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "quota_exceeded"

    me = client.get("/api/me", headers=auth("secret")).json()
    assert me["quota"] == {"daily_outfit_limit": 1, "used_today": 1}


def test_quota_multi_mode_limit_from_users_json(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 2}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)
    g = import_one(client, token="tok-1")

    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 202
    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 202
    resp = create_outfit_req(client, "tok-1", g["id"])
    assert resp.status_code == 429
    assert "2" in resp.json()["error"]["message"]

    me = client.get("/api/me", headers=auth("tok-1")).json()
    assert me["quota"] == {"daily_outfit_limit": 2, "used_today": 2}


def test_quota_hot_reload_changes_limit_immediately(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 1}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)
    g = import_one(client, token="tok-1")

    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 202
    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 429

    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 5}})
    new_mtime = users_path.stat().st_mtime + 1
    os.utime(users_path, (new_mtime, new_mtime))

    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 202


def test_quota_daily_reset_with_injectable_clock(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 1}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)
    g = import_one(client, token="tok-1")

    fixed_now = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)  # 北京时间 2026-09-19 18:00
    client.app.state.quota.clock = lambda: fixed_now

    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 202
    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 429

    next_day = fixed_now + timedelta(days=1)
    client.app.state.quota.clock = lambda: next_day
    assert create_outfit_req(client, "tok-1", g["id"]).status_code == 202


def test_quota_counts_cache_hit_outfits(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 5}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)
    g = import_one(client, token="tok-1")

    first = create_outfit_req(client, "tok-1", g["id"])
    assert first.status_code == 202
    assert first.json()["result"]["cached"] is False
    second = create_outfit_req(client, "tok-1", g["id"])
    assert second.status_code == 202
    assert second.json()["result"]["cached"] is True   # 完全相同的请求命中缓存

    me = client.get("/api/me", headers=auth("tok-1")).json()
    assert me["quota"]["used_today"] == 2   # 缓存命中同样计入额度


def test_quota_turntable_counts(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 5}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)
    g = import_one(client, token="tok-1")
    outfit = create_outfit_req(client, "tok-1", g["id"]).json()

    resp = client.post(f"/api/outfits/{outfit['id']}/turntable", headers=auth("tok-1"))
    assert resp.status_code == 202

    me = client.get("/api/me", headers=auth("tok-1")).json()
    assert me["quota"]["used_today"] == 2   # 1 次搭配 + 1 次 360°


def test_quota_retry_tryon_counts(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 5}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    runtime = build_runtime(tmp_path, provider_overrides={"tryon1": {"type": "fake_tryon", "fail": True}})
    client = make_client(tmp_path, runtime=runtime)
    g = import_one(client, token="tok-1")

    outfit = create_outfit_req(client, "tok-1", g["id"]).json()
    assert outfit["status"] == "failed"
    job_id = outfit["job_id"]

    me = client.get("/api/me", headers=auth("tok-1")).json()
    assert me["quota"]["used_today"] == 1   # 创建搭配这一步已经计入，不管试衣本身成不成功

    retry_resp = client.post(f"/api/jobs/{job_id}/retry", headers=auth("tok-1"))
    assert retry_resp.status_code == 202

    me2 = client.get("/api/me", headers=auth("tok-1")).json()
    assert me2["quota"]["used_today"] == 2   # 重试 tryon 任务也计入


def test_quota_retry_prepare_garment_not_counted(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王", "daily_outfit_limit": 5}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    runtime = build_runtime(tmp_path, route_overrides={"analyzer": []})
    client = make_client(tmp_path, runtime=runtime)

    garment = import_one(client, token="tok-1")
    assert garment["status"] == "failed"
    assert garment["error"]["code"] == "category_required"
    job_id = garment["job_id"]

    me = client.get("/api/me", headers=auth("tok-1")).json()
    assert me["quota"]["used_today"] == 0

    retry_resp = client.post(f"/api/jobs/{job_id}/retry", headers=auth("tok-1"))
    assert retry_resp.status_code == 202

    me2 = client.get("/api/me", headers=auth("tok-1")).json()
    assert me2["quota"]["used_today"] == 0   # prepare_garment 的重试不计入额度


# ================= Job.queue_position =================

def test_queue_position_field_present_and_null_when_done(tmp_path):
    client = make_client(tmp_path)
    g = import_one(client)
    job = client.get(f"/api/jobs/{g['job_id']}").json()
    assert job["queue_position"] is None
    assert job["status"] == "succeeded"


def test_queue_position_gpu_fifo_then_null_after_start(tmp_path):
    """连续提交 3 个排在同一个 gpu 任务后面的任务，位置依次为 0、1、2；开始执行后变为 null。"""
    db = Database(tmp_path / "jobs.sqlite3")
    runner = JobRunner(db, sync=False)
    try:
        gates = [threading.Event() for _ in range(4)]
        started = [threading.Event() for _ in range(4)]

        def handler_builder(target_id: str):
            idx = int(target_id)

            def fn(report):
                started[idx].set()
                assert gates[idx].wait(timeout=5), f"job {idx} 没有在超时前被释放"
            return fn

        runner.register("tryon", handler_builder)

        job_ids = [runner.submit("tryon", target_id="0", user_id="u1")]
        # 确认第 0 个任务已经开始执行、占住 gpu 队列唯一的 worker，
        # 后面提交的 3 个才能保证仍在排队，不会被并发抢跑
        assert started[0].wait(timeout=5)

        job_ids += [runner.submit("tryon", target_id=str(i), user_id="u1") for i in range(1, 4)]

        assert runner.queue_position(job_ids[0]) is None   # 正在执行，不算排队
        assert runner.queue_position(job_ids[1]) == 0
        assert runner.queue_position(job_ids[2]) == 1
        assert runner.queue_position(job_ids[3]) == 2

        gates[0].set()
        assert started[1].wait(timeout=5)
        assert runner.queue_position(job_ids[1]) is None   # 开始执行后变为 null
        assert runner.queue_position(job_ids[2]) == 0
        assert runner.queue_position(job_ids[3]) == 1

        gates[1].set()
        gates[2].set()
        gates[3].set()
        deadline = time.time() + 5
        while time.time() < deadline and any(db.get_job(jid)["status"] != "succeeded" for jid in job_ids):
            time.sleep(0.01)
        for jid in job_ids:
            assert db.get_job(jid)["status"] == "succeeded"
        assert all(runner.queue_position(jid) is None for jid in job_ids)
    finally:
        runner.close()


def test_queue_position_survives_restart_as_null(tmp_path):
    """服务重启后，旧的 queued/running 任务会被标成 failed；新 JobRunner 的排队状态从空开始，不会残留脏数据。"""
    db = Database(tmp_path / "restart.sqlite3")
    job = db.create_job(kind="tryon", target_id="x", user_id="u1")
    db.update_job(job["id"], status="queued")

    db.recover_running_jobs()
    assert db.get_job(job["id"])["status"] == "failed"

    runner = JobRunner(db, sync=False)
    try:
        assert runner.queue_position(job["id"]) is None
    finally:
        runner.close()


# ================= server/bench/usage_report.py =================

def test_usage_report_collects_stats_and_feedback(tmp_path):
    db_path = tmp_path / "report.sqlite3"
    db = Database(db_path)
    now = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    g1 = db.create_garment(status="ready", category="top", category_source="ai",
                           image={"sha256": "a" * 64, "mime": "image/png"}, source={}, user_id="u1")
    db.update_garment(g1["id"], created_at=recent)
    g2 = db.create_garment(status="ready", category="top", category_source="ai",
                           image={"sha256": "b" * 64, "mime": "image/png"}, source={}, user_id="u1")
    db.update_garment(g2["id"], created_at=recent)
    g_old = db.create_garment(status="ready", category="top", category_source="ai",
                              image={"sha256": "c" * 64, "mime": "image/png"}, source={}, user_id="u1")
    db.update_garment(g_old["id"], created_at=old)  # 超出 7 天窗口，不应计入 imports

    o1 = db.create_outfit(preset_id=PRESET_ID, garment_ids=[g1["id"]], options={}, job_id="", user_id="u1")
    db.update_outfit(o1["id"], created_at=recent, status="ready",
                     result={"image": {"sha256": "d" * 64, "mime": "image/png"},
                             "metrics": [{"seconds": 10}, {"seconds": 20}]})
    o2 = db.create_outfit(preset_id=PRESET_ID, garment_ids=[g2["id"]], options={}, job_id="", user_id="u1")
    db.update_outfit(o2["id"], created_at=recent, status="ready",
                     result={"image": {"sha256": "e" * 64, "mime": "image/png"},
                             "metrics": [{"seconds": 10}]})

    job = db.create_job(kind="tryon", target_id="whatever", user_id="u1")
    db.update_job(job["id"], status="failed", error_code="tryon_failed", created_at=recent)

    db.record_usage_event("u1", "quota_exceeded", created_at=recent)

    db.create_feedback(user_id="u1", target_type="outfit", target_id=o1["id"], rating=4, text="还不错")
    db.create_feedback(user_id="u1", target_type="general", target_id=None, rating=None, text="求求增加更多模特")

    data = collect_usage(db_path, days=7, now=now)
    assert data["days"] == 7

    u = next(u for u in data["users"] if u["user_id"] == "u1")
    assert u["imports"] == 2
    assert u["outfits"] == 2
    assert u["failures"] == 1
    assert u["failure_reasons"] == {"tryon:tryon_failed": 1}
    assert u["quota_hits"] == 1
    assert u["tryon_avg_seconds"] == 20.0
    assert u["tryon_p90_seconds"] == 28.0

    assert len(data["feedback"]) == 2
    by_type = {f["target_type"]: f for f in data["feedback"]}
    assert by_type["outfit"]["image_url"] == f"/files/{'d' * 64}"
    assert by_type["general"]["image_url"] is None

    # 渲染不应报错，且能看到关键信息
    text = render_text(data)
    assert "u1" in text
    html_out = render_html(data)
    assert "u1" in html_out


def test_usage_report_empty_db_smoke(tmp_path):
    data = collect_usage(tmp_path / "empty.sqlite3", days=7)
    assert data["users"] == []
    assert data["feedback"] == []
    assert "没有用户活动数据" in render_text(data)
    assert "没有用户活动数据" in render_html(data)


def test_usage_report_never_leaks_tokens(tmp_path, monkeypatch):
    secret = "super-secret-token-xyz"
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {secret: {"user_id": "u9", "name": "神秘用户"}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))

    db_path = tmp_path / "report2.sqlite3"
    db = Database(db_path)
    db.create_garment(status="ready", category="top", category_source="ai",
                      image={"sha256": "f" * 64, "mime": "image/png"}, source={}, user_id="u9")

    data = collect_usage(db_path, days=7)
    text = render_text(data)
    html_out = render_html(data)
    assert secret not in text
    assert secret not in html_out
    assert "神秘用户" in text
    assert "神秘用户" in html_out


def test_usage_report_cli_smoke(tmp_path, capsys):
    from bench.usage_report import main
    db_path = tmp_path / "cli.sqlite3"
    Database(db_path)
    main(["--db", str(db_path), "--days", "3"])
    captured = capsys.readouterr()
    assert "使用情况报表" in captured.out
