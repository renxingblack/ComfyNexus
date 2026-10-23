"""
安装前全面测速（全部使用 aria2）

覆盖三个维度：
  1. 原始链接 × 不使用系统代理
  2. 原始链接 × 使用系统代理
  3. 各加速镜像站 × 不使用代理（gh-proxy 系列完整前缀形式）

礼貌性约束（遵守各镜像站规范）：
  - 每站仅用 4 连接、单次采样 2MB（不压满 16 连接上限，不长时间占用带宽）
  - 每目标独立超时，失败快速跳过（不重试轰炸公益站）
  - 多目标并行探测（总计 ~20-40 秒完成）

结果按实测速度排名，供后续下载排序使用（优先于心跳小文件测速）。
"""

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from backend.src.utils.logger import app_logger as logger

# 测速链接（用户指定）
GITHUB_BENCH_URL = ("https://github.com/renxingblack/math-vertical-worksheet-generator/"
                    "releases/download/4.0/Vertical-Division-Generator-4.0.exe")
HF_BENCH_URL = ("https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/"
                "resolve/main/model.safetensors.index.json")  # resolve 才是文件直链（blob 是网页）

# 分类型测速（用户要求：release / raw / zip 三类分别测速取优）
REL_PATH = "/renxingblack/math-vertical-worksheet-generator/releases/download/4.0/Vertical-Division-Generator-4.0.exe"
RAW_PATH = "/rgthree/rgthree-comfy/main/README.md"  # raw.githubusercontent 格式无 /raw/ 段
ZIP_PATH = "/rgthree/rgthree-comfy/zip/refs/heads/main"   # codeload 形态

# HuggingFace 镜像（实测可用：hf-mirror.com / hf-mirror.net；官方直连国内多不通）
HF_MIRRORS = ["hf-mirror.com", "hf-mirror.net"]
HF_PATH = "/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/main/model.safetensors.index.json"

# 加速镜像站（gh-proxy 系列：完整前缀形式 https://{mirror}/https://github.com/...）
BENCH_MIRRORS = [
    "cdn.gh-proxy.org",
    "hk.gh-proxy.org",
    "ghfast.top",
    "gh.monlor.com",
    "gh.catmak.name",
    "gh.77yun.com.cn",
    "gh-proxy.net",
    "gh.h233.eu.org",
    "gh.ddlc.top",
    "wget.la",
    "github.moeyy.xyz",
    "ghproxy.net",
]

SAMPLE_BYTES = 2 * 1024 * 1024   # 每站采样 2MB
PER_TARGET_TIMEOUT = 18          # 单目标最长 18 秒（慢速站给足时间）


def _find_aria2() -> Optional[str]:
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        cand = Path(sys.executable).parent / "tools" / "aria2c.exe"
    else:
        cand = Path(__file__).resolve().parents[2] / "tools" / "aria2c.exe"
    return str(cand) if cand.is_file() else None


def _system_proxy() -> Optional[str]:
    try:
        from backend.src.utils.system_proxy import get_system_proxy
        return get_system_proxy()
    except Exception:
        return None


def _probe_with_aria2(aria2: str, url: str, use_proxy: bool) -> Dict:
    """
    aria2 采样测速：温和并发（4 连接），下满 2MB 即停止。

    Returns:
        {ok, speed_mbps, latency_ms, size}
    """
    proxy = _system_proxy() if use_proxy else None
    proxy_arg = f"--all-proxy={proxy}" if proxy else "--all-proxy="
    tmp_dir = None
    try:
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="gbench_")
        cmd = [
            aria2, url,
            "--dir", tmp_dir, "--out", "bench.bin",
            "--split=4", "--max-connection-per-server=4",   # 礼貌性并发：不压满
            "--min-split-size=1M",
            "--max-tries=1", "--retry-wait=0",               # 不重试轰炸
            "--timeout=8", "--connect-timeout=6",
            proxy_arg,
            "--summary-interval=0", "--console-log-level=warn",
            "--allow-overwrite=true", "--auto-file-renaming=false",
            "--check-certificate=false",
            "--file-allocation=none",
        ]
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        t0 = time.perf_counter()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=creation)
        dest = None
        try:
            from pathlib import Path
            dest = Path(tmp_dir) / "bench.bin"
        except Exception:
            pass
        downloaded = 0
        # 轮询：下满采样量或超时即停（记录实际速度）
        while proc.poll() is None and (time.perf_counter() - t0) < PER_TARGET_TIMEOUT:
            time.sleep(0.25)
            if dest and dest.is_file():
                downloaded = dest.stat().st_size
                if downloaded >= SAMPLE_BYTES:
                    break
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        elapsed = max(time.perf_counter() - t0, 0.001)
        if dest and dest.is_file():
            downloaded = max(dest.stat().st_size, downloaded)
        # 小文件（< 采样量）下载完成即算成功（raw 测速就是小文件）
        completed = proc.returncode == 0 and downloaded > 0
        ok = downloaded >= SAMPLE_BYTES * 0.8 or completed
        speed = round(downloaded * 8 / elapsed / 1_000_000, 2) if downloaded else 0.0
        return {
            "ok": ok,
            "speed_mbps": speed if ok else 0.0,
            "latency_ms": int(elapsed * 1000),
            "size": downloaded,
        }
    except Exception as e:
        return {"ok": False, "speed_mbps": 0.0, "latency_ms": None, "size": 0, "error": str(e)}
    finally:
        try:
            import shutil
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def run_full_speed_test(log_fn: Optional[Callable[[str], None]] = None) -> Dict:
    """
    执行全面测速并按速度排名。

    Returns:
        {
          "ranking": [{"name","kind","url","ok","speed_mbps","latency_ms"}],  # 优者在前
          "mirrorRanking": ["cdn.gh-proxy.org", ...],   # 镜像站速度排名
          "bestGithubDirect": bool,   # 直连是否更快（决定是否还用镜像）
          "bestHfDirect": bool,
          "proxyAvailable": bool,
        }
    """
    log = log_fn or (lambda m: logger.info(f"[测速] {m}"))
    aria2 = _find_aria2()
    if aria2 is None:
        log("未找到 aria2，跳过测速")
        return {"ranking": [], "mirrorRanking": [], "bestGithubDirect": False,
                "bestHfDirect": False, "proxyAvailable": False}

    proxy = _system_proxy()
    log("开始安装前全面测速（aria2 / 每站 4 连接采样 2MB）...")

    # 目标清单
    targets: List[Dict] = [
        {"name": "GitHub原始链接(无代理)", "kind": "direct", "url": GITHUB_BENCH_URL, "proxy": False},
        {"name": "HuggingFace原始链接(无代理)", "kind": "direct", "url": HF_BENCH_URL, "proxy": False},
    ]
    if proxy:
        targets.append({"name": "GitHub原始链接(走系统代理)", "kind": "direct_proxy",
                        "url": GITHUB_BENCH_URL, "proxy": True})
        targets.append({"name": "HuggingFace原始链接(走系统代理)", "kind": "direct_proxy",
                        "url": HF_BENCH_URL, "proxy": True})
    for m in HF_MIRRORS:
        targets.append({
            "name": f"{m}(HF)", "kind": "hf_mirror",
            "url": f"https://{m}{HF_PATH}", "proxy": False,
        })

    # 测速前先同步加速脚本（5a/5b）：脚本有更新则用最新镜像列表
    bench_mirrors = list(BENCH_MIRRORS)
    try:
        from backend.src.utils.mirror_script import fetch_script_mirrors
        script_mirrors = fetch_script_mirrors(log_fn=log)
        if script_mirrors:
            # 脚本镜像排前面（最新最强），内置列表补足
            merged = script_mirrors + [m for m in bench_mirrors if m not in script_mirrors]
            bench_mirrors = merged
    except Exception as e:
        logger.debug(f"[测速] 脚本镜像获取失败: {e}")

    gh_path = GITHUB_BENCH_URL.replace("https://github.com", "")
    for m in bench_mirrors:
        # 镜像站规范：gh-proxy 系列 = 完整前缀形式
        targets.append({
            "name": m, "kind": "mirror",
            "url": f"https://{m}/https://github.com{gh_path}", "proxy": False,
        })

    results = []
    done_count = [0]
    lock = threading.Lock()

    def _task(t):
        r = _probe_with_aria2(aria2, t["url"], t["proxy"])
        r["name"] = t["name"]
        r["kind"] = t["kind"]
        r["url"] = t["url"]
        with lock:
            done_count[0] += 1
            log(f"  [{done_count[0]}/{len(targets)}] {t['name']}: "
                f"{r['speed_mbps']:.2f} Mbps" if r["ok"] else
                f"  [{done_count[0]}/{len(targets)}] {t['name']}: 不可用")
        return r

    # 并行探测（6 路）
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="bench") as pool:
        futures = [pool.submit(_task, t) for t in targets]
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception:
                pass

    # 排序：有效结果按速度降序（速度为主）
    results.sort(key=lambda x: (x["ok"], x["speed_mbps"]), reverse=True)

    # ---- 阶段二：raw / zip 分类型测速（跑最可控的 10 个站，避免 100+ 目标过慢）----
    gh_ok = [r for r in results if r["kind"] == "mirror" and r["ok"]]
    top_mirrors = [r["name"] for r in gh_ok][:10]
    type_results = {"release": list(gh_ok), "raw": [], "zip": []}
    if top_mirrors:
        log(f"开始 raw / zip 分类型测速（前 {len(top_mirrors)} 个站）...")
        stage2 = []
        for m in top_mirrors:
            stage2.append({"name": m, "kind": "raw",
                           "url": f"https://{m}/https://raw.githubusercontent.com{RAW_PATH}", "proxy": False})
            stage2.append({"name": m, "kind": "zip",
                           "url": f"https://{m}/https://codeload.github.com{ZIP_PATH}", "proxy": False})
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="bench2") as pool2:
            futs = [pool2.submit(_task, tg) for tg in stage2]
            for f in as_completed(futs):
                try:
                    r2 = f.result()
                except Exception:
                    continue
                if r2["ok"]:
                    type_results[r2["kind"]].append(r2)
        for kind in ("raw", "zip"):
            type_results[kind].sort(key=lambda x: x["speed_mbps"], reverse=True)
            if type_results[kind]:
                log(f"{kind.upper()} 镜像速度排名: " + " > ".join(r["name"] for r in type_results[kind][:8]))

    mirror_ranking = [r["name"] for r in results if r["kind"] == "mirror" and r["ok"]]
    hf_mirror_ranking = [r["name"].replace("(HF)", "") for r in results
                         if r["kind"] == "hf_mirror" and r["ok"]]
    gh_direct = next((r for r in results if r["name"] == "GitHub原始链接(无代理)"), None)
    gh_proxy = next((r for r in results if r["name"] == "GitHub原始链接(走系统代理)"), None)
    hf_direct = next((r for r in results if r["name"] == "HuggingFace原始链接(无代理)"), None)
    hf_proxy = next((r for r in results if r["name"] == "HuggingFace原始链接(走系统代理)"), None)

    # 直连是否优于最快镜像（含代理直连）
    best_mirror_speed = max(
        (r["speed_mbps"] for r in results if r["kind"] == "mirror"), default=0.0)
    gh_best_direct = max(
        [x for x in (gh_direct, gh_proxy) if x and x["ok"]],
        key=lambda x: x["speed_mbps"], default=None)
    hf_best_direct = max(
        [x for x in (hf_direct, hf_proxy) if x and x["ok"]],
        key=lambda x: x["speed_mbps"], default=None)

    out = {
        "ranking": results,
        "mirrorRanking": mirror_ranking,
        "hfMirrorRanking": hf_mirror_ranking,
        "rankingByType": {k: [r["name"] for r in v] for k, v in type_results.items()},
        "bestGithubDirect": bool(gh_best_direct and gh_best_direct["speed_mbps"] > best_mirror_speed),
        "bestHfDirect": bool(hf_best_direct and hf_best_direct["speed_mbps"] > best_mirror_speed),
        "proxyAvailable": bool(proxy),
    }
    # 结果缓存（供 fallback 排序使用）
    try:
        from backend.src.utils.github_mirror import github_mirror_manager
        github_mirror_manager.set_benchmark_result(out)
    except Exception:
        pass
    if mirror_ranking:
        log("GitHub 镜像速度排名: " + " > ".join(mirror_ranking))
    if hf_mirror_ranking:
        log("HuggingFace 镜像速度排名: " + " > ".join(hf_mirror_ranking))
    if out["bestGithubDirect"]:
        log("直连（含代理）快于镜像，后续 GitHub 下载将优先直连")
    if out["bestHfDirect"]:
        log("直连（含代理）快于镜像，后续模型下载将优先直连")
    return out