"""零依赖的 HTTP 工具（沿用 outfit-poc/common.py）。"""
import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


class HttpError(RuntimeError):
    def __init__(self, status, url, detail):
        super().__init__(f"HTTP {status} {url}\n{detail}")
        self.status = status


def request(method, url, headers=None, body=None, timeout=120, raw=False):
    """body 为 dict/list 时按 JSON 发送，为 bytes 时原样发送。raw=True 返回 (响应, 字节)。"""
    headers = dict(headers or {})
    data = None
    if isinstance(body, (dict, list)):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, bytes):
        data = body
    headers.setdefault("User-Agent", UA)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            if raw:
                return resp, content
            text = content.decode("utf-8", errors="replace")
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, url, e.read().decode("utf-8", errors="replace")[:800]) from None


def multipart(fields, file_field, file_path):
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    path = Path(file_path)
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def fetch_bytes(url, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get_content_type()


def poll(fetch, is_done, interval=4, timeout=900, label="任务"):
    """反复调用 fetch()，直到 is_done(结果) 为真；is_done 可以抛异常表示失败。"""
    start = time.time()
    while True:
        result = fetch()
        if is_done(result):
            return result
        if time.time() - start > timeout:
            raise TimeoutError(f"{label} 超时（{timeout}s）")
        time.sleep(interval)
