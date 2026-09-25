"""网页托管的安全回归测试：web/dist 存在时，兜底路由不能读到目录以外的文件。"""
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from outfit_core.bootstrap import SERVER_ROOT
from outfit_core.registry import Registry
from outfit_core.bootstrap import Runtime
from outfit_core.pipeline import OutfitPipeline

WEB_DIST = SERVER_ROOT.parent / "web" / "dist"


@pytest.fixture
def client(store, cache, tmp_path):
    if not (WEB_DIST / "index.html").exists():
        pytest.skip("web/dist 不存在，先在 web/ 下运行 npm run build")
    reg = Registry.from_config({"providers": {}, "routes": {}}, store)
    runtime = Runtime(reg, store, cache, OutfitPipeline(reg, store, cache))
    return TestClient(create_app(runtime=runtime, db_path=tmp_path / "api.sqlite3", sync=True))


@pytest.mark.parametrize("path", ["/..%2F..%2Fserver%2Fpyproject.toml", "/%2e%2e/%2e%2e/server/pyproject.toml",
                                  "/..%2F..%2Fserver%2F.env.example"])
def test_spa_fallback_blocks_traversal(client, path):
    r = client.get(path)
    assert "outfit-server" not in r.text and "DASHSCOPE" not in r.text
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", ["/api/not-exist", "/files/..%2Fx", "/files"])
def test_unknown_api_and_files_paths_are_json_404(client, path):
    r = client.get(path)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
