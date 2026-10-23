"""
补齐便携包 Python 开发文件（include/ 与 libs/）

ComfyUI 便携包使用 Python embeddable 版，**天然没有 include/ 和 libs/**——
导致需要编译的自定义节点（如 SageAttention、triton 相关）无法构建。

本模块：探测便携包 Python 版本 → 下载对应完整安装包（华为云/阿里云/python.org 镜像）
→ /layout 展开 msi → msiexec 管理安装提取 → 复制 include/ + libs/ 到 python_embeded。
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional


def _version_tuple(v: str) -> Optional[tuple]:
    try:
        nums = v.strip().lstrip("Python ").split(".")
        return tuple(int(x) for x in nums[:3])
    except Exception:
        return None


def detect_python_version(python_exe: Path) -> Optional[str]:
    """探测 python.exe 版本（如 3.13.14）"""
    for args in (["--version"], ["-V"]):
        try:
            r = subprocess.run([str(python_exe), *args], capture_output=True, text=True,
                               timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = (r.stdout or "") + (r.stderr or "")
            for token in out.replace("Python ", "").split():
                if token and token[0].isdigit() and token.count(".") >= 1:
                    return token.strip()
        except Exception:
            continue
    return None


def ensure_python_dev_headers(python_exe: Path,
                              log_fn: Optional[Callable[[str], None]] = None) -> bool:
    """
    确保 python_embeded 下的 include/ 与 libs/ 完整。

    Returns:
        bool: 是否已就绪（或原本就有）
    """
    log = log_fn or (lambda m: print(m))
    try:
        emb = Path(python_exe).parent
        inc, libs = emb / "include", emb / "libs"
        if inc.is_dir() and (inc / "Python.h").is_file() and libs.is_dir() and any(libs.glob("python*.lib")):
            return True

        ver = detect_python_version(Path(python_exe))
        if not ver:
            log("  无法探测便携包 Python 版本，跳过 include/libs 补全")
            return False
        vt = _version_tuple(ver)
        if not vt:
            return False
        log(f"  便携包 Python {ver}，缺少 include/libs，开始补全...")

        # ---- 方案 A：python-build-standalone install_only 包（纯解压，最稳定）----
        # 含完整 include/ + libs/，无需安装器/msiexec/管理员权限；3.13 系列 ABI 兼容
        if _try_standalone(vt, inc, libs, log):
            log(f"  include/ 与 libs/ 已补全到 {emb.name}")
            return True

        mirrors = [
            f"https://mirrors.huaweicloud.com/python/{ver}/python-{ver}-amd64.exe",
            f"https://mirrors.aliyun.com/python-release/windows/python-{ver}-amd64.exe",
            f"https://www.python.org/ftp/python/{ver}/python-{ver}-amd64.exe",
        ]
        work = Path(tempfile.mkdtemp(prefix="pydev_"))
        try:
            pkg = work / f"python-{ver}-amd64.exe"
            ok = _download(mirrors, pkg, log)
            if not ok:
                log("  完整安装包下载失败，跳过 include/libs 补全")
                return False

            # 官方安装器静默安装到临时目录（Include_dev=1 → 带 include/libs）
            # 相比 /layout+msiexec，这是标准安装流程，100% 产出完整 include/libs
            tmp_py = work / "pyinstall"
            log("  静默安装完整 Python 到临时目录（取 include/libs）...")
            # 关键：/quiet 默认 SimpleInstall=1（只装 core/exe/lib/pip），
            # 会把 Include_dev 等组件开关全部忽略 → 必须 SimpleInstall=0
            install_args = [
                str(pkg), "/quiet",
                f"TargetDir={tmp_py}",
                "SimpleInstall=0", "InstallAllUsers=0", "PrependPath=0", "Shortcuts=0",
                "Include_launcher=0", "AssociateFiles=0",
                "Include_exe=1", "Include_lib=1", "Include_dev=1",
                "Include_test=0", "Include_pip=0", "Include_doc=0", "Include_tcltk=0",
            ]
            try:
                r = subprocess.run(install_args, timeout=900, capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                log(f"  安装器退出码: {r.returncode}")
            except Exception as e:
                log(f"  安装器执行失败: {e}")

            src_inc = tmp_py / "include"
            src_libs = tmp_py / "libs"
            if not (src_inc / "Python.h").is_file() or not src_libs.is_dir():
                # 兜底 1：搜索本机已安装的 Python 3.13（安装器 TargetDir 未生效时常见）
                log("  安装结果不完整，搜索本机已装 Python 3.13...")
                import os as _os
                vt_t = _version_tuple(ver) or (3, 13, 0)
                cands = [
                    Path(_os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
                    Path("C:/Python313"), Path("C:/Python3.13"),
                    Path("C:/Program Files/Python313"), Path("C:/Program Files/Python3.13"),
                ]
                found = None
                for c in cands:
                    if not c.exists():
                        continue
                    pool = [c] if (c / "include").is_dir() else [d for d in c.glob("Python313*") if d.is_dir()]
                    for d in pool:
                        if (d / "include" / "Python.h").is_file() and (d / "libs").is_dir():
                            found = d
                            break
                    if found:
                        break
                if found:
                    log(f"  使用本机已有 Python 环境: {found}")
                    src_inc, src_libs = found / "include", found / "libs"
                else:
                    # 兜底 2：msiexec /a 解 dev.msi（部分环境安装器受限时）
                    log("  尝试 msiexec 兜底...")
                layout = work / "layout"
                layout.mkdir(exist_ok=True)
                try:
                    subprocess.run([str(pkg), "/layout", str(layout), "/quiet"],
                                   timeout=600, capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except Exception:
                    pass
                extract = work / "extract"
                extract.mkdir(exist_ok=True)
                for msi in list(layout.glob("*dev*.msi")) + list(layout.glob("dev.msi")):
                    subprocess.run(["msiexec", "/a", str(msi), f"TARGETDIR={extract}", "/qn"],
                                   timeout=600, capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                src_inc = next((q for q in extract.rglob("include") if (q / "Python.h").is_file()), None)
                src_libs = next((q for q in extract.rglob("libs") if any(q.glob("python*.lib"))), None)

            if src_inc is None or src_libs is None or not (Path(src_inc) / "Python.h").is_file():
                log("  未能获得 include/libs（安装器与 msiexec 均失败）")
                return False

            if inc.exists():
                shutil.rmtree(inc, ignore_errors=True)
            shutil.copytree(src_inc, inc)
            if libs.exists():
                shutil.rmtree(libs, ignore_errors=True)
            shutil.copytree(src_libs, libs)
            log(f"  include/ 与 libs/ 已补全到 {emb.name}")
            return True
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except Exception as e:
        log(f"  include/libs 补全异常: {e}")
        return False


def _copy_inc_libs(src_root: Path, inc: Path, libs: Path, log, emb_name: str):
    """把 src_root 下的 include/ + libs/ 拷入便携包环境"""
    src_inc = src_root / "include"
    src_libs = src_root / "libs"
    if not (src_inc / "Python.h").is_file() or not src_libs.is_dir():
        return False
    if inc.exists():
        shutil.rmtree(inc, ignore_errors=True)
    shutil.copytree(src_inc, inc)
    if libs.exists():
        shutil.rmtree(libs, ignore_errors=True)
    shutil.copytree(src_libs, libs)
    log(f"  include/ 与 libs/ 已补全到 {emb_name}")
    return True


_STANDALONE_TAGS = ["20261013", "20260930", "20260916", "20260902", "20250819",
                    "20250805", "20250722", "20250708", "20250624", "20250610"]


def _try_standalone(vt: tuple, inc: Path, libs: Path, log) -> bool:
    """
    尝试 python-build-standalone 的 install_only 包（纯解压取 include/libs）。

    3.13 系列 C ABI 稳定，跨补丁版本（如 3.13.16 → 3.13.14）头文件/导入库通用
    （导入库名为 python313.lib，不含补丁号）。直接把 include/libs 拷入目标。
    """
    try:
        import tarfile
        work = Path(tempfile.mkdtemp(prefix="pbs_"))
        try:
            # 3.13 系列 ABI 稳定：直接用已知存在的 3.13.16 包（含 include/python313.lib，
            # 跨补丁版本通用，导入库名 python313.lib 不含补丁号）。3.13.14 无对应包。
            targets = ["cpython-3.13.16"]
            if vt[2] == 16:
                targets = [f"cpython-{'.'.join(map(str, vt))}"]
            for base_ver in targets:
                for tag in _STANDALONE_TAGS:
                    cand = f"{base_ver}%2B{tag}-x86_64-pc-windows-msvc-install_only.tar.gz"
                    urls = [
                        f"https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/{cand}",
                        f"https://cdn.gh-proxy.org/https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/{cand}",
                        f"https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/{cand}",
                    ]
                    pkg = work / cand
                    if _download(urls, pkg, log):
                        extract = work / "x"
                        extract.mkdir(exist_ok=True)
                        with tarfile.open(pkg, "r:gz") as tf:
                            tf.extractall(extract)
                        root = next((d for d in extract.rglob("include") if (d / "Python.h").is_file()), None)
                        if root:
                            note = "" if base_ver.endswith(str(vt[2])) else "（同系列 ABI 兼容）"
                            log(f"  [standalone] 从 python-build-standalone 取得 include/libs{note}")
                            # 立即拷入目标（临时目录随后会被清理）
                            if _copy_inc_libs(root.parent, inc, libs, log, inc.parent.name):
                                return True
            return False
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except Exception as e:
        logger.debug(f"[PythonDevHeaders] standalone 方案失败: {e}")
        return False


def _download(urls, dest: Path, log) -> bool:
    """下载安装包（尽量用 aria2 多线程，失败回退 requests）"""
    try:
        from backend.src.utils.aria2_helper import aria2_download, find_aria2
        if find_aria2():
            if aria2_download(list(urls), dest, None, 0, log_fn=log, max_connections=8):
                return dest.is_file() and dest.stat().st_size > 5 * 1024 * 1024
    except Exception:
        pass
    try:
        import requests
        for u in urls:
            try:
                with requests.get(u, stream=True, timeout=(15, 120), allow_redirects=True) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                if dest.stat().st_size > 5 * 1024 * 1024:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False
