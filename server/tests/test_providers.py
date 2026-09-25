import base64
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from outfit_core.registry import Registry
from outfit_core.types import BodySpec, Category, Garment, TryOnOptions
from providers._prompts import parse_analysis
from providers.kling import make_jwt
from resolvers.generic_meta import parse_page
from resolvers.platforms import detect_platform, extract_url

from .conftest import PNG, fake_image


def test_extract_url_from_share_text():
    text = "【淘宝】限时 https://e.tb.cn/h.AbC123?tk=xyz 「连衣裙」点击链接直接打开"
    assert extract_url(text) == "https://e.tb.cn/h.AbC123?tk=xyz"
    assert detect_platform(extract_url(text)) == "taobao"
    assert detect_platform("https://item.jd.com/1.html") == "jd"


def test_parse_page_json_ld_and_open_graph():
    ld = {"@context": "https://schema.org", "@graph": [{"@type": "Product", "name": "Linen Shirt",
          "image": ["https://x/1.jpg", {"url": "https://x/2.jpg"}], "offers": {"price": "39.9", "priceCurrency": "USD"}}]}
    page = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    assert parse_page(page) == {"title": "Linen Shirt", "price": "39.9 USD",
                                "images": ["https://x/1.jpg", "https://x/2.jpg"], "method": "schema.org"}
    og = '<meta content="https://x/og.jpg" property="og:image"><meta property="og:title" content="Tee &amp; Co">'
    assert parse_page(og)["images"] == ["https://x/og.jpg"] and parse_page(og)["title"] == "Tee & Co"


def test_parse_analysis_tolerates_noise():
    a = parse_analysis('好的：```json\n{"category":"jacket","shot":"worn_by_model","layer":"outer","tryon_ready":true}\n```')
    assert a.category == Category.other and a.shot.value == "worn_by_model" and a.layer == "outer"


def test_parse_analysis_picks_first_option_when_model_hedges():
    # Qwen3-VL-4B 实测偶尔会照抄提示词 schema 的写法，输出 "top|bottom" 这种拼接多个候选的 category
    # （尤其是上衣+裤子同框、面积接近的图片），而不是严格二选一。与其整条判定失败退回 other，
    # 不如拆开取第一个合法值（实测复现过）。
    a = parse_analysis('{"category":"top|bottom","shot":"worn_by_model","layer":"outer","tryon_ready":true}')
    assert a.category == Category.top


def test_parse_analysis_strips_lone_surrogates():
    # 模拟本地量化模型偶发的字节级 fallback token：解析结果里混入孤立 UTF-16 代理项（不是合法字符）。
    color = "\ud8f2黑色"
    note = "短袖\udcabT恤"
    broken = ('{"category":"top","shot":"flat_lay","layer":"none","tryon_ready":true,'
              f'"color":"{color}","note":"{note}"}}')
    a = parse_analysis(broken)
    assert a.category == Category.top
    assert a.color == "黑色"
    assert a.note == "短袖T恤"
    assert all(not (0xd800 <= ord(c) <= 0xdfff) for c in a.color + a.note)


def test_kling_jwt_signature():
    token = make_jwt("ak", "sk", now=1_000_000)
    header, payload, sig = token.split(".")
    expected = hmac.new(b"sk", f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(sig + "==") == expected
    assert json.loads(base64.urlsafe_b64decode(payload + "==")) == {"iss": "ak", "exp": 1_001_800, "nbf": 999_995}


def test_remote_worker_protocol_roundtrip(store):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"ok": True, "capabilities": {"tryon": {}}})

        def do_POST(self):
            received.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self._send({"image": {"data_uri": "data:image/png;base64," + base64.b64encode(PNG + b"out").decode()}})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = Registry.from_config({"providers": {"w": {"type": "remote_worker", "capabilities": ["tryon"],
                                                        "url": f"http://127.0.0.1:{server.server_port}"}},
                                    "routes": {"tryon": ["w"]}}, store)
        worker = reg.providers["w"]
        assert worker.available() == (True, "ok")
        garment = Garment(image=fake_image(store, "coat"), category=Category.outer)
        out = worker.tryon(fake_image(store, "person"), [garment], TryOnOptions(tuck="in"))
        assert store.read_bytes(out) == PNG + b"out"
        assert received["garments"][0]["category"] == "outer"
        assert received["person"]["data_uri"].startswith("data:image/png;base64,")
        assert received["options"]["tuck"] == "in"
    finally:
        server.shutdown()


def test_openai_compat_vlm_against_local_server(store):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"data": [{"id": "qwen3-vl-4b"}]})

        def do_POST(self):
            seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            answer = '{"category":"skirt","layer":"none","shot":"flat_lay","tryon_ready":true,"color":"黑"}'
            self._send({"choices": [{"message": {"content": answer}}]})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        reg = Registry.from_config({"providers": {"v": {"type": "openai_compat_vlm", "base_url": base,
                                                        "model": "qwen3-vl-4b"}}}, store)
        vlm = reg.providers["v"]
        assert vlm.available() == (True, "ok")
        analysis = vlm.analyze(fake_image(store, "skirt"))
        assert analysis.category == Category.skirt and analysis.color == "黑"
        image_part = seen["messages"][0]["content"][0]["image_url"]["url"]
        assert seen["model"] == "qwen3-vl-4b" and image_part.startswith("data:image/png;base64,")
    finally:
        server.shutdown()
    offline = Registry.from_config({"providers": {"v": {"type": "openai_compat_vlm", "base_url": "http://127.0.0.1:9/v1",
                                                        "model": "m"}}}, store).providers["v"]
    assert offline.available()[0] is False


def test_openai_compat_vlm_resizes_large_image(store):
    from io import BytesIO

    from PIL import Image

    big = BytesIO()
    Image.new("RGB", (2000, 3000), (10, 20, 30)).save(big, format="PNG")
    image = store.put_bytes(big.getvalue(), "image/png")

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"data": [{"id": "qwen3-vl-4b"}]})

        def do_POST(self):
            seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            answer = '{"category":"top","layer":"none","shot":"flat_lay","tryon_ready":true}'
            self._send({"choices": [{"message": {"content": answer}}]})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        reg = Registry.from_config({"providers": {"v": {"type": "openai_compat_vlm", "base_url": base,
                                                        "model": "qwen3-vl-4b", "resize_long_edge": 768}}}, store)
        reg.providers["v"].analyze(image)
        image_url = seen["messages"][0]["content"][0]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        sent_bytes = base64.b64decode(image_url.split(",", 1)[1])
        with Image.open(BytesIO(sent_bytes)) as sent:
            assert max(sent.size) <= 768
    finally:
        server.shutdown()


def test_openai_compat_vlm_keeps_small_image_untouched(store):
    from io import BytesIO

    from PIL import Image

    small = BytesIO()
    Image.new("RGB", (200, 300), (10, 20, 30)).save(small, format="PNG")
    image = store.put_bytes(small.getvalue(), "image/png")

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"data": [{"id": "qwen3-vl-4b"}]})

        def do_POST(self):
            seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            answer = '{"category":"top","layer":"none","shot":"flat_lay","tryon_ready":true}'
            self._send({"choices": [{"message": {"content": answer}}]})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        reg = Registry.from_config({"providers": {"v": {"type": "openai_compat_vlm", "base_url": base,
                                                        "model": "qwen3-vl-4b", "resize_long_edge": 768}}}, store)
        reg.providers["v"].analyze(image)
        image_url = seen["messages"][0]["content"][0]["image_url"]["url"]
        # 小图不需要缩放，原样透传（PNG 不重新编码成 JPEG）
        assert image_url.startswith("data:image/png;base64,")
        assert base64.b64decode(image_url.split(",", 1)[1]) == small.getvalue()
    finally:
        server.shutdown()


def test_aliyun_wan_t2i_async_protocol(store, monkeypatch):
    # wanx2.1-t2i-turbo（默认模型）走旧协议：POST 创建任务 → 轮询 GET 拿结果，见 aliyun.py 的 T2I_SYNC_MODELS 判断。
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            seen["path"] = self.path
            seen["async_header"] = self.headers.get("X-DashScope-Async")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send({"output": {"task_status": "PENDING", "task_id": "task-1"}})

        def do_GET(self):
            if self.path.startswith("/api/v1/tasks/"):
                self._send({"output": {"task_status": "SUCCEEDED",
                                       "results": [{"url": f"http://127.0.0.1:{self.server.server_port}/out.png"}]}})
                return
            data = PNG + b"model"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = Registry.from_config({"providers": {"t2i": {"type": "aliyun_wan_t2i",
                                                           "base_url": f"http://127.0.0.1:{server.server_port}"}}},
                                   store)
        provider = reg.providers["t2i"]
        assert provider.available() == (True, "ok")
        assert provider.info.cost_per_call == 0.14
        body = BodySpec(gender="female", height="medium", build="regular", skin="light")
        asset = provider.generate_model(body, "测试提示词", seed=42)
        assert store.read_bytes(asset) == PNG + b"model"
        assert seen["path"] == "/api/v1/services/aigc/text2image/image-synthesis"
        assert seen["async_header"] == "enable"
        assert seen["body"]["model"] == "wanx2.1-t2i-turbo"
        assert seen["body"]["input"]["prompt"] == "测试提示词"
        assert seen["body"]["parameters"]["size"] == "576*864"
        assert seen["body"]["parameters"]["seed"] == 42
        assert "negative_prompt" in seen["body"]["parameters"]
    finally:
        server.shutdown()


def test_aliyun_wan_t2i_sync_protocol(store, monkeypatch):
    # wan2.6-t2i 走新协议：一次 POST 直接拿结果，不轮询。
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps({"output": {"finished": True, "choices": [{"message": {"content": [
                {"type": "image", "image": f"http://127.0.0.1:{self.server.server_port}/out.png"}]}}]}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            data = PNG + b"sync"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = Registry.from_config({"providers": {"t2i": {"type": "aliyun_wan_t2i", "model": "wan2.6-t2i",
                                                           "base_url": f"http://127.0.0.1:{server.server_port}"}}},
                                   store)
        provider = reg.providers["t2i"]
        assert provider.info.cost_per_call == 0.20
        body = BodySpec(gender="male", height="medium", build="slim", skin="dark")
        asset = provider.generate_model(body, "test prompt")
        assert store.read_bytes(asset) == PNG + b"sync"
        assert seen["path"] == "/api/v1/services/aigc/multimodal-generation/generation"
        assert seen["body"]["input"]["messages"][0]["content"][0]["text"] == "test prompt"
        assert "seed" not in seen["body"]["parameters"]
    finally:
        server.shutdown()


def test_remote_worker_reports_missing_capability(store):
    reg = Registry.from_config({"providers": {"w": {"type": "remote_worker", "capabilities": ["tryon"],
                                                    "url": "http://127.0.0.1:9"}}}, store)
    ok, why = reg.providers["w"].available()
    assert not ok and "无法连接" in why
