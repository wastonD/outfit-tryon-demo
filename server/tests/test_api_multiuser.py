"""契约 v1.3：三种鉴权模式、跨用户隔离、users.json 热更新、旧数据库迁移。"""
from __future__ import annotations

import io
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from outfit_core.assets import AssetStore
from outfit_core.bootstrap import Runtime
from outfit_core.cache import ResultCache
from outfit_core.pipeline import OutfitPipeline
from outfit_core.registry import Registry

from api.db import Database
from api.main import create_app

PRESET_ID = "female-medium-regular-light"


def make_png_bytes(color=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def build_runtime(tmp_path) -> Runtime:
    store = AssetStore(tmp_path / "assets")
    cache = ResultCache(tmp_path / "cache.sqlite3")
    providers = {
        "tryon1": {"type": "fake_tryon"}, "analyzer1": {"type": "fake_analyzer"},
        "segmenter1": {"type": "fake_segmenter"}, "upscaler1": {"type": "fake_upscaler"},
    }
    routes = {"tryon": ["tryon1"], "analyzer": ["analyzer1"], "segmenter": ["segmenter1"],
              "upscaler": ["upscaler1"], "turntable": []}
    registry = Registry.from_config({"providers": providers, "routes": routes}, store)
    return Runtime(registry, store, cache, OutfitPipeline(registry, store, cache))


def make_client(tmp_path, db_name: str = "api.sqlite3") -> TestClient:
    runtime = build_runtime(tmp_path)
    app = create_app(runtime=runtime, db_path=tmp_path / db_name, sync=True)
    return TestClient(app)


def auth(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def import_one(client: TestClient, token: str | None = None, category: str | None = None) -> dict:
    png = make_png_bytes()
    files = [("files", ("garment.png", png, "image/png"))]
    data = {"category": category} if category else {}
    resp = client.post("/api/import/images", files=files, data=data, headers=auth(token))
    assert resp.status_code == 202, resp.text
    return resp.json()["items"][0]


def write_users_file(path, tokens: dict):
    path.write_text(json.dumps({"tokens": tokens}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_real_users_file(monkeypatch, tmp_path):
    """默认指向一个不存在的文件，避免真实仓库里的 server/config/users.json（如果有）影响测试。"""
    monkeypatch.delenv("OUTFIT_API_TOKEN", raising=False)
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(tmp_path / "no-such-users.json"))


# ---------- GET /api/me：三种模式 ----------

def test_me_open_mode(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "local", "name": "local", "mode": "open",
                           "quota": {"daily_outfit_limit": None, "used_today": 0}}


def test_me_single_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTFIT_API_TOKEN", "secret-token")
    client = make_client(tmp_path)

    assert client.get("/api/me").status_code == 401

    resp = client.get("/api/me", headers=auth("secret-token"))
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "default", "name": "default", "mode": "single",
                           "quota": {"daily_outfit_limit": None, "used_today": 0}}


def test_me_multi_mode(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王"},
                                  "tok-2": {"user_id": "u2", "name": "小李"}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)

    resp = client.get("/api/me", headers=auth("tok-1"))
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "u1", "name": "小王", "mode": "multi",
                           "quota": {"daily_outfit_limit": None, "used_today": 0}}

    resp = client.get("/api/me", headers=auth("tok-2"))
    assert resp.json()["user_id"] == "u2"

    assert client.get("/api/me", headers=auth("wrong-token")).status_code == 401
    assert client.get("/api/me").status_code == 401
    # 多用户模式下即使设置了 OUTFIT_API_TOKEN 也应该被忽略（users.json 优先级更高）
    monkeypatch.setenv("OUTFIT_API_TOKEN", "secret-token")
    assert client.get("/api/me", headers=auth("secret-token")).status_code == 401


# ---------- 跨用户隔离 ----------

@pytest.fixture
def multi_client(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王"},
                                  "tok-2": {"user_id": "u2", "name": "小李"}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    return make_client(tmp_path)


def test_garment_list_and_detail_isolated(multi_client):
    client = multi_client
    g1 = import_one(client, token="tok-1")
    g2 = import_one(client, token="tok-2")

    items1 = client.get("/api/garments", headers=auth("tok-1")).json()["items"]
    assert [g["id"] for g in items1] == [g1["id"]]
    items2 = client.get("/api/garments", headers=auth("tok-2")).json()["items"]
    assert [g["id"] for g in items2] == [g2["id"]]

    assert client.get(f"/api/garments/{g2['id']}", headers=auth("tok-1")).status_code == 404
    assert client.get(f"/api/garments/{g1['id']}", headers=auth("tok-2")).status_code == 404
    assert client.get(f"/api/garments/{g1['id']}", headers=auth("tok-1")).status_code == 200


def test_garment_patch_and_delete_isolated(multi_client):
    client = multi_client
    g1 = import_one(client, token="tok-1")

    assert client.patch(f"/api/garments/{g1['id']}", json={"category": "bottom"},
                        headers=auth("tok-2")).status_code == 404
    assert client.delete(f"/api/garments/{g1['id']}", headers=auth("tok-2")).status_code == 404

    assert client.patch(f"/api/garments/{g1['id']}", json={"category": "bottom"},
                        headers=auth("tok-1")).status_code == 200
    assert client.delete(f"/api/garments/{g1['id']}", headers=auth("tok-1")).status_code == 204


def test_garment_reprocess_isolated(multi_client):
    client = multi_client
    g1 = import_one(client, token="tok-1")

    assert client.post(f"/api/garments/{g1['id']}/reprocess", headers=auth("tok-2")).status_code == 404
    assert client.post(f"/api/garments/{g1['id']}/reprocess", headers=auth("tok-1")).status_code == 202


def test_outfit_isolated_and_cannot_use_foreign_garment(multi_client):
    client = multi_client
    g1 = import_one(client, token="tok-1")
    g2 = import_one(client, token="tok-2")

    resp = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [g2["id"]]},
                        headers=auth("tok-1"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "garment_not_found"

    outfit1 = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [g1["id"]]},
                          headers=auth("tok-1")).json()
    outfit2 = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [g2["id"]]},
                          headers=auth("tok-2")).json()

    items1 = client.get("/api/outfits", headers=auth("tok-1")).json()["items"]
    assert [o["id"] for o in items1] == [outfit1["id"]]

    assert client.get(f"/api/outfits/{outfit2['id']}", headers=auth("tok-1")).status_code == 404
    assert client.get(f"/api/outfits/{outfit1['id']}", headers=auth("tok-1")).status_code == 200

    assert client.delete(f"/api/outfits/{outfit1['id']}", headers=auth("tok-2")).status_code == 404
    assert client.delete(f"/api/outfits/{outfit1['id']}", headers=auth("tok-1")).status_code == 204


def test_job_get_and_retry_isolated(multi_client):
    client = multi_client
    g1 = import_one(client, token="tok-1")
    job_id = g1["job_id"]

    assert client.get(f"/api/jobs/{job_id}", headers=auth("tok-2")).status_code == 404
    assert client.get(f"/api/jobs/{job_id}", headers=auth("tok-1")).status_code == 200

    assert client.post(f"/api/jobs/{job_id}/retry", headers=auth("tok-2")).status_code == 404
    # 属于自己但任务已成功，不能重试——用来确认所有权检查发生在状态检查之前（403/409 而不是 404）
    assert client.post(f"/api/jobs/{job_id}/retry", headers=auth("tok-1")).status_code == 409


def test_files_shared_across_users_but_needs_valid_token(multi_client):
    client = multi_client
    g1 = import_one(client, token="tok-1")
    file_url = g1["image"]["url"]

    assert client.get(file_url).status_code == 401
    assert client.get(file_url, headers=auth("wrong-token")).status_code == 401
    assert client.get(file_url, headers=auth("tok-1")).status_code == 200
    # 结果缓存按内容哈希在用户之间共享，契约允许任何一个有效令牌访问 /files
    assert client.get(file_url, headers=auth("tok-2")).status_code == 200
    assert client.get(f"{file_url}?token=tok-2").status_code == 200


# ---------- users.json 热更新 ----------

def test_users_file_hot_reload_without_restart(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王"}})
    monkeypatch.setenv("OUTFIT_USERS_FILE", str(users_path))
    client = make_client(tmp_path)

    assert client.get("/api/me", headers=auth("tok-1")).status_code == 200
    assert client.get("/api/me", headers=auth("tok-2")).status_code == 401

    write_users_file(users_path, {"tok-1": {"user_id": "u1", "name": "小王"},
                                  "tok-2": {"user_id": "u2", "name": "小李"}})
    # 部分文件系统 mtime 精度是秒级，强制往后拨一点，确保被判定为"变了"
    new_mtime = users_path.stat().st_mtime + 1
    os.utime(users_path, (new_mtime, new_mtime))

    resp = client.get("/api/me", headers=auth("tok-2"))
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "u2"


# ---------- 旧数据库迁移 ----------

def test_old_db_migration_defaults_records_to_local_user(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE garments (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, error_code TEXT, error_message TEXT,
            category TEXT, category_source TEXT, analysis TEXT, image TEXT NOT NULL, cutout TEXT,
            source TEXT NOT NULL, job_id TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE outfits (
            id TEXT PRIMARY KEY, preset_id TEXT NOT NULL, garment_ids TEXT NOT NULL, options TEXT NOT NULL,
            status TEXT NOT NULL, error_code TEXT, error_message TEXT, job_id TEXT NOT NULL, result TEXT,
            turntable_status TEXT NOT NULL DEFAULT 'none', turntable_job_id TEXT, turntable_video TEXT,
            turntable_provider TEXT, turntable_error_code TEXT, turntable_error_message TEXT,
            turntable_duration INTEGER, created_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_id TEXT NOT NULL, status TEXT NOT NULL,
            progress_done INTEGER NOT NULL DEFAULT 0, progress_total INTEGER NOT NULL DEFAULT 1,
            progress_note TEXT NOT NULL DEFAULT '', error_code TEXT, error_message TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO garments (id, status, category, category_source, image, source, created_at) "
        "VALUES ('g1', 'ready', 'top', 'ai', '{}', '{}', '2026-01-01T00:00:00Z')")
    conn.execute(
        "INSERT INTO outfits (id, preset_id, garment_ids, options, status, job_id, created_at) "
        "VALUES ('o1', 'p1', '[]', '{}', 'ready', 'j1', '2026-01-01T00:00:00Z')")
    conn.execute(
        "INSERT INTO jobs (id, kind, target_id, status, created_at, updated_at) "
        "VALUES ('j1', 'prepare_garment', 'g1', 'succeeded', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")
    conn.commit()
    conn.close()

    db = Database(db_path)
    assert db.get_garment("g1")["user_id"] == "local"
    assert db.get_outfit("o1")["user_id"] == "local"
    assert db.get_job("j1")["user_id"] == "local"

    assert db.get_garment_for_user("g1", "local") is not None
    assert [g["id"] for g in db.list_garments("local")] == ["g1"]
