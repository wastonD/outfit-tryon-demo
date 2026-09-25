"""批量生成预设模特候选图，调用阿里云万相文生图 API。

用法（在 server 目录下）：
  python -m bench.gen_presets --dry-run                      # 只算数量和预计费用，不调用 API
  python -m bench.gen_presets --samples                      # 先出 4 张跨体型样张，确认风格/文案后再批量生成
  python -m bench.gen_presets                                 # 默认 18 个体型（身高固定 medium）× 3 候选
  python -m bench.gen_presets --heights short,medium,tall     # 扩展到 54 个体型
  python -m bench.gen_presets --only female-medium-regular-light,male-medium-slim-dark   # 只生成指定体型（调试用）
  python -m bench.gen_presets --lang en                       # 用英文提示词模板（默认中文）

断点续跑：candidates 目录下已存在的候选图不会重新生成，避免重复花钱；重新生成某一张时手动删除对应文件即可。
生成的候选图落在 server/data/presets_candidates/，同目录下的 gallery.html 是挑选页（网格排列，标注
preset_id、候选编号、单张费用和累计费用），发给用户确认后再手动挑选写入 server/presets/。
"""
import argparse
from pathlib import Path

from outfit_core.bootstrap import SERVER_ROOT, build, setup_console
from outfit_core.types import BodySpec

CANDIDATES_DIR = SERVER_ROOT / "data" / "presets_candidates"
DEFAULT_N_CANDIDATES = 3

GENDERS = ["female", "male"]
BUILDS = ["slim", "regular", "plus"]
SKINS = ["light", "medium", "dark"]

GENDER_ZH = {"female": "女性", "male": "男性"}
BUILD_ZH = {"slim": "身材明显纤瘦、四肢细长", "regular": "身材标准匀称", "plus": "身材丰满偏胖、体态圆润"}
# 第二版样张里 dark 只出到偏黄小麦色、medium 偏白，全是东亚面孔——肤色措辞加强并绑定面孔特征。
SKIN_ZH = {"light": "白皙的浅色皮肤", "medium": "健康的小麦色偏古铜皮肤", "dark": "非常深的黑棕色皮肤、非裔面孔"}
# 男女贴身衣分开写死，避免模型自由发挥出连体衣/泳衣（样张里女性两张都跑成了连体款式）。
# 男款第一版样张用"紧身平角短裤"触发了内容审核 DataInspectionFailed，且上衣和短裤连成了一件
# 紧身连体衣、隐约勾出身体轮廓——改成宽松版型，并在提示词里明确"两件独立衣物"防止再融合。
OUTFIT_ZH = {
    "female": "穿着分体两件式的贴身纯浅灰色运动内衣和高腰紧身短裤，上衣下摆在腰部以上，露出腰腹",
    "male": "上身穿浅灰色宽松圆领短袖T恤（下摆盖过腰部，材质有厚度不贴身），"
           "下身穿浅灰色宽松运动短裤（裤长到大腿中部，裤型宽松不勒身）；T恤和短裤是两件独立的衣物",
}

GENDER_EN = {"female": "female", "male": "male"}
BUILD_EN = {"slim": "noticeably slim and lean, with slender limbs", "regular": "average, well-proportioned",
           "plus": "plus-size, full-figured with a rounded silhouette"}
SKIN_EN = {"light": "fair light", "medium": "healthy tan, bronzed", "dark": "very deep dark-brown skin, African features"}
OUTFIT_EN = {
    "female": "wearing a two-piece set: a fitted plain light-gray sports bra and high-waist fitted shorts, "
             "with the bra hem above the waist, exposing the midriff",
    "male": "wearing two separate loose-fitting garments: a plain light-gray crew-neck short-sleeve T-shirt "
           "with a thick non-clingy fabric and a hem below the waist, and plain light-gray loose athletic "
           "shorts reaching mid-thigh with a relaxed, non-tight fit",
}

# 提示词模板（中英文各一版，--lang 选择用哪版；生成 4 张样张后由用户挑选效果更好的一版）。
# 负面提示词在 providers/aliyun.py 的 T2I_DEFAULT_NEGATIVE_PROMPT 里配置（可在 providers.yaml 覆盖）。
# 注意：正向提示词里绝不能出现"手镯/项链/不要X"这类否定式列举——扩散模型对否定几乎无感，
# 词本身反而是召唤物（上一版样张 4/4 出现手链就是这个原因）；否定项只放 negative prompt。
PROMPT_ZH = (
    "电商服装摄影，一位成年{gender}模特的全身照，{build}，{skin}，"
    "以电商服装模特的自然松弛姿态正面面对镜头站立，肩膀放松下沉，"
    "双臂自然垂放并略微离开身体，双腿略微分开，重心自然，"
    "神态放松，表情自然柔和；"
    "头顶到脚底完整入镜，人物居中，四周留有均匀空白，固定机位相同拍摄距离；"
    "{outfit}，露出手臂和小腿，脚上是简洁的白色一脚蹬布鞋；"
    "双手空无一物，手腕、脖颈和耳朵裸露干净；"
    "纯浅灰色无缝背景，背景明亮度均匀无渐变，影棚均匀柔光；"
    "相貌自然普通的虚构人物；高清写实摄影"
)
PROMPT_EN = (
    "E-commerce apparel photography, full-body shot of an adult {gender} model, {build} build, {skin} skin, "
    "standing facing the camera in the relaxed, at-ease posture of an e-commerce fashion model, "
    "shoulders dropped and relaxed, arms hanging naturally slightly away from the body, "
    "feet slightly apart, natural weight distribution, calm soft facial expression; "
    "head-to-toe fully in frame, figure centered with even margins, fixed camera at consistent distance; "
    "{outfit}, bare arms and lower legs, simple plain white slip-on shoes; "
    "empty hands, bare clean wrists, neck and ears; "
    "seamless plain light-gray studio background with uniform brightness and no gradient, even soft lighting; "
    "an ordinary-looking fictional person; realistic high-resolution photograph"
)

# --samples 用：故意跨性别/体型/肤色挑几个组合，够看出提示词风格，不用等 18 个全生成完再确认。
SAMPLE_BODIES = [
    BodySpec(gender="female", height="medium", build="regular", skin="light"),
    BodySpec(gender="male", height="medium", build="regular", skin="light"),
    BodySpec(gender="female", height="medium", build="plus", skin="dark"),
    BodySpec(gender="male", height="medium", build="slim", skin="medium"),
]


def build_prompt(body: BodySpec, lang: str) -> str:
    if lang == "en":
        return PROMPT_EN.format(gender=GENDER_EN[body.gender], build=BUILD_EN[body.build],
                               skin=SKIN_EN[body.skin], outfit=OUTFIT_EN[body.gender])
    return PROMPT_ZH.format(gender=GENDER_ZH[body.gender], build=BUILD_ZH[body.build],
                           skin=SKIN_ZH[body.skin], outfit=OUTFIT_ZH[body.gender])


def all_bodies(heights: list[str]) -> list[BodySpec]:
    return [BodySpec(gender=g, height=h, build=b, skin=s)
           for h in heights for g in GENDERS for b in BUILDS for s in SKINS]


def candidate_path(preset_id: str, index: int) -> Path:
    return CANDIDATES_DIR / f"{preset_id}-{index}.png"


def write_gallery(bodies: list[BodySpec], n_candidates: int, cost_per_call: float | None, out_path: Path):
    cumulative = 0.0
    cards = []
    for body in bodies:
        for index in range(1, n_candidates + 1):
            path = candidate_path(body.preset_id, index)
            if not path.exists():
                continue
            if cost_per_call is not None:
                cumulative += cost_per_call
            cost_html = f"{cost_per_call} 元 · 累计 {round(cumulative, 2)} 元" if cost_per_call is not None else "单价未知"
            cards.append(
                f'<div class="card"><img src="{path.name}" loading="lazy">'
                f'<div class="label">{body.preset_id}<br>候选 #{index}</div>'
                f'<div class="cost">{cost_html}</div></div>')
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>预设模特候选</title>
<style>
body {{ font-family: system-ui, "Microsoft YaHei", sans-serif; background: #111; color: #eee; margin: 0; padding: 16px; }}
h1 {{ font-size: 18px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }}
.card {{ background: #1c1c1c; border-radius: 8px; padding: 8px; text-align: center; }}
.card img {{ width: 100%; border-radius: 4px; background: #333; aspect-ratio: 2/3; object-fit: cover; }}
.label {{ margin-top: 6px; font-size: 13px; }}
.cost {{ font-size: 12px; color: #999; }}
</style></head>
<body><h1>预设模特候选（共 {len(cards)} 张）</h1><div class="grid">{"".join(cards)}</div></body></html>"""
    out_path.write_text(html, encoding="utf-8")


def main():
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--heights", default="medium", help="逗号分隔，默认只生成 medium（18 个体型）")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh")
    ap.add_argument("--n-candidates", type=int, default=DEFAULT_N_CANDIDATES)
    ap.add_argument("--only", help="只生成指定 preset_id（逗号分隔），调试用")
    ap.add_argument("--samples", action="store_true", help="只生成 4 张跨体型样张确认风格，忽略 --heights/--only")
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--dry-run", action="store_true", help="只打印数量和预计费用，不调用 API、不联网")
    args = ap.parse_args()

    rt = build(args.config)
    cost_per_call = None
    for name in rt.registry.routes.get("model_generator") or []:
        provider = rt.registry.providers.get(name)
        if provider and provider.available()[0]:
            cost_per_call = provider.info.cost_per_call
            break

    if args.samples:
        bodies, n_candidates = SAMPLE_BODIES, 1
    else:
        heights = [h.strip() for h in args.heights.split(",") if h.strip()]
        bodies = all_bodies(heights)
        if args.only:
            wanted = set(args.only.split(","))
            bodies = [b for b in bodies if b.preset_id in wanted]
        n_candidates = args.n_candidates

    todo = [(b, i) for b in bodies for i in range(1, n_candidates + 1) if not candidate_path(b.preset_id, i).exists()]
    total = len(bodies) * n_candidates
    price_note = f"{cost_per_call} 元/张" if cost_per_call is not None else "单价未知（模型不可用或未配置）"
    print(f"体型数：{len(bodies)}，每个体型 {n_candidates} 张候选，共需 {total} 张；"
         f"已存在 {total - len(todo)} 张（跳过，不重复花钱），还需新生成 {len(todo)} 张，单价 {price_note}")
    if cost_per_call is not None:
        print(f"预计新增花费：约 {round(cost_per_call * len(todo), 2)} 元")
    if args.dry_run:
        return
    if not todo:
        print("没有需要新生成的候选，直接刷新挑选页")
    else:
        CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
        spent = 0.0
        for body, index in todo:
            prompt = build_prompt(body, args.lang)
            seed = args.seed_base + abs(hash((body.preset_id, index))) % 100000
            asset, metrics = rt.pipeline.generate_model(body, prompt, seed=seed)
            candidate_path(body.preset_id, index).write_bytes(Path(asset.path).read_bytes())
            cost = next((m.cost for m in metrics if m.cost is not None), None)
            spent += cost or 0
            print(f"[{body.preset_id} #{index}] 完成，本次累计 {round(spent, 2)} 元")

    gallery = CANDIDATES_DIR / "gallery.html"
    write_gallery(bodies, n_candidates, cost_per_call, gallery)
    print(f"挑选页：{gallery}")


if __name__ == "__main__":
    main()
