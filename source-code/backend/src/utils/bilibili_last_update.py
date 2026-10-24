"""
Bilibili UP 主最新投稿时间查询（多接口回退 + 预取 + 持久缓存）

## 为什么需要多接口回退（2026-10 实测）

B 站各接口风控强度差异极大，**同一账号在不同接口上是完全不同的命运**：

| 接口 | 实测结果 |
| --- | --- |
| `x/space/wbi/arc/search`（WBI 签名） | **-352 风控校验失败** / HTTP 412 |
| `x/space/arc/search`（无签名） | HTTP 412 |
| `x/polymer/web-dynamic/v1/feed/space` | HTTP 412 |
| `x/space/wbi/acc/info` | -403 访问权限不足 |
| `x/series/recArchivesByKeywords` | **间歇性 412**（约 30% 成功率，频率敏感） |
| `x/polymer/web-space/seasons_series_list` | **100% 成功，免风控** |
| `x/polymer/web-dynamic/v1/opus/feed/space` | **100% 成功，免风控** |
| `x/web-interface/card` | 100% 成功 |
| `x/space/navnum` | 100% 成功 |

### 为什么「诶-阿伟哥」一直不显示（本次修的 bug）

原实现只有一条路径：`recArchivesByKeywords` → 失败后退回 Edge headless 抓
`space.bilibili.com/{mid}/upload/video` 页面。

对这个 UP 主两条路都断了：
1. `recArchivesByKeywords` 对他**稳定 412**（不是间歇，是必然）；
2. headless 页面抓到的 DOM 里是「空间主人还没投过视频，这里什么也没有...」——
   他有 5 个视频 + **30 篇图文**，主战场是图文（opus），
   但图文不进「投稿视频」列表页，而这个页面当时还被风控渲染成空壳。
   → 两条路都拿不到，`pubdate` 永远为 None，卡片永远不出提示。

### 现在的主路径：opus 动态（覆盖图文 + 视频）

`opus/feed/space` 返回该 UP 主的**全部动态**（视频投稿、图文、转发都会进 opus），
天然覆盖「视频少但图文多」的创作者，正是本 bug 的场景。
列表项不含时间，需再请求一次 `opus/detail` 取 `module_author.pub_ts`。
两次请求即可，无需翻页（列表已按时间倒序，第一条就是最新的）。

## 架构
- `get_cached(mid)`：前端卡片立即可读（磁盘缓存，可能为 None）
- `prefetch_all(mids)`：后台线程启动预取循环，逐轮收敛
- `get_status()`：{done, total, running}

## 缓存语义（很重要）
- 成功：`{"pubdate": int, "ts": 写入时刻, "src": 来源接口}`
- 失败：`{"pubdate": None, "ts": 写入时刻}`
- **失败条目不能污染成功条目**：某一轮失败时若直接覆盖，会把上一轮的正确答案冲成
  None，导致「上次还能显示、这次突然消失」。所以失败时保留旧的 pubdate
  （见 `_should_keep_old`）。
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from backend.src.utils.logger import app_logger as logger
from backend.src.utils.paths import get_cache_dir

# ---------- 各接口地址 ----------
SEASONS_URL = "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
OPUS_FEED_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space"
OPUS_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
ARC_URL = "https://api.bilibili.com/x/series/recArchivesByKeywords"

REQUEST_INTERVAL = 3.0                  # 轮内请求间隔
ROUND_BACKOFF = [5, 20, 45, 90, 180, 300]   # 轮间退避（秒）
POSITIVE_TTL = 6 * 3600                 # 成功缓存 6 小时
NEGATIVE_TTL = 10 * 60                  # 失败负缓存 10 分钟（轮内跳过）

_lock = threading.Lock()
_session: Optional[requests.Session] = None
_cache_file: Optional[Path] = None
_results: Dict[str, Dict] = {}          # mid -> {"pubdate", "ts", "src"}
_prefetch_thread: Optional[threading.Thread] = None
_status = {"done": 0, "total": 0, "running": False}


def _session_get() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False      # 绕开系统代理（本机代理会拦 127/外网）
        _session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://space.bilibili.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # 预热 buvid3 cookie，降低风控概率（实测能显著减少 412）
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
        p.write_text(json.dumps(_results, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[bilibili] 缓存写入失败: {e}")


def _get_json(url: str, params: Optional[dict] = None,
              timeout=(10, 20)) -> Optional[dict]:
    """统一 GET + JSON 解析。**412/非 JSON 一律返回 None**，不抛异常。

    返回 None 不代表「这个 UP 主没作品」，只代表「这条路走不通，换下一条」。
    这种区分很重要：把「被风控」当成「没投稿」会让卡片永远不出提示。
    """
    try:
        r = _session_get().get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            logger.debug(f"[bilibili] {url} HTTP {r.status_code}")
            return None
        ctype = (r.headers.get("content-type") or "").lower()
        if "json" not in ctype:
            # 412 风控返回的是 HTML 验证页，不是 JSON
            logger.debug(f"[bilibili] {url} 非 JSON（疑似风控）")
            return None
        return r.json()
    except Exception as e:
        logger.debug(f"[bilibili] {url} 请求异常: {e}")
        return None


# ---------------------------------------------------------------------------
# 路径 1：opus 动态（主路径，覆盖图文 + 视频，实测免风控）
# ---------------------------------------------------------------------------

def _query_via_opus(mid: str) -> Optional[int]:
    """取该 UP 主最新一条动态的发布时间。

    为什么这条路径最可靠：
      - 免风控（实测 11/11 成功），而 arc/search 系全线 -352/412；
      - 覆盖**图文**。诶-阿伟哥 30 篇图文 5 个视频，只看视频会误判成「很久没更新」；
      - 列表已按时间倒序，只取第一条即可，无需翻页。

    代价：列表项 `pub_time` 是空字符串，必须再请求一次 detail 拿 `pub_ts`。
    两次请求、间隔 1.5s，可接受。
    """
    feed = _get_json(OPUS_FEED_URL, {"host_mid": mid, "page": 1, "type": "all"})
    if not feed:
        return None
    if feed.get("code") != 0:
        logger.debug(f"[bilibili] opus feed mid={mid} code={feed.get('code')}")
        return None
    items = ((feed.get("data") or {}).get("items")) or []
    if not items:
        # 真的没有任何动态（新号/空号），这是有效结论而非失败
        logger.debug(f"[bilibili] opus feed mid={mid} 无动态")
        return 0
    opus_id = items[0].get("opus_id")
    if not opus_id:
        return None

    time.sleep(1.5)   # 拉开两次请求间隔，降低触发风控的概率
    detail = _get_json(OPUS_DETAIL_URL, {"id": opus_id, "features": "itemOpusStyle"})
    if not detail or detail.get("code") != 0:
        return None
    item = ((detail.get("data") or {}).get("item")) or {}
    modules = item.get("modules") or {}
    # detail 的 modules 是 dict（新结构）；兼容老结构 list
    if isinstance(modules, list):
        author = {}
        for m in modules:
            if isinstance(m, dict) and m.get("module_author"):
                author = m["module_author"]
                break
    else:
        author = modules.get("module_author") or {}
    pub_ts = author.get("pub_ts")
    return int(pub_ts) if pub_ts else None


# ---------------------------------------------------------------------------
# 路径 2：合集/系列（辅助，覆盖「只在合集里更新」的 UP 主）
# ---------------------------------------------------------------------------

def _query_via_seasons(mid: str) -> Optional[int]:
    """取所有合集/系列里最新一期的发布时间。免风控，作为 opus 的补充。

    局限：只能看到**已归入合集**的视频，散装视频看不到。
    所以定位是「补漏」而不是主路径。
    """
    data = _get_json(SEASONS_URL, {"mid": mid, "page_num": 1, "page_size": 20})
    if not data or data.get("code") != 0:
        return None
    items_lists = (data.get("data") or {}).get("items_lists") or {}
    latest: Optional[int] = None
    for group in (items_lists.get("seasons_list") or []) + \
                 (items_lists.get("series_list") or []):
        for arc in (group.get("archives") or []):
            p = arc.get("pubdate")
            if p:
                p = int(p)
                if latest is None or p > latest:
                    latest = p
    return latest


# ---------------------------------------------------------------------------
# 路径 3：recArchivesByKeywords（老路径，间歇可用，仅作兜底）
# ---------------------------------------------------------------------------

def _query_via_arc(mid: str) -> Optional[int]:
    """老接口。实测对这个 UP 主稳定 412，但对另一些账号还能用，保留作兜底。"""
    data = _get_json(ARC_URL, {"mid": mid, "keywords": "", "ps": "1"})
    if not data or data.get("code") != 0:
        return None
    archives = (data.get("data") or {}).get("archives") or []
    if not archives:
        return None
    pubdate = archives[0].get("pubdate")
    return int(pubdate) if pubdate else None


def _query_one(mid: str) -> Optional[int]:
    """取各路径结果的**最大值**（最新时间），而不是「第一个成功就用」。

    **这是本方案最关键的一处，别改回「短路返回」**（实测踩过）：

    三条路径覆盖的作品类型不同，必须取并集才是「最近一次更新」：
      - opus    ：覆盖图文动态 + 转发，但**看不到纯视频投稿**
                  （8g显存小黑 有 2026-10 发布的视频，opus 里最新只到 2023-12，
                   因为他发视频时不带图文动态 → 只看 opus 会误报「1041 天没更新」）
      - seasons ：覆盖**已归入合集**的视频
      - arc     ：覆盖视频投稿列表（风控严，能通就最准）

    实测证据（8g显存小黑）：opus=2023-12-18 / seasons=2026-10-24
    → 取 max 才是正确答案；短路返回会给用户一个「三年没更新」的假警报。

    返回值：
      - int > 0：最新发布时间戳（多路取最大）
      - 0      ：确认无任何作品（有效结论）
      - None   ：所有路径都失败（未知，下一轮重试）
    """
    values = []
    for name, fn in (("opus", _query_via_opus),
                     ("seasons", _query_via_seasons),
                     ("arc", _query_via_arc)):
        try:
            val = fn(mid)
        except Exception as e:
            logger.debug(f"[bilibili] {name} mid={mid} 异常: {e}")
            continue
        if val is not None:
            values.append((name, val))
            if val:
                logger.debug(f"[bilibili] mid={mid} {name} → pubdate={val}")
        time.sleep(0.8)   # 换路径前略等，避免连续撞风控

    if not values:
        return None
    positive = [v for _, v in values if v]
    if positive:
        best = max(positive)
        src = [n for n, v in values if v == best][0]
        logger.debug(f"[bilibili] mid={mid} 最终取 {src} 的 {best}")
        return best
    # 全部路径都"成功但为空" → 确认无作品
    return 0


def _is_fresh(entry: Dict) -> bool:
    ttl = POSITIVE_TTL if entry.get("pubdate") else NEGATIVE_TTL
    return time.time() - entry.get("ts", 0) < ttl


def _should_keep_old(mid: str, new_val: Optional[int]) -> bool:
    """失败时是否保留旧的 pubdate。

    **这是「提示时有时无」的根治点**：
      原实现每轮失败都直接写 `{"pubdate": None}`，把上一轮好不容易拿到的
      正确时间戳冲掉了。前端读到 None 就不再显示倒计时 ——
      用户感受是「这个提示一会儿有一会儿没有」。
      现在：新值失败（None 且旧值>0）就保留旧值，只更新 ts。
    """
    if new_val is not None:
        return False
    old = _results.get(str(mid)) or {}
    return bool(old.get("pubdate"))


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
    """启动后台预取（单例线程）：多轮收敛直到全部成功或轮数耗尽。"""
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
                        keep = _should_keep_old(mid, pubdate)
                        if keep:
                            old = dict(_results.get(mid) or {})
                            old["ts"] = time.time()
                            _results[mid] = old
                            logger.debug(
                                f"[bilibili] mid={mid} 本轮失败，保留旧值 "
                                f"{old.get('pubdate')}"
                            )
                        else:
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
                logger.info(
                    f"[bilibili] 预取第 {round_idx + 1} 轮完成，"
                    f"剩余 {remaining}/{len(mids)}"
                )
                if remaining == 0:
                    break
        except Exception as e:
            logger.error(f"[bilibili] 预取异常: {e}")
        finally:
            with _lock:
                _status["running"] = False

    _prefetch_thread = threading.Thread(target=_run, daemon=True,
                                        name="bilibili-prefetch")
    _prefetch_thread.start()
