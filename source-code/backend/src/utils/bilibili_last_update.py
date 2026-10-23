"""
Bilibili UP 主最新投稿时间查询（预取 + 持久缓存 + 多轮退避重试）

实测结论（2026-10）：
- x/space/wbi/arc/search、web-dynamic feed 风控极严（-352），不可用
- x/series/recArchivesByKeywords 免登录可用，但对频率极敏感：
  3 秒间隔连续 13 个 mid 成功率仅 3/13
- 成功策略：**慢速轮次收敛**——每轮间隔 5 秒，失败者进入下一轮
  （最多 6 轮，轮间指数退避），结果持久化到磁盘缓存，重启不丢

架构：
- get_cached(mid)：前端卡片立即可读（磁盘缓存，可能为 None）
- prefetch_all(mids)：后台线程启动预取循环，逐轮收敛
- get_status()：{done, total, running} 供前端显示进度
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from backend.src.utils.logger import app_logger as logger
from backend.src.utils.paths import get_cache_dir

ARC_URL = "https://api.bilibili.com/x/series/recArchivesByKeywords"
REQUEST_INTERVAL = 5.0          # 轮内请求间隔
ROUND_BACKOFF = [5, 20, 45, 90, 180, 300]   # 轮间退避（秒）
POSITIVE_TTL = 6 * 3600         # 成功缓存 6 小时
NEGATIVE_TTL = 10 * 60          # 失败负缓存 10 分钟（轮内跳过）

_lock = threading.Lock()
_session: Optional[requests.Session] = None
_cache_file: Optional[Path] = None
_results: Dict[str, Dict] = {}          # mid -> {"pubdate": Optional[int], "ts": float}
_prefetch_thread: Optional[threading.Thread] = None
_status = {"done": 0, "total": 0, "running": False}


def _session_get():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
        _session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://space.bilibili.com/",
        })
        # 预热 buvid3 cookie，降低风控概率
        try:
            _session.get("https://www.bilibili.com", timeout=(10, 15))
        except Exception:
            pass
    return _session


def _cache_path() -> Path:
    global _cache_file
    if _cache_file is None:
        _cache_file = get_cache_dir() / "bilibili_updates.json"
    return _cache_file


def _load_cache():
    global _results
    if _results:
        return
    try:
        p = _cache_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            _results = {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception as e:
        logger.debug(f"[bilibili] 缓存读取失败: {e}")
        _results = {}


def _save_cache():
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_results, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[bilibili] 缓存写入失败: {e}")


def _query_one(mid: str) -> Optional[int]:
    """优先 API（快）；失败回退 Edge headless 抓视频列表页（用户思路：看最新视频的相对时间）"""
    pubdate = _query_via_api(mid)
    if pubdate:
        return pubdate
    return _query_via_page(mid)


def _query_via_api(mid: str) -> Optional[int]:
    try:
        r = _session_get().get(
            ARC_URL, params={"mid": mid, "keywords": "", "ps": "1"},
            timeout=(10, 20),
        )
        data = r.json().get("data") or {}
        archives = data.get("archives") or []
        if not archives:
            return None
        pubdate = archives[0].get("pubdate")
        return int(pubdate) if pubdate else None
    except Exception:
        return None


_REL_TIME = __import__("re").compile(
    r"<span[^>]*>(\d+)\s*(分钟前|小时前|天前)</span>|<span[^>]*>刚刚</span>"
)


def _query_via_page(mid: str) -> Optional[int]:
    """
    用户思路：打开 UP 主视频列表页（space.bilibili.com/{mid}/upload/video），
    从第一条视频下方的「X分钟前/小时前/天前」反推最后更新时间。
    API 有 -352 风控时，渲染后的 DOM 里相对时间总是存在。
    看不到视频列表 → 等 3 秒重进（最多 3 次）。
    """
    url = f"https://space.bilibili.com/{mid}/upload/video"
    edge = _find_edge()
    if edge is None:
        return None

    import subprocess
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    for attempt in range(3):
        try:
            r = subprocess.run(
                [edge, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--virtual-time-budget=6000", "--dump-dom", url],
                capture_output=True, text=True, timeout=40,
                encoding="utf-8", errors="replace", creationflags=creation,
            )
            html = r.stdout or ""
            if len(html) < 10000:
                # 页面没加载出来（风控/空壳）→ 3 秒后再进
                time.sleep(3)
                continue
            # 取第一条视频的相对时间（DOM 顺序即最新在前）
            m = _REL_TIME.search(html)
            if not m:
                time.sleep(3)
                continue
            now = int(time.time())
            if m.group(1) and m.group(2):
                n, unit = int(m.group(1)), m.group(2)
                sec = {"分钟前": 60, "小时前": 3600, "天前": 86400}[unit]
                return now - n * sec
            if "刚刚" in (m.group(0) or ""):
                return now
            time.sleep(3)
        except Exception:
            time.sleep(3)
            continue
    return None


def _find_edge() -> Optional[str]:
    import sys
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if __import__("pathlib").Path(c).is_file():
            return c
    return None


def _is_fresh(entry: Dict) -> bool:
    ttl = POSITIVE_TTL if entry.get("pubdate") else NEGATIVE_TTL
    return time.time() - entry.get("ts", 0) < ttl


def get_cached(mid: str) -> Optional[int]:
    """立即返回磁盘缓存中的值（可能为 None=未知/待补齐）"""
    with _lock:
        _load_cache()
        entry = _results.get(str(mid))
        if entry and _is_fresh(entry):
            return entry.get("pubdate")
    return None


def get_status() -> Dict:
    with _lock:
        return dict(_status)


def prefetch_all(mids: List[str]):
    """
    启动后台预取（单例线程）：多轮收敛直到全部成功或轮数耗尽。

    每轮：逐个查询缺失/过期的 mid（轮内 5s 间隔）→ 保存缓存；
    失败者进下一轮（轮间退避）。前端定时轮询 get_cached() 即可看到补齐过程。
    """
    global _prefetch_thread, _status
    mids = [str(m).strip() for m in mids if str(m).strip().isdigit()]
    if not mids:
        return

    with _lock:
        if _status.get("running"):
            return
        _load_cache()
        _status = {"done": 0, "total": len(mids), "running": True}

    def _run():
        try:
            for round_idx, backoff in enumerate(ROUND_BACKOFF):
                if round_idx > 0:
                    time.sleep(backoff)

                pending = []
                with _lock:
                    for mid in mids:
                        entry = _results.get(mid)
                        if not entry or not _is_fresh(entry):
                            pending.append(mid)
                    _status["total"] = len(mids)
                    _status["done"] = sum(
                        1 for m in mids
                        if _results.get(m) and _results[m].get("pubdate")
                    )

                if not pending:
                    break

                for mid in pending:
                    pubdate = _query_one(mid)
                    with _lock:
                        _results[mid] = {"pubdate": pubdate, "ts": time.time()}
                        _status["done"] = sum(
                            1 for m in mids
                            if _results.get(m) and _results[m].get("pubdate")
                        )
                    _save_cache()
                    time.sleep(REQUEST_INTERVAL)

                with _lock:
                    remaining = sum(
                        1 for m in mids
                        if not (_results.get(m) and _results[m].get("pubdate"))
                    )
                logger.info(f"[bilibili] 预取第 {round_idx + 1} 轮完成，剩余 {remaining}/{len(mids)}")
                if remaining == 0:
                    break
        except Exception as e:
            logger.error(f"[bilibili] 预取异常: {e}")
        finally:
            with _lock:
                _status["running"] = False

    _prefetch_thread = threading.Thread(target=_run, daemon=True, name="bilibili-prefetch")
    _prefetch_thread.start()
