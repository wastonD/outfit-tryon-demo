"""各适配器共用的提示词。"""
import json
import re

from outfit_core.capabilities import ProviderError
from outfit_core.types import Category, GarmentAnalysis, Shot

ANALYZE_PROMPT = """你是电商服装图片分析器。判断这张商品图，只输出一行 JSON，不要任何解释、不要 markdown：
{"category": "top|outer|bottom|skirt|dress|shoes|bag|other",
 "layer": "inner|outer|none",
 "shot": "flat_lay|worn_by_model|mannequin|detail|poster|other",
 "tryon_ready": true,
 "color": "主色，不超过6个字",
 "note": "一句话描述款式，不超过30个字"}
说明：
- top 指 T 恤、衬衫、毛衣等贴身穿的上衣；outer 指外套、夹克、开衫、西装、大衣等通常可以脱下、穿在最外层的衣服；
  如果画面里同时能看到内外两层，外面那件（能整件脱下的）是 outer，贴身那件是 top。
- skirt 指半身裙：独立的下装，只覆盖下半身，和裤子一样单穿；dress 指连衣裙或连体衣：上下连为一体、没有独立腰线分割。
- 如果画面里出现不止一件衣服（例如一整套穿搭合影），只描述其中最显眼、占画面面积最大的那一件的
  category/color/note，不要因为多件衣服就返回 other；并在 note 末尾用"，另有…"简短说明画面里还有什么
  （例如"黑色针织开衫，另有白色半裙和短靴"）。
- tryon_ready 表示这张图是否是单件服装、主体清晰、适合直接用于虚拟试穿。
- color 和 note 都用简短中文，不要输出英文或拼音，不要重复 category 已经表达的信息。
- category 只能是上面列出的单个词，禁止像 "top|bottom" 这样用竖线拼出多个候选；拿不准就按"最显眼、
  占画面面积最大"的规则选一个，不要犹豫。"""

TURNTABLE_PROMPT = ("模特在纯色背景前原地缓慢转身一整圈（360度），依次展示正面、侧面、背面，最后回到正面。"
                    "身体保持直立，手臂自然下垂，脚不离地。镜头固定不动，光线不变。"
                    "服装的颜色、图案、版型和面料细节在整个过程中保持一致，不增减任何衣物。")


_LONE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _clean_text(value, max_len=None):
    """去掉孤立 UTF-16 代理项（本地量化模型偶发的字节级 fallback token 可能产生），必要时截断。
    实测所谓"乱码"多是终端显示编码问题，这里只是防御性清洗。"""
    if not isinstance(value, str):
        return value
    cleaned = _LONE_SURROGATE_RE.sub("", value).strip()
    return cleaned[:max_len] if max_len else cleaned


def _first_valid(value, valid_values):
    """模型偶尔会像 "top|bottom" 这样把多个候选拼在一起（照抄了提示词里 schema 的写法），
    即使提示词已经明确禁止。与其整条判定失败退回 other，不如拆开取第一个合法值。"""
    if not isinstance(value, str):
        return None
    if value in valid_values:
        return value
    for part in re.split(r"[|,，/]", value):
        part = part.strip()
        if part in valid_values:
            return part
    return None


def parse_analysis(text: str) -> GarmentAnalysis:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ProviderError(f"识别结果不是 JSON：{(text or '')[:200]}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ProviderError(f"识别结果 JSON 解析失败：{e}") from None
    category = _first_valid(data.get("category"), Category._value2member_map_)
    shot = _first_valid(data.get("shot"), Shot._value2member_map_)
    layer = _first_valid(data.get("layer"), ("inner", "outer", "none"))
    return GarmentAnalysis(
        category=category or Category.other,
        shot=shot or Shot.other,
        layer=layer or "none",
        tryon_ready=bool(data.get("tryon_ready")),
        color=_clean_text(data.get("color"), max_len=12),
        note=_clean_text(data.get("note"), max_len=60))
