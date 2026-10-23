"""
常用工具 / 推荐关注 的图标缓存

解决的问题：
1. **持久化**：图标（favicon / logo）只下载一次，落盘到本地缓存目录，
   之后每次打开页面都直接读本地文件，不再重复请求网络。
2. **可用性**：前端 <img> 直连各类图标服务（iowen / duckduckgo / google）在国内
   经常整体不可达，导致图标显示成地球占位。这里改由后端抓取：
   站点自身 favicon → 页面 <link rel=icon> 声明 → 站点 logo 图片，
   全部失败才回退到公共图标服务（已实测 iowen/duckduckgo 在部分网络下不通）。
3. **删除同步**：从列表删除某项时，调用 remove_cached_icon 一并清掉本地缓存。

缓存目录：<运行时数据目录>/cache/icons/<host>.<ext>
"""

import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from backend.src.utils.logger import app_logger as logger

_lock = threading.Lock()
# host → 本地文件名（内存索引，避免每次扫目录）
_index: Dict[str, str] = {}
_index_loaded = False

# 缓存有效期（天）：图标一般不会变，长期复用；超过则重新抓取
_MAX_AGE_DAYS = 30
# 抓取超时
_TIMEOUT = (6, 12)

# 常见图片类型 → 扩展名
_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/bmp": ".bmp",
}


def cache_dir() -> Path:
    """图标缓存目录：<运行时数据>/cache/icons"""
    try:
        from backend.src.utils.paths import get_project_root
        d = Path(get_project_root()) / "cache" / "icons"
    except Exception:
        d = Path.home() / ".comfynexus" / "cache" / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_index():
    global _index_loaded
    if _index_loaded:
        return
    with _lock:
        if _index_loaded:
            return
        try:
            for f in cache_dir().iterdir():
                if f.is_file():
                    _index[f.stem] = f.name
        except Exception:
            pass
        _index_loaded = True


def _host_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _safe_name(url: str) -> str:
    """把 URL 映射为安全的缓存文件名"""
    host = _host_of(url) or "unknown"
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r"[^a-z0-9\-_.]", "_", host)[:48]
    return f"{safe}_{digest}"


def cached_path(url: str) -> Optional[Path]:
    """查询已缓存的图标文件（存在且未过期则返回路径）"""
    if not url:
        return None
    _load_index()
    name = _index.get(_safe_name(url))
    if not name:
        return None
    p = cache_dir() / name
    if not p.exists():
        return None
    try:
        age_days = (time.time() - p.stat().st_mtime) / 86400
        if age_days > _MAX_AGE_DAYS:
            p.unlink(missing_ok=True)
            _index.pop(_safe_name(url), None)
            return None
    except OSError:
        return None
    return p


def _save(url: str, data: bytes, ext: str) -> Optional[Path]:
    """保存图标到缓存目录"""
    if not data or len(data) < 64:  # 过滤空/占位响应
        return None
    if not ext or ext not in (".png", ".jpg", ".gif", ".webp", ".svg", ".ico", ".bmp"):
        ext = ".png"
    name = _safe_name(url) + ext
    p = cache_dir() / name
    try:
        p.write_bytes(data)
    except OSError as e:
        logger.debug(f"[IconCache] 写入失败: {e}")
        return None
    with _lock:
        _index[_safe_name(url)] = name
    return p


def _fetch(url: str) -> Optional[Tuple[bytes, str]]:
    """下载单个 URL，返回 (内容, 扩展名)"""
    try:
        import requests
    except Exception:
        return None
    try:
        r = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0 Safari/537.36"),
                "Accept": ("image/avif,image/webp,image/apng,image/svg+xml,"
                           "image/*,*/*;q=0.8"),
            },
            allow_redirects=True,
        )
        if r.status_code != 200:
            return None
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        data = r.content
        if not data:
            return None
        # 纯文本响应（很多站点的 404 页面返回 HTML）→ 不是图片
        if ctype.startswith("text/") or (not ctype and data[:20].lstrip()[:1] == b"<"):
            return None
        ext = _EXT_BY_MIME.get(ctype, "")
        if not ext:
            # 按内容魔数判断（顺序：SVG 文本 → PNG → JPEG → GIF → WEBP → ICO）
            head = data[:512].lstrip()
            if head[:4] == b"\x89PNG":
                ext = ".png"
            elif head[:3] == b"\xff\xd8\xff":
                ext = ".jpg"
            elif head[:6] in (b"GIF87a", b"GIF89a"):
                ext = ".gif"
            elif head[:4] == b"RIFF" and data[8:12] == b"WEBP":
                ext = ".webp"
            elif head[:4] == b"\x00\x00\x01\x00":
                ext = ".ico"
            elif b"<svg" in head.lower() or head[:5] == b"<?xml":
                ext = ".svg"
        return (data, ext)
    except Exception:
        return None


def _page_icon_candidates(url: str) -> List[str]:
    """抓取页面 HTML，从 <link rel="icon"> 声明里取真实图标地址"""
    out: List[str] = []
    try:
        import requests
        from urllib.parse import urljoin
        r = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return out
        html = r.text[:200000]
        for m in re.finditer(
            r'<link[^>]+rel=["\']?[^"\']*icon[^"\']*["\']?[^>]*>', html, re.I
        ):
            tag = m.group(0)
            href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
            if not href:
                continue
            icon_url = urljoin(r.url, href.group(1).strip())
            if icon_url.startswith("data:"):
                continue
            if icon_url not in out:
                out.append(icon_url)
            if len(out) >= 4:
                break
    except Exception:
        pass
    return out


def _candidate_urls(url: str) -> List[str]:
    """
    图标候选地址（按可靠性排序）。

    顺序刻意把「站点自身」放前面：公共图标服务（iowen/duckduckgo/google）
    在国内常整体不可达，放在前面会白白浪费请求。
    """
    host = _host_of(url)
    cands: List[str] = []
    if host:
        cands.append(f"https://{host}/favicon.ico")
        cands.append(f"https://{host}/favicon.png")
        cands.append(f"https://{host}/favicon.svg")
    return cands


def _is_direct_image(url: str) -> bool:
    """判断 URL 是否直接指向图片文件（.svg/.png/.jpg/.ico/.webp/.gif）"""
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return path.endswith((".svg", ".png", ".jpg", ".jpeg", ".ico", ".webp", ".gif", ".bmp"))


def get_or_fetch(url: str, use_page_icons: bool = True) -> Optional[str]:
    """
    获取图标（优先本地缓存），返回**本地文件路径**（字符串）。

    流程：本地缓存 → 直链图片本身 → 站点 favicon → 页面声明的 icon → 公共图标服务。
    全部失败返回 None（前端回退到首字母占位）。
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    p = cached_path(url)
    if p:
        return str(p)

    # 0) 直链图片（显式指定的 logo 地址）：直接下载，不要被站点 favicon 抢先
    if _is_direct_image(url):
        got = _fetch(url)
        if got:
            saved = _save(url, got[0], got[1])
            if saved:
                logger.info(f"[IconCache] 已缓存图标(直链): {url} → {saved.name}")
                return str(saved)

    # 1) 站点自身 favicon
    for cand in _candidate_urls(url):
        got = _fetch(cand)
        if got:
            saved = _save(url, got[0], got[1])
            if saved:
                logger.info(f"[IconCache] 已缓存图标: {url} → {saved.name}")
                return str(saved)

    # 2) 页面 <link rel=icon> 声明（长 logo / 深路径 favicon 靠这条拿到）
    if use_page_icons:
        for cand in _page_icon_candidates(url):
            got = _fetch(cand)
            if got:
                saved = _save(url, got[0], got[1])
                if saved:
                    logger.info(f"[IconCache] 已缓存图标(页面声明): {url} → {saved.name}")
                    return str(saved)

    # 3) 公共图标服务兜底
    host = _host_of(url)
    if host:
        for svc in (
            f"https://api.iowen.cn/favicon/{host}.png",
            f"https://icons.duckduckgo.com/ip3/{host}.ico",
            f"https://www.google.com/s2/favicons?domain={host}&sz=64",
        ):
            got = _fetch(svc)
            if got:
                saved = _save(url, got[0], got[1])
                if saved:
                    logger.info(f"[IconCache] 已缓存图标(公共服务): {url} → {saved.name}")
                    return str(saved)
    return None


def remove_cached_icon(url: str) -> bool:
    """
    删除某个 URL 的本地缓存（列表删除时同步清理）。

    支持两种入参：
    - 原始 URL（http/https）→ 按 URL 映射的缓存键删除
    - 本地路径（/icons/xxx.png）→ 直接按文件名删除
    """
    if not url:
        return False
    # 本地路径形式：直接删文件
    if url.startswith("/icons/") or url.startswith("icons/"):
        name = url.rsplit("/", 1)[-1]
        if not name or "/" in name or "\\" in name:
            return False
        p = cache_dir() / name
        try:
            if p.exists():
                p.unlink()
                logger.info(f"[IconCache] 已删除缓存图标: {name}")
                return True
        except OSError:
            return False
        return False
    _load_index()
    key = _safe_name(url)
    with _lock:
        name = _index.pop(key, None)
    if not name:
        return False
    p = cache_dir() / name
    try:
        p.unlink(missing_ok=True)
        logger.info(f"[IconCache] 已删除缓存图标: {name}")
        return True
    except OSError:
        return False
