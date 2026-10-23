"""
统一下载缓存层（全板块共用）

设计目标：
  1. **所有下载物先落缓存目录**（<app_data>/downloads），再解压/复制到目标位置——
     换安装目录、重装、多板块共享同一份缓存，避免重复下载
  2. **完整性校验**：缓存文件大小匹配 + 无 .part/.aria2 残留才算"完整"
  3. **断点续传**：.part/.aria2 保留，中断后续传；两个下载器语义统一
  4. 记录 `<缓存>/.manifest.json`：url → {file, size, done, ts}

使用方式：
    p = fetch(url, "ComfyUI_windows_portable_nvidia.7z", size_hint=..., progress_cb=...)
    # p 指向缓存中的完整文件；调用方负责解压/复制
"""

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from backend.src.utils.logger import app_logger as logger

MANIFEST = ".manifest.json"


def cache_dir() -> Path:
    """全局下载缓存目录：主程序同级 /download（跨安装目录/跨板块复用）"""
    try:
        from backend.src.utils.paths import get_downloads_dir
        return Path(get_downloads_dir())
    except Exception:
        d = Path.home() / ".comfynexus" / "downloads"
        d.mkdir(parents=True, exist_ok=True)
        return d


_MAX_AGE_DAYS = 7
_cleanup_lock = threading.Lock()
_cleanup_done = [0.0]


def cleanup_old_files(max_age_days: int = _MAX_AGE_DAYS):
    """
    清理超过 max_age_days 天的缓存文件（每周一触发一次的语义由调用方保证；
    这里按「进程内每天最多清一次」去重）。

    保留 .manifest.json 与仍在下载中的 .part/.aria2。
    """
    import datetime
    now = time.time()
    # 只在周一执行删除（用户要求：每周一删除超过 7 天的文件）
    if datetime.datetime.now().weekday() != 0:
        return
    with _cleanup_lock:
        if now - _cleanup_done[0] < 86400:
            return
        _cleanup_done[0] = now
    cutoff = now - max_age_days * 86400
    removed = 0
    try:
        for f in cache_dir().iterdir():
            if not f.is_file():
                continue
            if f.name == MANIFEST or f.suffix in (".part", ".aria2", ".bad"):
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.info(f"[DownloadCache] 已清理 {removed} 个超过 {max_age_days} 天的缓存文件")
    except Exception as e:
        logger.debug(f"[DownloadCache] 清理失败: {e}")


def _manifest_path() -> Path:
    return cache_dir() / MANIFEST


def _load_manifest() -> dict:
    try:
        p = _manifest_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_manifest(m: dict):
    try:
        _manifest_path().write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[DownloadCache] manifest 写入失败: {e}")


def _url_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8", "replace")).hexdigest()[:12]


def cached_path(url: str, filename: str) -> Path:
    """该 URL 对应的缓存文件路径（稳定：同 URL 同路径）"""
    safe = "".join(ch for ch in filename if ch not in '\\/:*?"<>|').strip() or "download.bin"
    return cache_dir() / f"{_url_key(url)}_{safe}"


def is_complete(url: str, path: Path, expected_size: int = 0) -> bool:
    """
    缓存文件是否完整（可跳过下载）：
      - 文件存在、无 .part/.aria2 残留
      - 期望大小已知 → 必须匹配
      - 期望未知 → manifest 记录大小匹配
    """
    try:
        if not path.is_file():
            return False
        for suffix in (".part", ".aria2"):
            if path.with_suffix(path.suffix + suffix).exists():
                return False
        actual = path.stat().st_size
        if expected_size > 0:
            return actual == expected_size
        entry = _load_manifest().get(url) or {}
        rec = int(entry.get("size") or 0)
        return rec > 0 and actual == rec
    except OSError:
        return False


def record(url: str, path: Path, done: bool = True):
    m = _load_manifest()
    try:
        size = path.stat().st_size if path.is_file() else 0
    except OSError:
        size = 0
    m[url] = {"file": path.name, "size": size, "done": bool(done), "ts": time.time()}
    _save_manifest(m)


def fetch(url: str, filename: str,
          size_hint: int = 0,
          progress_cb: Optional[Callable[[int, int], None]] = None,
          extra_urls: Optional[List[str]] = None,
          cancel_ev: Optional[threading.Event] = None,
          log_fn: Optional[Callable[[str], None]] = None,
          max_connections: Optional[int] = None) -> Path:
    """
    统一下载入口：缓存命中（完整）直接返回；否则下载到缓存目录（aria2 多线程/续传）。

    Returns:
        Path: 缓存中的完整文件路径

    Raises:
        RuntimeError: 所有源失败
    """
    log = log_fn or (lambda m: logger.info(m))
    dest = cached_path(url, filename)
    migrate_legacy_appdata()
    cleanup_old_files()

    if is_complete(url, dest, size_hint):
        log(f"缓存命中（完整），跳过下载: {filename}")
        if progress_cb and size_hint:
            progress_cb(size_hint, size_hint)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)

    # urls 必须在使用前定义（probe/多源扩展都依赖它）
    urls = [url] + [u for u in (extra_urls or []) if u]
    log(f"下载链接: {url}")

    from backend.src.utils.aria2_helper import aria2_download, find_aria2
    # 总大小未知 → HEAD/Range 探测（保证进度条能显示总大小与百分比）
    if size_hint <= 0:
        if True:
            for probe_u in urls[:3]:
                try:
                    import requests as _rq
                    r = _rq.head(probe_u, allow_redirects=True, timeout=(8, 15),
                                 headers={"User-Agent": "ComfyNexus/1.0"})
                    if r.status_code >= 400:
                        r = _rq.get(probe_u, stream=True, timeout=(8, 15),
                                    headers={"User-Agent": "ComfyNexus/1.0", "Range": "bytes=0-0"})
                        r.close()
                    cl = int(r.headers.get("Content-Length") or 0)
                    if cl > 0:
                        size_hint = cl
                        log(f"探测到文件大小: {cl / 1048576:.1f}MB")
                        break
                    # Content-Length=0（302 跳转页等）→ 换下一个候选探测
                except Exception:
                    continue

    # 自动多源扩展：URL 是 GitHub 镜像形态（https://mirror/https://github.com/...）时，
    # 自动补充脚本镜像 + 内置镜像的等价地址（单源慢时 aria2/换源机制才有源可换）
    # codeload / github 两种形态都支持（codeload 对镜像兼容性更好）
    _base = None
    gh_path = None
    if "/https://github.com/" in url:
        _base = "/https://github.com/"
        gh_path = url.split(_base, 1)[1]
    elif "/https://codeload.github.com/" in url:
        _base = "/https://codeload.github.com/"
        gh_path = url.split(_base, 1)[1]
    elif url.startswith("https://codeload.github.com/"):
        # 裸 codeload：转成「镜像前缀 codeload」候选（CDN 支持 Range 多连接）
        gh_path = "/" + url[len("https://codeload.github.com/"):]
        _base = "/https://codeload.github.com/"  # 后续拼接前缀用
    if gh_path is not None:
        gh_path = gh_path.lstrip("/")  # 防 // 双斜杠（镜像站会 403/404）
    if len(urls) == 1 and _base:
        try:
            from backend.src.utils.mirror_script import fetch_script_mirrors
            pool = list(fetch_script_mirrors()) or []
            pool += ["gh-proxy.org", "edgeone.gh-proxy.org", "cdn.gh-proxy.org",
                     "hk.gh-proxy.org", "ghproxy.net", "ghfast.top", "gh.monlor.com",
                     "ghpxy.hwinzniej.top", "github.ednovas.xyz", "ghproxy.it"]
            for m in pool:
                cand = f"https://{m}{_base}{gh_path}"
                if cand not in urls and len(urls) < 10:
                    urls.append(cand)
            # 直连兜底（codeload 本身可连，慢但可靠）
            direct = f"https://codeload.github.com/{gh_path}" if _base else None
            if direct and direct not in urls:
                urls.append(direct)
            if len(urls) > 1:
                log(f"多源扩展：{len(urls)} 个镜像源可切换")
                for i, u in enumerate(urls[:10]):
                    log(f"  源 {i}: {u}")
        except Exception:
            pass
    if find_aria2() and (size_hint > 1024 * 1024 or size_hint <= 0):
        log(f"使用 aria2 多线程下载: {filename}")
        conns = max_connections or (max(1, min(64, int(size_hint // (1024 * 1024)))) if size_hint else 64)
        if aria2_download(urls, dest, progress_cb, size_hint, cancel_ev=cancel_ev,
                          log_fn=log, max_connections=conns):
            record(url, dest)
            log(f"下载完成: {filename}（{dest.stat().st_size / 1048576:.1f}MB）")
            return dest

    # 回退单线程（带 Range 续传）
    log(f"回退单线程下载: {filename}")
    _single_thread(url, dest, progress_cb, size_hint, cancel_ev)
    record(url, dest)
    log(f"下载完成: {filename}（{dest.stat().st_size / 1048576:.1f}MB）")
    return dest


def _single_thread(url: str, dest: Path, progress_cb, size_hint: int,
                   cancel_ev: Optional[threading.Event]):
    import requests
    part = dest.with_suffix(dest.suffix + ".part")
    # 保护进度：aria2 已下到 dest（可能 90%+）时，先转成 .part 再 Range 续传，
    # 否则会从头覆盖（曾导致 2.5GB 下载 92% 后重下）
    if not part.exists() and dest.is_file() and dest.stat().st_size > 0:
        try:
            size_hint_now = size_hint
            if size_hint_now <= 0 or dest.stat().st_size < size_hint_now:
                dest.replace(part)
        except OSError:
            pass
    headers = {"User-Agent": "ComfyNexus/1.0"}
    if part.exists() and part.stat().st_size > 0:
        headers["Range"] = f"bytes={part.stat().st_size}-"
    with requests.get(url, stream=True, timeout=(30, 120), headers=headers,
                      allow_redirects=True) as r:
        r.raise_for_status()
        resumed = r.status_code == 206 and headers.get("Range")
        mode = "ab" if resumed else "wb"
        done = part.stat().st_size if resumed and part.exists() else 0
        total = int(r.headers.get("Content-Length") or 0) + (done if resumed else 0)
        win_start, win_done = time.time(), done
        with open(part, mode) as f:
            for chunk in r.iter_content(1 << 20):
                if cancel_ev is not None and cancel_ev.is_set():
                    raise RuntimeError("下载已取消")
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total or size_hint)
                    # 60 秒窗口速度监控：增量 < 1MB 判定慢源，交由上层换源
                    now = time.time()
                    if now - win_start >= 60:
                        delta = done - win_done
                        if delta < 1024 * 1024 and (not (total or size_hint) or done < (total or size_hint)):
                            raise RuntimeError(f"慢源（60 秒仅 {delta / 1024:.0f}KB），切换下一源")
                        win_start, win_done = now, done
        part.replace(dest)


def migrate_legacy_appdata(log_fn: Optional[Callable[[str], None]] = None):
    """把旧 ~/.comfynexus/downloads 的缓存迁到主程序同级 /download"""
    try:
        old_dir = Path.home() / ".comfynexus" / "downloads"
        if not old_dir.is_dir():
            return
        moved = 0
        for f in old_dir.iterdir():
            if not f.is_file():
                continue
            target = cache_dir() / f.name
            if target.exists():
                f.unlink(missing_ok=True)
                continue
            try:
                f.replace(target)
                moved += 1
            except OSError:
                pass
        if moved:
            (log_fn or (lambda m: logger.info(m)))(f"已迁移 {moved} 个缓存文件到 download 目录")
        if not any(old_dir.iterdir()):
            old_dir.rmdir()
    except Exception as e:
        logger.debug(f"[DownloadCache] appdata 迁移失败: {e}")


def migrate_legacy(install_dir: Path, log_fn: Optional[Callable[[str], None]] = None):
    """
    迁移旧版临时目录里的下载物到全局缓存（避免升级后重下大文件）：
      install_dir/_comfynexus_tmp/*.7z / *.zip → <cache>/
      install_dir/_zip_*/*.zip → <cache>/
    """
    log = log_fn or (lambda m: None)
    try:
        moved = 0
        sources = []
        legacy = Path(install_dir) / "_comfynexus_tmp"
        if legacy.is_dir():
            sources.extend(legacy.glob("*.7z"))
            sources.extend(legacy.glob("*.zip"))
        for d in Path(install_dir).glob("_zip_*"):
            if d.is_dir():
                sources.extend(d.glob("*.zip"))
        for f in sources:
            try:
                target = cache_dir() / f.name
                if target.exists() and target.stat().st_size == f.stat().st_size:
                    f.unlink(missing_ok=True)
                    continue
                if a_same_volume(f, target):
                    shutil.move(str(f), str(target))
                else:
                    shutil.copy2(str(f), str(target))
                    f.unlink(missing_ok=True)
                moved += 1
            except Exception:
                continue
        if moved:
            log(f"已迁移 {moved} 个旧下载文件到统一缓存目录")
    except Exception as e:
        logger.debug(f"[DownloadCache] 迁移失败: {e}")


def a_same_volume(a: Path, b: Path) -> bool:
    try:
        return Path(a).drive.lower() == Path(b).drive.lower()
    except Exception:
        return False