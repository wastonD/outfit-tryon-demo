# worker：本地 GPU 推理进程

独立的 Python 3.12 虚拟环境，跑在同一台机器（以后可以换成租用的 GPU 服务器，只改 `server` 配置里的 `url`）。
对外只暴露 `server/providers/remote_worker.py` 里约定的 HTTP 协议，`server` 不知道模型具体怎么跑。

## 启动
```bash
worker\.venv\Scripts\python -m app.main       # 默认 127.0.0.1:9001
curl http://127.0.0.1:9001/v1/health
```

`server` 侧把 `config/providers.yaml` 里的 `local-gpu` 指向这个地址即可（`providers.example.yaml` 已经这样配好）。

## 结构
| 文件 | 内容 | 状态 |
|---|---|---|
| `app/main.py` | FastAPI 入口，实现 `/v1/health` 和五个能力端点 | ✅ 步骤 1 |
| `app/gpu.py` | `Engine` 基类 + `ModelManager`：GPU 锁（串行）、按显存预算按需加载/卸载（LRU 淘汰） | ✅ 步骤 1 |
| `app/schemas.py` / `app/imageio.py` | 请求/响应模型（协议里的 `Ref`）、Ref↔PIL.Image 转换 | ✅ 步骤 1 |
| `app/config.py` | `.env` 读取（`WORKER_PORT`、`WORKER_VRAM_BUDGET_GB` 等） | ✅ 步骤 1 |
| `app/engines/fashn_vton.py` + `app/vendor/fashn_vton/` | tryon：FASHN VTON v1.5，去掉了人体分割，见 vendor 目录里的 NOTICE.md | ✅ 步骤 2 |
| `app/engines/birefnet.py` | segmenter：BiRefNet（MIT，transformers trust_remote_code 加载） | ✅ 步骤 3 |
| `app/engines/realesrgan.py` | upscaler：Real-ESRGAN x4plus（BSD-3-Clause，spandrel 加载） | ✅ 步骤 3 |
| `app/engines/` 其余 | turntable(Wan2.2) | 步骤 5 |

## 接入一个新引擎
1. 在 `app/engines/xxx.py` 写一个类，继承 `gpu.Engine`：
   ```python
   class MyEngine(Engine):
       name = "my-engine"
       vram_gb = 4.0          # ModelManager 按这个数字决定要不要先卸载别的引擎
       def load(self): ...    # 把权重搬进显存
       def unload(self): ...  # 释放显存（del + torch.cuda.empty_cache()）
       def run(self, ...): ...  # 具体推理，和 capability 对应的端点签名一致
   ```
2. 在 `app/engines/__init__.py` 的 `register_all()` 里 `manager.register("tryon", MyEngine())`。
3. `ModelManager` 保证：同一时刻只有一个请求在用 GPU；已加载引擎的 `vram_gb` 总和超预算时，自动卸载最久未用的那个。

## 显存预算
`WORKER_VRAM_BUDGET_GB`（默认 8）。RTX 4060 笔记本版 8GB 显存，一次只放一个大模型（FASHN VTON 或 Wan2.2），
小模型（BiRefNet、Real-ESRGAN）可能和当前大模型共存，具体取决于各自 `vram_gb` 估算是否超预算。

## 和 llama.cpp 的关系（analyzer，步骤 4，已完成）
Qwen3-VL-4B 通过 llama.cpp 自带的 OpenAI 兼容 server 独立运行（默认 `127.0.0.1:8080`），
`server` 直接用 `openai_compat_vlm` 适配器调用，**不经过这个 worker 进程**，所以 `analyzer` 能力不在这里实现，
也不受 `ModelManager` 的 GPU 锁和显存预算管理。

```powershell
pwsh worker\scripts\start_llama_server.ps1     # 或直接用 worker/llama_cpp/llama-server.exe，见脚本内容
curl http://127.0.0.1:8080/v1/models
```

- 权重：`worker/models/qwen3vl/`（`Qwen3VL-4B-Instruct-Q4_K_M.gguf` + `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`），
  来自 huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF，Apache-2.0。
- 二进制：`worker/llama_cpp/`（llama.cpp 官方 release 的 Windows CPU 版，MIT）。
- **默认只用 CPU**（`-ngl 0`）：worker 里的 FASHN VTON 会占约 7GB 显存，这个进程常驻加载、不受
  `ModelManager` 管理，同时开 GPU 版容易和 FASHN 抢显存爆掉。CPU 跑一次分类调用大约 1 分钟，
  对"识别服装类型"这种低频、非实时的任务够用。想换 GPU：重新下载 CUDA 版
  `llama-*-bin-win-cuda-*.zip` + 对应的 `cudart-llama-bin-win-cuda-*.zip`，把 `-ngl 0` 改成 `-ngl 99`，
  并注意避免和试衣任务同时跑。
