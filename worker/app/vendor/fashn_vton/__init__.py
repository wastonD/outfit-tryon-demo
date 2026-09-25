"""FASHN VTON v1.5 —— 去掉了非商用人体分割模型的本地分支，见 NOTICE.md。"""

__version__ = "1.5.0-nohp"

from .pipeline import PipelineOutput, TryOnPipeline
from .tryon_mmdit import TryOnModel

__all__ = [
    "TryOnPipeline",
    "PipelineOutput",
    "TryOnModel",
    "__version__",
]
