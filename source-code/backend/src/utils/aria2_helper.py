"""
Aria2 多线程下载（全项目共享）

- 默认 64 分片：aria2 自动把分片分配到多个源/连接（单服务器上限 16，
  多镜像源并行时可到 64）；失败时按 64 → 32 → 16 降级重试
- 多源并行：传入镜像候选 URL 列表，aria2 同时从多个源拉同一文件
- 断点续传：--continue + .aria2 控制文件
- 取消：cancel_event 触发即杀进程并清理控制文件（保留 .part 数据）
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from backend.src.utils.logger import app_logger as logger

_CONNECTION_LADDER = [64, 32, 16, 8]

# 慢速判定：窗口内平均速度低于 SLOW_BPS → 换源
SLOW_BPS = 500 * 1024      # 500 KB/s（用户要求）
SLOW_WINDOW = 60           # 60 秒窗口（用户要求：1 分钟内不足阈值才算慢源）


def find_aria2() -> Optional[Path]:
    """定位 aria2c.exe：frozen 下 exe 同级 tools/；开发模式 backend/tools/"""
    import sys
    if getattr(sys, "frozen", False):
        cand = Path(sys.executable).parent / "tools" / "aria2c.exe"
    else:
        cand = Path(__file__).resolve().parents[2] / "tools" / "aria2c.exe"
    return cand if cand.is_file() else None


def aria2_download(urls: List[str], dest: Path,
                   progress_cb: Optional[Callable[[int, int], None]] = None,
                   size_hint: int = 0,
                   cancel_ev: Optional[threading.Event] = None,
                   log_fn: Optional[Callable[[str], None]] = None,
                   max_connections: Optional[int] = None) -> bool:
    """
    aria2 多线程多源下载（自动换源）

    - 多源并列（第一个为主源），aria2 `--uri-selector=feedback` 按实测速度选源
    - **60 秒窗口速度监控**：窗口内下载量 < 1MB（含 <100KB 的极慢情形）→ 判定慢源，
      kill 当前进程并轮换主源重试（.aria2 控制文件保留 → 从断点续传）
    - 连接数按文件大小自适应，失败逐级减半

    Returns:
        bool: 是否成功
    """
    aria2 = find_aria2()
    if aria2 is None or not urls:
        return False

    log = log_fn or (lambda m: logger.info(f"[Aria2] {m}"))
    import re as _re

    # 解析 aria2 摘要行：[#gid 12MiB/23MiB(52%) CN:16 DL:5.4MiB]
    summary_re = _re.compile(
        r"\[#\w+\s+([\d.]+[KMG]?iB)/([\d.]+[KMG]?iB)\((\d+)%\)\s+CN:\d+\s+DL:([\d.]+[KMG]?iB)"
    )
    unit_mul = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}

    def _parse_size(s):
        body = s.rstrip("iB")
        unit = s[: len(s) - len(body)]
        return int(float(body) * unit_mul.get(unit, 1))

    done_box = [0]

    def _reader(proc_ref):
        import os as _os
        try:
            fd = proc_ref.stderr.fileno()
            buf = ""
            while True:
                data = _os.read(fd, 4096)
                if not data:
                    break
                buf += data.decode("utf-8", "replace")
                parts = buf.replace("\r", "\n").split("\n")
                buf = parts[-1]
                for seg in parts:
                    mm = summary_re.search(seg)
                    if mm:
                        done_box[0] = _parse_size(mm.group(1))
        except Exception:
            pass

    # 连接阶梯
    ladder = list(_CONNECTION_LADDER)
    if max_connections:
        ladder = []
        c = max(1, int(max_connections))
        while c >= 1:
            ladder.append(c)
            if c == 1:
                break
            c = max(1, c // 2)
        ladder = list(dict.fromkeys(ladder))

    # 代理感知
    try:
        from backend.src.utils.system_proxy import get_system_proxy
        sys_proxy = get_system_proxy()
    except Exception:
        sys_proxy = None
    proxy_args = [f"--all-proxy={sys_proxy}"] if sys_proxy else ["--all-proxy="]
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # 残留控制文件清理：dest 不存在但 .aria2 在 → --continue 会死等不存在的分片
    try:
        control = dest.with_suffix(dest.suffix + ".aria2")
        if not dest.exists() and control.exists():
            control.unlink(missing_ok=True)
    except OSError:
        pass

    current_urls = list(urls)
    src_rotations = 0
    MAX_ROTATION = 2  # 最多换 2 次源（之后接受现实速度）

    def _run_once(conns: int) -> str:
        """跑一次 aria2。返回 'ok' / 'slow'（60s 窗口不达标）/ 'fail'"""
        cmd = [str(aria2), *current_urls, *proxy_args,
               "--dir", str(dest.parent), "--out", dest.name,
               "--split", str(conns),
               "--max-connection-per-server=16",
               "--min-split-size=1M",
               "--max-concurrent-downloads=16",
               "--max-tries=5", "--retry-wait=2",
               "--timeout=30", "--connect-timeout=15",
               "--lowest-speed-limit=200K",
               "--uri-selector=feedback",
               "--http-accept-gzip=false",
               "--summary-interval=1",
               "--console-log-level=warn",
               "--allow-overwrite=true", "--auto-file-renaming=false",
               "--file-allocation=none",
               "--check-certificate=false"]
        if dest.exists() and dest.stat().st_size > 0:
            cmd.append("--continue")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, creationflags=creation)
        except Exception as e:
            logger.warning(f"[Aria2] 启动失败: {e}")
            return "fail"
        threading.Thread(target=_reader, args=(proc,), daemon=True,
                         name="aria2-progress").start()

        done0 = dest.stat().st_size if dest.is_file() else 0
        win_start, win_done = time.time(), done0
        while proc.poll() is None:
            if cancel_ev is not None and cancel_ev.is_set():
                proc.kill()
                log("下载已取消")
                return "fail"
            done = done_box[0] or (dest.stat().st_size if dest.is_file() else 0)
            if progress_cb and size_hint:
                progress_cb(min(done, size_hint), size_hint)
            now = time.time()
            # ---- 慢速判定：15 秒窗口平均速度 < 500KB/s → 换源 ----
            if now - win_start >= SLOW_WINDOW:
                delta = done - win_done
                avg_bps = delta / max(now - win_start, 0.001)
                if avg_bps < SLOW_BPS and (not size_hint or done < size_hint):
                    log(f"平均速度仅 {avg_bps / 1024:.0f}KB/s（{conns} 连接），判定慢源")
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    return "slow"
                win_start, win_done = now, done
            time.sleep(1)

        if proc.returncode == 0 and dest.is_file():
            if progress_cb and size_hint:
                progress_cb(size_hint, size_hint)
            return "ok"
        return "fail"

    # 主循环：**先换源后降连接**（用户要求）
    #   对每个连接档：依次尝试所有源（轮换）→ 全部源都不行 → 才降连接数重来
    total_urls = len(current_urls)
    rotations_done = 0
    for conns in ladder:
        if cancel_ev is not None and cancel_ev.is_set():
            return False
        # 当前连接档：最多轮换 len(urls) 次（把所有源试一遍）
        tries = min(total_urls, MAX_ROTATION + 2)
        for t_i in range(tries):
            result = _run_once(conns)
            if result == "ok":
                return True
            if result == "slow":
                log(f"{conns} 连接下当前源过慢，换源重试（{t_i + 1}/{tries}）")
            else:
                log(f"{conns} 连接下当前源失败，换源重试（{t_i + 1}/{tries}）")
            rotations_done += 1
            if len(current_urls) > 1:
                current_urls = current_urls[1:] + current_urls[:1]
                log(f"切换下载源：{current_urls[0]}")
        log(f"{conns} 连接下所有源均不可用，降低连接数重试")
    return False

