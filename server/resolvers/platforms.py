"""从分享文本中提取链接、识别电商平台。"""
import re
import urllib.parse

PLATFORMS = {
    "taobao": ("taobao.com", "tmall.com", "tb.cn", "alicdn.com"),
    "jd": ("jd.com", "3.cn", "jd.hk"),
    "pdd": ("pinduoduo.com", "yangkeduo.com"),
    "douyin": ("douyin.com", "iesdouyin.com"),
    "vip": ("vip.com",),
    "shein": ("shein.com",),
    "shopee": ("shopee.",),
    "lazada": ("lazada.",),
    "zalora": ("zalora.",),
    "amazon": ("amazon.", "amzn."),
    "uniqlo": ("uniqlo.com",),
    "zara": ("zara.com",),
    "hm": ("hm.com",),
}
AFFILIATE_PLATFORMS = {"taobao": "淘宝联盟", "jd": "京东联盟", "pdd": "多多进宝", "douyin": "抖音精选联盟"}


def extract_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s，。、】）)\"'<>]+", text or "")
    return match.group(0) if match else None


def detect_platform(url: str | None) -> str:
    if not url:
        return "unknown"
    host = urllib.parse.urlparse(url).netloc.lower()
    for name, keys in PLATFORMS.items():
        if any(k in host for k in keys):
            return name
    return "other"
