# 组件许可证清单

每次新增或升级模型都要更新本表。**代码、权重、训练数据、依赖模型要分别核对**，任何一层不可商用，该组件都不可商用。
在 `config/providers.yaml` 中用 `info.commercial_ok` 标记；路由里使用了不可商用的实现，启动时会发出警告。

| 组件 | 用途 | 代码 | 权重 | 训练数据 / 依赖 | 可商用 | 核对日期 |
|---|---|---|---|---|---|---|
| FASHN VTON v1.5 | 试衣 | Apache-2.0 | Apache-2.0 | DWPose（Apache-2.0）、YOLOX（Apache-2.0） | ✅ | 2026-09-17 |
| FASHN Human Parser | FASHN 自带的人体分割 | — | 继承 NVIDIA SegFormer 许可证 | — | ❌ **仅限非商用，已移除** — 代码里不 import、不下载、不加载这个模型，详见 `worker/app/vendor/fashn_vton/NOTICE.md` | 2026-09-17 |
| Wan2.2 TI2V-5B | 360° 视频 | Apache-2.0 | Apache-2.0 | 待核对 | ✅（待复核） | 2026-09-17 |
| Z-Image-Turbo | 生成预设模特 | — | — | — | ❌ **未采用** — 需下载本地权重（10GB+），只为一次性生成不划算，改用阿里云万相文生图 API，见下方"云服务" | 2026-09-18 |
| Qwen3-VL-4B-Instruct | 服装识别 | Apache-2.0 | Apache-2.0（huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF，官方 GGUF） | — | ✅（其他尺寸需单独核对） | 2026-09-17 |
| BiRefNet | 抠图 | MIT | MIT（huggingface.co/ZhengPeng7/BiRefNet，同仓库同许可证） | — | ✅ | 2026-09-17 |
| SAM 2 | 抠图 | Apache-2.0 | Apache-2.0 | — | 未使用——BiRefNet 单独效果已经够用，没有接入 | — |
| Real-ESRGAN | 超分辨率 | BSD-3-Clause | BSD-3-Clause（github.com/xinntao/Real-ESRGAN 官方 release，同仓库同许可证） | — | ✅ | 2026-09-17 |
| llama.cpp | 本地运行视觉大模型 | MIT | — | — | ✅ | — |
| pillow-heif | 导入 heic 图片（server） | BSD-3-Clause | — | wheel 内打包了 libheif、libde265（均为 LGPL，具体版本待核对；只用于解码），作为可替换的第三方包引入，LGPL 允许商用 | ✅（待复核 LGPL 版本） | 2026-09-18 |

Real-ESRGAN 用 [spandrel](https://github.com/chaiNNer-org/spandrel)（MIT，架构实现代码继承原模型许可证）加载官方 `.pth` 权重，
没用官方 `realesrgan` pip 包——它依赖的 `basicsr` 和现在的 torchvision 版本不兼容。

## 明确不用于产品的模型（仅可本地参考）
CatVTON、IDM-VTON、OOTDiffusion、StableVITON（CC BY-NC-SA 4.0）；用 VITON-HD（CC BY-NC）或 DressCode（仅限学术）训练的权重；SMPL 人体模型（商用需另购授权）。

## 云服务
阿里云百炼、可灵等按各自服务协议执行，重点确认：生成结果的权利归属、是否允许商用、平台是否使用上传数据训练模型。

| 服务 | 用途 | 生成日期 | 结论 |
|---|---|---|---|
| 阿里云百炼万相文生图（wanx2.1-t2i-turbo，见 `providers/aliyun.py` 的 `aliyun_wan_t2i`） | 生成预设模特底图 | 2026-09-18～09-19 | 《阿里云百炼服务协议》第 7.5 条：若用户对上传内容（文生图场景即提示词本身）具有合法知识产权，合成内容的知识产权归用户，但是否构成知识产权由用户自行判断，阿里云不承诺；第 4.6 条禁止用生成内容训练与百炼竞争的模型（不影响本场景）；未发现禁止商用的条款。已设置 `watermark: false`（不加"AI生成"水印，避免污染试衣输入图）——按 4.3.1 条，生成式内容对外发布时依法应显著标识为非真实信息，产品侧需要在模特图使用场景另行加标识或说明，不能仅靠不加水印来规避标注义务。协议全文：https://terms.alicdn.com/legal-agreement/terms/common_platform_service/20230728213935489/20230728213935489.html |
