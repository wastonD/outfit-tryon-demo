# 改动声明（Apache-2.0 第 4(b) 条要求）

这个目录是 [fashn-AI/fashn-vton-1.5](https://github.com/fashn-AI/fashn-vton-1.5)
（Apache-2.0，Copyright 2025 FASHN AI）的本地分支，pin 在 commit
`7c0f10af3f91ad4048fe9729c470a13ef905d25a`。`LICENSE` 文件原样保留自上游仓库。

## 改动内容
- **去掉了 FashnHumanParser**：上游默认在 `TryOnPipeline.__init__` 里加载它，并在每次推理时调用，
  用它的分割结果生成 inpainting 掩码。它的推理代码来源不明确，权重继承自 NVIDIA SegFormer 的许可证，
  **只能非商用**，和本项目的商用目标冲突（详见仓库根目录 `LICENSES.md`）。
  - `pipeline.py`：删掉了 `_setup_hp_model`、`self.hp_model.predict(...)` 调用、`segmentation_free` 参数
    （现在行为永远等价于上游的 `segmentation_free=True`）。
  - `preprocessing/agnostic.py`：`create_clothing_agnostic_image` / `create_garment_image` 改成直接返回
    原图的空操作，不再需要 `fashn_human_parser` 提供的标签常量。
  - 没有拷贝上游的 `preprocessing/masks.py`：那些函数只被人体分割相关的掩码逻辑用到，现在没有调用方了。
- **未改动**：`tryon_mmdit.py`（TryOnModel 本体，Apache-2.0）、`dwpose/`（DWPose 姿态估计，Apache-2.0，
  另见该目录 `__init__.py` 里对 IDEA-Research/DWPose 的引用）、`preprocessing/transforms.py`、`utils/`。

## 影响
- `garment_photo_type="model"`（服装图是模特上身图）在上游会用分割结果把服装从模特身上抠出来；
  这个分支里没有这一步，所以只支持已经抠好的服装图（`"flat-lay"`，本项目默认路径：先过 BiRefNet
  抠图，见 `../birefnet.py`，步骤 3）。直接传模特上身图会得到较差的效果，不会报错。
- person 图不做任何身体分割，等价于上游的 `segmentation_free=True`：不限制服装体积，更好保留体型，
  这也是上游文档推荐的默认模式，不是妥协。
