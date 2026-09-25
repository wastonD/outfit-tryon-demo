# 启动 llama.cpp 的 OpenAI 兼容 server，跑 Qwen3-VL-4B（服装识别，analyzer 能力）。
# 默认 CPU 推理（-ngl 0）：worker 里的 FASHN VTON 试衣要占约 7GB 显存，这个进程不受
# worker 的 GPU 锁管理，同时跑 GPU 版容易和 FASHN 抢显存爆掉。想用 GPU 就把 -ngl 0 改大，
# 但要注意别和试衣同时跑，且需要重新下载 CUDA 版的 llama-server（见 worker/README.md）。
#
# 不传 -t/-c，让 llama.cpp 自动选择：H 任务在 32 逻辑核的机器上实测过，自动选择的线程数
# （本机是 24）比手动设成 16 或 32 都快（32 反而比 24 慢一倍多，猜测是超线程/内存带宽争用）；
# 手动把 -c 从自动算出来的默认值（本机 95744）调小到 4096 同一张图反而更慢，没有必要改。真正
# 决定耗时的是发给模型的图片分辨率——见 server/providers/openai_compat_vlm.py 的 resize_long_edge。
#
# 用法：pwsh worker\scripts\start_llama_server.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

& "$root\llama_cpp\llama-server.exe" `
  --model "$root\models\qwen3vl\Qwen3VL-4B-Instruct-Q4_K_M.gguf" `
  --mmproj "$root\models\qwen3vl\mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf" `
  --alias qwen3-vl-4b `
  --host 127.0.0.1 --port 8080 `
  -ngl 0
