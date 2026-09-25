"""叠穿规划：决定先穿什么、后穿什么，并按引擎一次能穿几件拆成步骤。"""
from __future__ import annotations

from .capabilities import TryOnSpec
from .types import Category, Garment, Slot, TryOnOptions


def plan_steps(garments: list[Garment], spec: TryOnSpec, options: TryOnOptions) -> tuple[list[list[Garment]], list[str]]:
    """返回 (步骤列表, 跳过的 garment id)。每个步骤是一次引擎调用要穿的衣服。

    规则：
      - 基础层：连衣裙；或 上衣 + 下装（没有上衣时外套充当上衣）
      - 外层：外套叠在基础层之上（引擎不支持叠穿时跳过）
      - 每个位置只取第一件，其余跳过；连衣裙与上衣/下装冲突时保留连衣裙
      - 一次只能穿一件的引擎：tuck=in 先上衣后下装（下装压住上衣下摆），否则先下装后上衣
    """
    skipped: list[str] = []
    picked: dict[str, Garment] = {}
    for g in garments:
        role = {Category.dress: "dress", Category.top: "top", Category.outer: "outer",
                Category.bottom: "lower", Category.skirt: "lower"}.get(g.category)
        if role is None or g.slot not in spec.slots or role in picked:
            skipped.append(g.id)
            continue
        picked[role] = g

    if "dress" in picked:
        for role in ("top", "lower"):
            if role in picked:
                skipped.append(picked.pop(role).id)

    outer = picked.pop("outer", None)
    if outer and "top" not in picked and "dress" not in picked:
        picked["top"] = outer          # 只有外套时，外套就是上衣
        outer = None

    if "dress" in picked:
        base = [picked["dress"]]
    elif options.tuck == "in":
        base = [g for g in (picked.get("top"), picked.get("lower")) if g]
    else:
        base = [g for g in (picked.get("lower"), picked.get("top")) if g]

    steps = _chunk(base, spec.max_garments_per_call)
    if outer:
        if spec.supports_layering and steps:
            steps.append([outer])
        else:
            skipped.append(outer.id)
    return steps, skipped


def _chunk(items: list[Garment], size: int) -> list[list[Garment]]:
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def slots_of(garments: list[Garment]) -> set[Slot]:
    return {g.slot for g in garments if g.slot}
