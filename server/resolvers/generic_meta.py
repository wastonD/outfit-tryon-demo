"""通用网页解析：读取 schema.org Product 和 Open Graph 标签。适用于大部分海外电商和独立站。

国内主要平台（淘宝、京东等）通常会被登录页或验证页拦截，应在路由中排在联盟接口之后作为兜底，
或通过配置 skip_platforms 直接跳过。
"""
import html
import json
import re

from outfit_core.capabilities import LinkResolver, Provider, ProviderError, ProviderInfo
from outfit_core.http import HttpError, request
from outfit_core.registry import register
from outfit_core.types import Asset, Product

from .platforms import AFFILIATE_PLATFORMS, detect_platform, extract_url


def _meta(page: str, prop: str) -> str | None:
    p = re.escape(prop)
    m = (re.search(rf'<meta[^>]+(?:property|name)=["\']{p}["\'][^>]*content=["\']([^"\']+)', page, re.I)
         or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{p}["\']', page, re.I))
    return html.unescape(m.group(1)) if m else None


def _json_ld_products(page: str) -> list[dict]:
    found = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            stack.extend(item.get("@graph", []))
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types or "ProductGroup" in types:
                found.append(item)
    return found


def parse_page(page: str) -> dict:
    out = {"title": None, "price": None, "images": [], "method": None}
    products = _json_ld_products(page)
    if products:
        p = products[0]
        imgs = p.get("image") or []
        imgs = imgs if isinstance(imgs, list) else [imgs]
        out["images"] = [i.get("url") if isinstance(i, dict) else i for i in imgs if i]
        out["title"] = p.get("name")
        offers = p.get("offers") or {}
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict) and (offers.get("price") or offers.get("lowPrice")):
            out["price"] = f"{offers.get('price') or offers.get('lowPrice')} {offers.get('priceCurrency', '')}".strip()
        out["method"] = "schema.org"
    if not out["images"] and (og := _meta(page, "og:image")):
        out["images"], out["method"] = [og], "open_graph"
    out["title"] = out["title"] or _meta(page, "og:title")
    out["price"] = out["price"] or _meta(page, "product:price:amount")
    return out


@register("generic_meta")
class GenericMetaResolver(Provider, LinkResolver):
    """配置：skip_platforms（列表，默认空）、max_images（默认 10）、timeout。"""
    default_info = ProviderInfo(license="自研", cost_per_call=0)

    def can_handle(self, text: str) -> bool:
        url = extract_url(text)
        return bool(url) and detect_platform(url) not in self.config.get("skip_platforms", [])

    def resolve(self, text: str) -> Product:
        url = extract_url(text)
        platform = detect_platform(url)
        try:
            resp, content = request("GET", url, {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                                    timeout=self.config.get("timeout", 20), raw=True)
        except (HttpError, OSError) as e:
            raise ProviderError(f"网页读取失败：{e}") from None
        final_url = resp.geturl()
        page = content.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        if platform == "other":
            platform = detect_platform(final_url)
        parsed = parse_page(page)
        if not parsed["images"]:
            hint = f"，建议使用{AFFILIATE_PLATFORMS[platform]}接口" if platform in AFFILIATE_PLATFORMS else ""
            raise ProviderError(f"页面中没有读到商品图（可能是登录页、验证页或前端动态渲染）{hint}")
        return Product(source_text=text, url=final_url, platform=platform, title=parsed["title"],
                       price=parsed["price"], resolver=self.name,
                       images=[Asset(url=u) for u in parsed["images"][: self.config.get("max_images", 10)]])
