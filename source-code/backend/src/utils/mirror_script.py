"""
GitHub 加速脚本镜像集成（油猴脚本：Github Enhancement - High Speed Download）

每次测速前拉取脚本最新版本：
  - 用 ETag/If-None-Match 做增量检查（304 直接用缓存，避免重复下载）
  - 脚本 @version 变化或内容变化 → 重新解析镜像列表并更新缓存
  - 从脚本 SOURCES 配置中提取所有「完整前缀形式」的加速域名
    （形如 https://{mirror}/https://github.com）

镜像来源优先级：脚本最新列表 > 本地缓存 > 内置兜底列表。
"""

import json
import re
import time
from pathlib import Path
from typing import Callable, List, Optional

from backend.src.utils.logger import app_logger as logger

SCRIPT_URL = ("https://scriptcat.org/scripts/code/7474/"
              "Github%20Enhancement%20-%20High%20Speed%20Download%20(%E4%BC%98%E5%8C%96%E7%89%88).user.js")

CACHE_NAME = "gh_script_mirrors.json"

# 完整前缀形式：https://{domain}/https://github.com
_DOMAIN_RE = re.compile(r"https://([A-Za-z0-9.-]+)/https://github\.com")
_VERSION_RE = re.compile(r"@version\s+([\d.]+)")

# 占位/无效域名
_IGNORE = {"example.com", "github.com", "www.github.com"}


def _cache_path() -> Path:
    try:
        from backend.src.utils.paths import get_app_data_dir
        base = Path(get_app_data_dir())
    except Exception:
        base = Path.home() / ".comfynexus"
    d = base / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / CACHE_NAME


def _load_cache() -> dict:
    try:
        p = _cache_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(data: dict):
    try:
        _cache_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[MirrorScript] 缓存写入失败: {e}")


def parse_mirrors(script_text: str) -> List[str]:
    """从脚本源码解析镜像域名（去重保序，过滤占位域名）"""
    seen, out = set(), []
    for m in _DOMAIN_RE.finditer(script_text):
        d = m.group(1).lower().strip(".")
        if d in _IGNORE or d in seen:
            continue
        # 只保留看起来是加速站的域名（gb-proxy 系列/短域名等）
        seen.add(d)
        out.append(d)
    return out


_MEM = {"at": 0.0, "mirrors": []}
_MEM_TTL = 300  # 5 分钟内复用，避免频繁请求脚本站


def fetch_script_mirrors(log_fn: Optional[Callable[[str], None]] = None,
                         timeout: int = 15) -> List[str]:
    """
    拉取（或读缓存）脚本镜像列表。

    逻辑：
      1. 有缓存 → 带 If-None-Match 请求；304 → 用缓存
      2. 200 → 解析 @version 与镜像域名 → 版本/列表变化则更新缓存并记录日志
      3. 网络失败 → 用缓存；无缓存 → 返回空（调用方用内置兜底列表）

    Returns:
        List[str]: 镜像域名列表（可能为空）
    """
    log = log_fn or (lambda m: logger.info(m))
    now = time.time()
    if _MEM["mirrors"] and (now - _MEM["at"]) < _MEM_TTL:
        return list(_MEM["mirrors"])
    cache = _load_cache()

    try:
        import requests
        headers = {"User-Agent": "ComfyNexus/1.0"}
        if cache.get("etag"):
            headers["If-None-Match"] = cache["etag"]
        if cache.get("lastModified"):
            headers["If-Modified-Since"] = cache["lastModified"]

        r = requests.get(SCRIPT_URL, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 304 and cache.get("mirrors"):
            log(f"加速脚本无更新（v{cache.get('version', '?')}，{len(cache['mirrors'])} 个镜像）")
            _MEM["at"], _MEM["mirrors"] = now, list(cache["mirrors"])
            return list(cache["mirrors"])

        if r.status_code == 200:
            text = r.text
            mirrors = parse_mirrors(text)
            vm = _VERSION_RE.search(text)
            version = vm.group(1) if vm else "?"
            old_version = cache.get("version")
            if mirrors:
                changed = (version != old_version) or (mirrors != cache.get("mirrors"))
                _save_cache({
                    "version": version,
                    "mirrors": mirrors,
                    "etag": r.headers.get("ETag"),
                    "lastModified": r.headers.get("Last-Modified"),
                    "fetchedAt": time.time(),
                })
                if changed:
                    log(f"加速脚本已更新至 v{version}，镜像列表刷新（{len(mirrors)} 个）")
                else:
                    log(f"加速脚本 v{version}，镜像 {len(mirrors)} 个")
                _MEM["at"], _MEM["mirrors"] = now, list(mirrors)
                return mirrors
    except Exception as e:
        logger.debug(f"[MirrorScript] 拉取失败: {e}")

    if cache.get("mirrors"):
        log(f"加速脚本拉取失败，使用缓存镜像（v{cache.get('version', '?')}，{len(cache['mirrors'])} 个）")
        _MEM["at"], _MEM["mirrors"] = now, list(cache["mirrors"])
        return list(cache["mirrors"])
    return []
