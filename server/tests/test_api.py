"""接口测试：只使用 conftest.py 里的假实现，不启动 worker、不调用真实模型。"""
from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from outfit_core.assets import AssetStore
from outfit_core.bootstrap import Runtime
from outfit_core.cache import ResultCache
from outfit_core.pipeline import OutfitPipeline
from outfit_core.registry import Registry

from api.main import create_app

PRESET_ID = "female-medium-regular-light"


def make_png_bytes(color=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def build_runtime(tmp_path, providers=None, routes=None) -> Runtime:
    store = AssetStore(tmp_path / "assets")
    cache = ResultCache(tmp_path / "cache.sqlite3")
    base_providers = {
        "tryon1": {"type": "fake_tryon"},
        "analyzer1": {"type": "fake_analyzer"},
        "segmenter1": {"type": "fake_segmenter"},
        "upscaler1": {"type": "fake_upscaler"},
    }
    base_routes = {
        "tryon": ["tryon1"], "analyzer": ["analyzer1"], "segmenter": ["segmenter1"],
        "upscaler": ["upscaler1"], "turntable": [],
    }
    if providers:
        base_providers.update(providers)
    if routes:
        base_routes.update(routes)
    registry = Registry.from_config({"providers": base_providers, "routes": base_routes}, store)
    return Runtime(registry, store, ResultCache(tmp_path / "cache.sqlite3"), OutfitPipeline(registry, store, cache))


def make_client(tmp_path, providers=None, routes=None, sync=True, db_name="api.sqlite3") -> tuple[TestClient, Runtime]:
    runtime = build_runtime(tmp_path, providers=providers, routes=routes)
    app = create_app(runtime=runtime, db_path=tmp_path / db_name, sync=sync)
    return TestClient(app), runtime


def import_one(client: TestClient, *, category: str | None = None, data_uri: bool = False) -> dict:
    png = make_png_bytes()
    if data_uri:
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        payload = {"images": [{"data_uri": uri, "category": category}]}
        resp = client.post("/api/import/images", json=payload)
    else:
        files = [("files", ("garment.png", png, "image/png"))]
        data = {"category": category} if category else {}
        resp = client.post("/api/import/images", files=files, data=data)
    assert resp.status_code == 202, resp.text
    return resp.json()["items"][0]


# ---------- 导入 ----------

def test_import_multipart_two_images(tmp_path):
    client, _ = make_client(tmp_path)
    png = make_png_bytes()
    files = [("files", ("a.png", png, "image/png")), ("files", ("b.png", png, "image/png"))]
    resp = client.post("/api/import/images", files=files)
    assert resp.status_code == 202
    items = resp.json()["items"]
    assert len(items) == 2
    for item in items:
        assert item["status"] == "ready"
        assert item["category"] == "top"          # 来自 FakeAnalyzer 默认识别结果
        assert item["category_source"] == "ai"
        assert item["job_id"]


def test_import_json_data_uri_with_category(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client, category="bottom", data_uri=True)
    assert garment["status"] == "ready"
    assert garment["category"] == "bottom"
    assert garment["category_source"] == "user"


def test_import_category_required_then_patch(tmp_path):
    client, _ = make_client(tmp_path, routes={"analyzer": []})
    garment = import_one(client)
    assert garment["status"] == "failed"
    assert garment["error"]["code"] == "category_required"

    resp = client.patch(f"/api/garments/{garment['id']}", json={"category": "top"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["category"] == "top"
    assert body["category_source"] == "user"
    assert body["error"] is None


def make_avif_bytes(color=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="AVIF")
    return buf.getvalue()


def make_heic_bytes(color=(30, 150, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="HEIF")
    return buf.getvalue()


def test_import_avif_multipart_converted_to_png(tmp_path):
    client, _ = make_client(tmp_path)
    files = [("files", ("photo.avif", make_avif_bytes(), "image/avif"))]
    resp = client.post("/api/import/images", files=files)
    assert resp.status_code == 202, resp.text
    item = resp.json()["items"][0]
    assert item["image"]["mime"] == "image/png"
    file_resp = client.get(item["image"]["url"])
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(file_resp.content)).format == "PNG"


def test_import_heic_json_data_uri_converted_to_png(tmp_path):
    client, _ = make_client(tmp_path)
    uri = "data:image/heic;base64," + base64.b64encode(make_heic_bytes()).decode()
    resp = client.post("/api/import/images", json={"images": [{"data_uri": uri}]})
    assert resp.status_code == 202, resp.text
    item = resp.json()["items"][0]
    assert item["image"]["mime"] == "image/png"
    file_resp = client.get(item["image"]["url"])
    assert file_resp.status_code == 200
    assert Image.open(io.BytesIO(file_resp.content)).format == "PNG"


def test_import_unsupported_format_still_422(tmp_path):
    client, _ = make_client(tmp_path)
    files = [("files", ("not-an-image.bin", b"not an image at all", "application/octet-stream"))]
    resp = client.post("/api/import/images", files=files)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unsupported_image"


def test_analysis_text_sanitized_removes_surrogates(tmp_path):
    """analyzer 偶发返回带孤立 UTF-16 代理项的文本，写库前要清洗掉。"""
    from outfit_core.capabilities import GarmentAnalyzer, Provider
    from outfit_core.registry import register, registered_types
    from outfit_core.types import GarmentAnalysis

    if "fake_analyzer_dirty_text" not in registered_types():
        @register("fake_analyzer_dirty_text")
        class DirtyTextAnalyzer(Provider, GarmentAnalyzer):
            def analyze(self, image):
                return GarmentAnalysis(category="top", shot="flat_lay", tryon_ready=True,
                                       color="红色\ud800裙子", note="\ud83c\ud83c")

    client, _ = make_client(tmp_path, providers={"analyzer1": {"type": "fake_analyzer_dirty_text"}})
    garment = import_one(client)
    assert garment["analysis"]["color"] == "红色裙子"
    assert garment["analysis"]["note"] is None


# ---------- 衣橱 ----------

def test_garment_not_found(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.get("/api/garments/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---------- 重新处理（reprocess，契约 v1.2） ----------

def test_reprocess_basic_flow_gets_new_job(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client)
    resp = client.post(f"/api/garments/{garment['id']}/reprocess")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["job_id"] != garment["job_id"]


def test_reprocess_busy_conflict(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client)
    client.app.state.db.update_garment(garment["id"], status="processing")
    resp = client.post(f"/api/garments/{garment['id']}/reprocess")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "garment_busy"


def test_reprocess_keeps_user_specified_category(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client, category="bottom")  # fake_analyzer 默认识别成 top，但用户指定了 bottom
    assert garment["category_source"] == "user"

    resp = client.post(f"/api/garments/{garment['id']}/reprocess")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["category"] == "bottom"
    assert body["category_source"] == "user"


def test_reprocess_force_segment_calls_segmenter_even_on_flat_lay(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client, category="top")
    assert garment["cutout"] is None  # 默认 flat_lay 不抠图

    resp = client.post(f"/api/garments/{garment['id']}/reprocess", json={"force_segment": True})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["cutout"] is not None
    assert body["cutout"]["url"].startswith("/files/")


def test_reprocess_segment_failure_clears_cutout_but_stays_ready(tmp_path):
    client, _ = make_client(tmp_path, routes={"segmenter": []})
    garment = import_one(client, category="top")
    resp = client.post(f"/api/garments/{garment['id']}/reprocess", json={"force_segment": True})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["cutout"] is None


# ---------- 搭配 ----------

def test_create_outfit_ready_and_file_download(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client)
    resp = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment["id"]]})
    assert resp.status_code == 202, resp.text
    outfit = resp.json()
    assert outfit["status"] == "ready"
    assert outfit["result"] is not None
    image_url = outfit["result"]["image"]["url"]
    assert image_url.startswith("/files/")

    file_resp = client.get(image_url)
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "image/png"


def test_outfit_garment_not_ready(tmp_path):
    client, _ = make_client(tmp_path, routes={"analyzer": []})
    garment = import_one(client)  # 没有 analyzer，没指定类型 -> failed
    resp = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment["id"]]})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "garment_not_ready"


def test_outfit_nothing_to_try_on(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client, category="shoes")
    assert garment["status"] == "ready"
    resp = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment["id"]]})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "nothing_to_try_on"


def test_turntable_unavailable_then_ready(tmp_path):
    client, _ = make_client(tmp_path)  # 默认 turntable 路由为空
    garment = import_one(client)
    outfit = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment["id"]]}).json()

    resp = client.post(f"/api/outfits/{outfit['id']}/turntable")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "turntable_unavailable"

    client2, _ = make_client(tmp_path, providers={"turntable1": {"type": "fake_turntable"}},
                              routes={"turntable": ["turntable1"]}, db_name="api2.sqlite3")
    garment2 = import_one(client2)
    outfit2 = client2.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment2["id"]]}).json()
    resp2 = client2.post(f"/api/outfits/{outfit2['id']}/turntable")
    assert resp2.status_code == 202
    body = resp2.json()
    assert body["turntable"]["status"] == "ready"
    assert body["turntable"]["video"]["url"].startswith("/files/")


def test_tryon_progress_multi_step(tmp_path):
    client, _ = make_client(tmp_path)
    top = import_one(client, category="top")
    bottom = import_one(client, category="bottom")
    resp = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [top["id"], bottom["id"]]})
    assert resp.status_code == 202
    outfit = resp.json()
    job = client.get(f"/api/jobs/{outfit['job_id']}").json()
    assert job["status"] == "succeeded"
    assert job["progress"]["total"] > 1


# ---------- 任务重试 ----------

def test_retry_failed_job_then_succeed(tmp_path):
    client, runtime = make_client(tmp_path, providers={"tryon1": {"type": "fake_tryon", "fail": True}})
    garment = import_one(client)
    resp = client.post("/api/outfits", json={"preset_id": PRESET_ID, "garment_ids": [garment["id"]]})
    outfit = resp.json()
    assert outfit["status"] == "failed"
    job_id = outfit["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"

    runtime.registry.providers["tryon1"].config["fail"] = False
    retry_resp = client.post(f"/api/jobs/{job_id}/retry")
    assert retry_resp.status_code == 202
    assert retry_resp.json()["status"] == "succeeded"
    assert client.get(f"/api/outfits/{outfit['id']}").json()["status"] == "ready"


def test_retry_non_failed_job_conflict(tmp_path):
    client, _ = make_client(tmp_path)
    garment = import_one(client)
    job_id = garment["job_id"]
    resp = client.post(f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "job_not_failed"


def test_retry_unknown_job_not_found(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.post("/api/jobs/does-not-exist/retry")
    assert resp.status_code == 404


# ---------- 鉴权 ----------

def test_auth_token(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTFIT_API_TOKEN", "secret-token")
    client, runtime = make_client(tmp_path)

    resp = client.get("/api/status")
    assert resp.status_code == 401

    resp = client.get("/api/status", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200

    garment = import_one_with_auth(client, "secret-token")
    sha = garment["image"]["url"].rsplit("/", 1)[-1]

    resp = client.get(f"/files/{sha}")
    assert resp.status_code == 401
    resp = client.get(f"/files/{sha}?token=secret-token")
    assert resp.status_code == 200


def import_one_with_auth(client: TestClient, token: str) -> dict:
    png = make_png_bytes()
    files = [("files", ("a.png", png, "image/png"))]
    resp = client.post("/api/import/images", files=files, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 202, resp.text
    return resp.json()["items"][0]


# ---------- 文件 ----------

def test_files_invalid_sha_and_traversal(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/files/not-a-valid-sha").status_code == 404
    assert client.get("/files/..%2F..%2Fetc%2Fpasswd").status_code == 404


# ---------- 重启恢复 ----------

def test_restart_marks_running_jobs_failed(tmp_path):
    client, runtime = make_client(tmp_path, sync=False)
    db = client.app.state.db
    job = db.create_job(kind="tryon", target_id="fake-outfit-id", user_id="local")
    db.update_job(job["id"], status="running")

    client2, _ = make_client(tmp_path, sync=True)
    job_after = client2.get(f"/api/jobs/{job['id']}").json()
    assert job_after["status"] == "failed"


# ---------- 链接解析 ----------

def test_import_link_success_and_failure(tmp_path, monkeypatch):
    client, runtime = make_client(tmp_path)
    from outfit_core.types import Asset, Product

    def fake_resolve_ok(text, route="resolver"):
        return Product(source_text=text, url="https://item.taobao.com/1", platform="taobao", title="示例商品",
                       price="99.00", images=[Asset(url="https://img.example.com/1.jpg")])

    monkeypatch.setattr(runtime.pipeline, "resolve_link", fake_resolve_ok)
    resp = client.post("/api/import/link", json={"text": "https://item.taobao.com/1 快来看"})
    assert resp.status_code == 200
    body = resp.json()["product"]
    assert body["platform"] == "taobao"
    assert body["images"] == ["https://img.example.com/1.jpg"]

    from outfit_core.registry import AllProvidersFailed

    def fake_resolve_fail(text, route="resolver"):
        raise AllProvidersFailed("resolver", [("generic", "不支持")])

    monkeypatch.setattr(runtime.pipeline, "resolve_link", fake_resolve_fail)
    resp = client.post("/api/import/link", json={"text": "https://item.taobao.com/2"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "resolve_failed"

    resp = client.post("/api/import/link", json={"text": "没有链接的一段文字"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_url"
