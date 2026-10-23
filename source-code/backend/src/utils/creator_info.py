"""
创作者信息抓取（推荐关注）

自定义添加创作者时，自动抓取一次头像 / 昵称 / 简介，并**落盘缓存**：
- 头像：走 icon_cache 的本地缓存（一次下载，之后直接读本地）
- 简介等文本：写入 creator_store 的 JSON，列表删除时随之删除

这样避免"每次打开页面都重新下载一遍"。
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from backend.src.utils.logger import app_logger as logger

_TIMEOUT = (6, 12)
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 文本信息缓存：<app_data>/config/creator_info.json  → {url: {name, description, avatar, ts}}
_MAX_AGE_DAYS = 30


def _info_file() -> Path:
    try:
        from backend.src.utils.paths import get_app_data_dir
        base = Path(get_app_data_dir())
    except Exception:
        base = Path.home() / ".comfynexus"
    d = base / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d / "creator_info.json"


def _load_cache() -> Dict:
    try:
        p = _info_file()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(data: Dict):
    try:
        _info_file().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[CreatorInfo] 缓存写入失败: {e}")


def _cache_get(url: str) -> Optional[Dict]:
    data = _load_cache()
    item = data.get(url)
    if not item:
        return None
    try:
        if (time.time() - float(item.get("ts", 0))) / 86400 > _MAX_AGE_DAYS:
            return None
        return item
    except Exception:
        return None


def _cache_put(url: str, item: Dict):
    data = _load_cache()
    item = dict(item)
    item["ts"] = time.time()
    data[url] = item
    _save_cache(data)


def _bilibili_info(mid: str) -> Dict:
    """B 站空间：头像 / 昵称 / 签名"""
    out: Dict = {}
    try:
        import requests
        # 头像（直接给的是头像原图，尺寸大；用 @160 缩略）
        try:
            r = requests.get(
                f"https://api.bilibili.com/x/web-interface/card?mid={mid}&photo=false",
                headers={"User-Agent": _UA}, timeout=_TIMEOUT)
            if r.status_code == 200:
                js = r.json()
                card = (js.get("data") or {}).get("card") or {}
                if card.get("face"):
                    out["avatar"] = card["face"]
                if card.get("name"):
                    out["name"] = card["name"]
                sign = card.get("sign")
                if sign:
                    out["description"] = sign.strip()
        except Exception:
            pass
    except Exception:
        pass
    return out


def _generic_info(url: str) -> Dict:
    """通用网页：og:image / og:description / <title>"""
    out: Dict = {}
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT,
                         allow_redirects=True)
        if r.status_code != 200:
            return out
        html = r.text[:200000]
        m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            desc = re.sub(r"\s+", " ", m.group(1)).strip()
            if desc:
                out["description"] = desc[:200]
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            if name:
                out["name"] = name[:80]
    except Exception:
        pass
    return out


def fetch(url: str) -> Dict:
    """
    抓取创作者信息（头像 / 名称 / 简介），头像落盘缓存。

    Returns:
        dict: {name, description, avatar}（avatar 为本地 /icons/xxx 路径）
    """
    url = (url or "").strip()
    if not url:
        return {}

    cached = _cache_get(url)
    if cached:
        return cached

    info: Dict = {}
    host = urlparse(url).netloc.lower()
    mid = ""
    if "space.bilibili.com" in host:
        m = re.search(r"/(\d+)", url)
        if m:
            mid = m.group(1)
    if mid:
        info.update(_bilibili_info(mid))
    if not info:
        info.update(_generic_info(url))

    # 头像统一走 icon_cache：下载一次 → 落盘 → 返回本地路径
    avatar = info.get("avatar")
    if avatar:
        try:
            from backend.src.utils import icon_cache
            local = icon_cache.get_or_fetch(avatar)
            if local:
                info["avatar"] = f"/icons/{Path(local).name}"
            else:
                info.pop("avatar", None)
        except Exception as e:
            logger.debug(f"[CreatorInfo] 头像缓存失败: {e}")

    if info:
        _cache_put(url, info)
    return info
