"""把 bench 结果渲染成单个 HTML 报告（图片用相对路径引用 data/assets）。"""
import html
import os
from pathlib import Path

esc = lambda s: html.escape("" if s is None else str(s))

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--ok:#2f7d4f;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1f;--text:#ededed;--muted:#a0a0a5;--line:#333;--ok:#6cc58f;--bad:#ef7a72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 80px}h1{font-size:26px;margin:0 0 4px}h2{font-size:20px;margin:36px 0 12px}
h3{font-size:16px;margin:0 0 8px}.muted{color:var(--muted);font-size:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;word-break:break-all}
.ok{color:var(--ok)}.bad{color:var(--bad)}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:12px}
.thumbs{display:flex;gap:8px;flex-wrap:wrap}.thumbs figure{margin:0;width:120px}.thumbs img{width:120px;height:150px;object-fit:contain;background:var(--bg);border-radius:6px}
figcaption{font-size:12px;color:var(--muted)}.result img{width:100%;border-radius:8px;background:var(--bg);cursor:zoom-in}
.pill{display:inline-block;padding:0 8px;border-radius:99px;background:var(--bg);border:1px solid var(--line);font-size:12px;margin:2px 4px 2px 0}
.spin{position:relative;overflow:hidden;border-radius:8px;background:#000;touch-action:none;cursor:ew-resize;aspect-ratio:3/4}
.spin video{width:100%;height:100%;object-fit:contain;pointer-events:none}
.spin .hint{position:absolute;left:8px;bottom:8px;color:#fff;background:#0008;padding:2px 8px;border-radius:99px;font-size:12px}
dialog{border:0;padding:0;background:transparent;max-width:95vw}dialog img{max-width:95vw;max-height:92vh}dialog::backdrop{background:#000c}
"""

JS = """
document.querySelectorAll('.spin').forEach(box=>{
  const v=box.querySelector('video');let drag=false,x=0,s=1;
  const zoom=n=>{s=Math.min(4,Math.max(1,n));v.style.transform=`scale(${s})`};
  box.onpointerdown=e=>{drag=true;x=e.clientX;box.setPointerCapture(e.pointerId);v.pause()};
  box.onpointermove=e=>{if(!drag||!v.duration)return;const d=(e.clientX-x)/box.clientWidth*v.duration;x=e.clientX;
    v.currentTime=((v.currentTime+d)%v.duration+v.duration)%v.duration};
  box.onpointerup=()=>drag=false;
  box.addEventListener('wheel',e=>{e.preventDefault();zoom(s*(e.deltaY<0?1.15:0.87))},{passive:false});
  box.ondblclick=()=>zoom(s>1?1:2);
});
const dlg=document.querySelector('dialog');
document.querySelectorAll('.result img').forEach(i=>i.onclick=()=>{dlg.querySelector('img').src=i.src;dlg.showModal()});
dlg.onclick=()=>dlg.close();
"""


def _src(asset: dict | None, base: Path) -> str:
    if not asset:
        return ""
    if asset.get("path"):
        return Path(os.path.relpath(asset["path"], base)).as_posix()
    return asset.get("url") or ""


def _links(rows):
    if not rows:
        return ""
    body = []
    for r in rows:
        if r["ok"]:
            p = r["product"]
            thumb = f"<img src='{esc(p['images'][0]['url'])}' style='height:60px'>" if p["images"] else ""
            body.append(f"<tr><td class=ok>成功</td><td>{esc(p['platform'])}</td><td>{esc(p['title'])}<br>"
                        f"{esc(p['price'])} · {len(p['images'])} 张图</td><td>{thumb}</td><td class=muted>{esc(r['input'])}</td></tr>")
        else:
            body.append(f"<tr><td class=bad>失败</td><td></td><td>{esc(r['error'])}</td><td></td>"
                        f"<td class=muted>{esc(r['input'])}</td></tr>")
    ok = sum(r["ok"] for r in rows)
    return (f"<h2>链接解析</h2><p class=muted>成功 {ok}/{len(rows)}</p><div class=card><table>"
            "<tr><th>结果</th><th>平台</th><th>详情</th><th>图</th><th>输入</th></tr>" + "".join(body) + "</table></div>")


def _case(c, base):
    parts = [f"<div class=card><h3>{esc(c['name'])}</h3>"]
    parts += [f"<p class=bad>{esc(e)}</p>" for e in c["errors"]]
    thumbs = [f"<figure><img src='{esc(_src(c.get('model'), base))}'><figcaption>模特</figcaption></figure>"]
    for g in c["garments"]:
        a = g.get("analysis") or {}
        img = g.get("cutout") or g["image"]
        thumbs.append(f"<figure><img src='{esc(_src(img, base))}'><figcaption>{esc(g['category'])}"
                      f"{' · ' + esc(a.get('shot')) if a else ''}<br>{esc(a.get('note') or '')}</figcaption></figure>")
    parts.append("<div class=thumbs>" + "".join(thumbs) + "</div><div class=grid>")

    for t in c["tryon"]:
        title = f"{esc(t['provider'])} <span class=muted>{esc(t['route'])}</span>"
        if not t["ok"]:
            parts.append(f"<div><h3>{title}</h3><p class=bad>{esc(t['error'][:500])}</p></div>")
            continue
        steps = "".join(f"<span class=pill>第{i + 1}步 {s['metrics']['seconds']}s</span>" for i, s in enumerate(t["steps"]))
        cost = "未知" if t["total_cost"] is None else f"¥{t['total_cost']:.3f}"
        extra = " · 缓存" if t["cached"] else ""
        skipped = f"<br><span class=muted>跳过 {len(t['skipped'])} 件不支持的服装</span>" if t["skipped"] else ""
        mids = "".join(f"<img src='{esc(_src(s['image'], base))}' style='width:32%'>" for s in t["steps"][:-1])
        parts.append(f"<div class=result><h3>{title}</h3><img src='{esc(_src(t['image'], base))}'>"
                     f"<p>耗时 <b>{t['total_seconds']}s</b> · 费用 <b>{cost}</b>{extra}<br>{steps}{skipped}</p>"
                     + (f"<p class=muted>中间步骤</p>{mids}" if mids else "") + "</div>")

    for t in c["turntable"]:
        if not t["ok"]:
            parts.append(f"<div><h3>360° {esc(t['provider'])}</h3><p class=bad>{esc(t['error'][:500])}</p></div>")
            continue
        secs = sum(m["seconds"] for m in t["metrics"])
        parts.append(f"<div><h3>360° {esc(t['provider'])}</h3><div class=spin>"
                     f"<video src='{esc(_src(t['video'], base))}' muted playsinline preload=auto></video>"
                     f"<span class=hint>左右拖动旋转 · 滚轮缩放 · 双击放大</span></div>"
                     f"<p>耗时 <b>{secs:.1f}s</b> · 首帧来自 {esc(t['source'])}</p></div>")
    parts.append("</div></div>")
    return "".join(parts)


def write_report(results: dict, run_dir: Path) -> Path:
    cases = "".join(_case(c, run_dir) for c in results["cases"])
    page = ("<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'><title>模型对比报告</title>"
            f"<style>{CSS}</style></head><body><main><h1>模型对比报告</h1>"
            f"<p class=muted>{esc(results['time'])} · 点击图片放大</p>{_links(results['links'])}"
            + (f"<h2>试衣与 360°</h2>{cases}" if cases else "")
            + f"</main><dialog><img></dialog><script>{JS}</script></body></html>")
    out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out
