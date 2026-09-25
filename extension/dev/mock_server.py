"""插件开发用的假服务器，只用 Python 标准库。

实现 GET /api/status 和 POST /api/import/images，按真实后端接口的格式返回，
收到请求时把摘要打印到控制台（图片数量、每张是 url 还是 data_uri、source），方便在插件里点"加入衣橱"后确认数据对不对。

用法：
    python extension/dev/mock_server.py [--port 8000] [--token TOKEN]

--token 用来测试插件设置页"测试连接"对 401 的处理：设置后，请求必须带
Authorization: Bearer TOKEN，否则返回 401 unauthorized。
"""
import argparse
import json
import sys
import time
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认编码常不是 UTF-8，避免中文打印乱码
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_handler(token: str | None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # 用下面自己的打印替代默认日志

        def _cors_headers(self):
            origin = self.headers.get("Origin", "*")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "600")

        def _send_json(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str):
            self._send_json(status, {"error": {"code": code, "message": message}})

        def _check_auth(self) -> bool:
            if not token:
                return True
            auth = self.headers.get("Authorization", "")
            return auth == f"Bearer {token}"

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/api/status"):
                if not self._check_auth():
                    self._error(401, "unauthorized", "令牌不正确")
                    return
                self._send_json(200, _fake_status())
                return
            self._error(404, "not_found", "未知路径")

        def do_POST(self):
            if self.path.startswith("/api/import/images"):
                if not self._check_auth():
                    self._error(401, "unauthorized", "令牌不正确")
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length else b""
                try:
                    data = json.loads(raw.decode("utf-8")) if raw else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._error(400, "bad_request", "请求体不是合法 JSON")
                    return

                images = data.get("images") or []
                if not images:
                    self._error(400, "no_images", "没有图片")
                    return

                source = data.get("source") or {}
                print("\n收到 /api/import/images：")
                print(f"  图片数量：{len(images)}")
                for i, img in enumerate(images):
                    kind = "data_uri" if img.get("data_uri") else "url"
                    ref = img.get("data_uri", "")[:40] + "..." if kind == "data_uri" else img.get("url")
                    print(f"    [{i}] {kind}: {ref} category={img.get('category')}")
                print(f"  source: url={source.get('url')} title={source.get('title')} "
                      f"platform={source.get('platform')} price={source.get('price')}")

                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                items = []
                for img in images:
                    items.append({
                        "id": uuid.uuid4().hex[:12],
                        "status": "pending",
                        "error": None,
                        "category": img.get("category"),
                        "category_source": "user" if img.get("category") else None,
                        "analysis": None,
                        "image": {"url": "/files/" + uuid.uuid4().hex, "mime": "image/jpeg"},
                        "cutout": None,
                        "source": {
                            "url": source.get("url"),
                            "title": source.get("title"),
                            "platform": source.get("platform"),
                            "price": source.get("price"),
                            "image_url": img.get("url"),
                        },
                        "job_id": uuid.uuid4().hex[:12],
                        "created_at": now,
                    })
                self._send_json(202, {"items": items})
                return
            self._error(404, "not_found", "未知路径")

    return Handler


def _fake_status() -> dict:
    return {
        "providers": {},
        "routes": {},
        "warnings": ["这是插件开发用的假服务器 mock_server.py，不是真正的后端"],
        "features": {"analyzer": False, "tryon": False, "upscale": False, "turntable": False},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default=None, help="设置后要求 Authorization: Bearer <token>")
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), make_handler(args.token))
    print(f"假服务器已启动：http://127.0.0.1:{args.port}"
          + (f"（需要 token={args.token}）" if args.token else "（不需要 token）"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
