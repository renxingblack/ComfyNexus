# -*- mode: python ; coding: utf-8 -*-
import os
import sys


def _opt_datas(entries):
    """
    过滤掉不存在的可选资源。

    LibreHardwareMonitorLib 是**可选**的硬件监控组件：
    backend/src/core/monitor/hardware_monitor.py 在找不到 DLL 时会自行降级
    （只损失 CPU 温度/功耗读数，不影响应用启动）。

    但 PyInstaller 遇到缺失路径会直接 ERROR 中止整个打包，
    导致没装该组件的开发者完全无法产出 exe。
    这里把不存在的路径剔除并给出提示，打包能继续。
    """
    present = []
    missing = []
    for src, dst in entries:
        if os.path.exists(src):
            present.append((src, dst))
        else:
            missing.append(src)

    if missing:
        print("[spec] 跳过不存在的可选资源（相关功能会自动降级）:")
        for m in missing:
            print(f"  - {m}")
    return present


block_cipher = None

# 可选资源：存在才打包
_OPTIONAL_DATAS = [
    (os.path.join('backend', 'lib', 'LibreHardwareMonitor'), os.path.join('lib', 'LibreHardwareMonitor')),
    (os.path.join('backend', 'lib', 'librehardwaremonitorlib', 'runtimes'), os.path.join('lib', 'librehardwaremonitorlib', 'runtimes')),
]

# 必需资源：缺失必须报错
_REQUIRED_DATAS = [
    ('dist', 'dist'),
    ('assets', 'assets'),
    ('comfy_nexus_version.py', '.'),
    # 版本更新源（v1.3.0 日志等）——更新日志弹窗的本地兜底数据
    (os.path.join('..', 'version.json'), '.'),
    ('backend/__init__.py', 'backend'),
    (os.path.join('backend', 'src'), os.path.join('backend', 'src')),
    (os.path.join('backend', 'models', 'nsfw.onnx'), os.path.join('models')),
    (os.path.join('backend', 'lib', 'webview2_netcore'), os.path.join('backend', 'lib', 'webview2_netcore')),
]

# 防自递归：datas 里的 ('dist','dist') 会把 source-code/dist 整个收进 _internal/dist，
# 若其中残留上一次的打包产物（dist/ComfyNexus），每次打包都会把产物自身再打包一遍，
# 体积滚雪球（实测 328MB -> 464MB）。COLLECT 会重建它，打包开始时先删是安全的。
import shutil as _shutil_pre
_PREV_OUTPUT = os.path.join('dist', 'ComfyNexus')
if os.path.isdir(_PREV_OUTPUT):
    _shutil_pre.rmtree(_PREV_OUTPUT)
    print("[spec] 已清除上一次的打包产物（防 datas 自递归）")

_missing_required = [s for s, _ in _REQUIRED_DATAS if not os.path.exists(s)]
if _missing_required:
    print("[spec] 错误：缺少必需资源:")
    for m in _missing_required:
        print(f"  - {m}")
    raise SystemExit("[spec] 必需资源缺失，无法打包")

# ---------------------------------------------------------------------------
# version.json 的「发布包内副本」必须清空 file_size / file_hash（自指陷阱）
#
# 为什么必须这么做：zip 里包含 version.json，而 version.json 又记录这个 zip 的
# file_size/file_hash。若把真实值打进包里，就会陷入死循环 ——
# 改 hash 让 zip 变、zip 变又让 hash 变，**永远收敛不了**
# （实测反复打 3 次 zip，hash 每次都不同）。
#
# 为什么可以清空：运行时 `get_local_changelog()` 只读
# `version/release_notes/published_at`，**根本不读这两个字段**；
# 它们只用于远端 UpdateChecker 拉 raw version.json 校验下载包。
# 所以「包内=占位值、仓库根=真实值」是自洽的。
#
# 做法：ds 阶段把 ../version.json 换成临时副本（已清零），
# 不修改仓库根的真实文件。
# ---------------------------------------------------------------------------
_VERSION_SRC = os.path.abspath(os.path.join('..', 'version.json'))
_VERSION_STRIPPED = os.path.join(
    os.path.abspath(os.path.join('build', '_spec_tmp')), 'version.json')
try:
    import json as _json
    _vd = _json.loads(_VERSION_SRC and open(_VERSION_SRC, encoding='utf-8').read())
    _vd['file_size'] = 0
    _vd['file_hash'] = ''
    os.makedirs(os.path.dirname(_VERSION_STRIPPED), exist_ok=True)
    with open(_VERSION_STRIPPED, 'w', encoding='utf-8') as _f:
        _f.write(_json.dumps(_vd, ensure_ascii=False, indent=2))
    _REQUIRED_DATAS = [
        (_VERSION_STRIPPED if s == os.path.join('..', 'version.json') else s, d)
        for s, d in _REQUIRED_DATAS
    ]
    print(f"[spec] version.json 已置空 file_size/file_hash 后收进包内"
          f"（避免 hash 自指；仓库根保持真实值 {_vd.get('version')}）")
except Exception as _e:
    raise SystemExit(f"[spec] 处理 version.json 失败: {_e}")


def _collect_extra_dlls():
    """
    收集 PyInstaller 不会自动带上、但 pyd 硬依赖的运行时 DLL。

    缺任何一个都会让 exe 在 import 阶段直接崩，例如：
        ImportError: DLL load failed while importing _ctypes: 找不到指定的模块。
    根因是 PyInstaller 6.x 的 hook 没有覆盖 Python 3.13 拆分出去的 DLL。

    已实测缺失清单（用 pefile 扫 _internal/*.pyd 的 import 表得出）：
        libffi-8.dll        <- _ctypes.pyd
        libcrypto-3-x64.dll <- _hashlib.pyd / _ssl.pyd
        libssl-3-x64.dll    <- _ssl.pyd
        sqlite3.dll         <- _sqlite3.pyd
        pywintypes313.dll   <- win32api.pyd / win32ui.pyd（pywin32）

    来源优先级：
        1) venv 的 base Python 目录（pyvenv.cfg 的 home）—— 版本绝对匹配
        2) pywin32_system32
        3) 其它已知的 python.org 安装目录
    """
    import sysconfig
    import glob as _glob

    candidates = []

    # 1) venv 的 base prefix（最可靠：与打包用的解释器同版本）
    base_prefix = getattr(sys, 'base_prefix', sys.prefix)
    for d in (os.path.join(base_prefix, 'DLLs'), base_prefix):
        if os.path.isdir(d):
            candidates.append(d)

    # 2) pywin32 的 DLL 目录
    for pat in (r'Lib\site-packages\pywin32_system32',
                r'lib\site-packages\pywin32_system32'):
        p = os.path.join(sys.prefix, pat)
        if os.path.isdir(p):
            candidates.append(p)

    # 3) 常见的 python.org 安装目录（libffi 只在这些发行版里）
    for extra in (r'C:\Python314\DLLs', r'C:\Python313\DLLs', r'C:\Python312\DLLs'):
        if os.path.isdir(extra):
            candidates.append(extra)

    # 注意：只取与当前解释器同版本的 OpenSSL DLL（lib*3-x64.dll）。
    # python 3.13 用 -x64 后缀，3.14 改成了 lib*3.dll，两个 ABI 不兼容，
    # 混在一起会优先加载到错版本，导致 _ssl/_hashlib 在运行时报错。
    import re as _re
    _ver = f'{sys.version_info.major}.{sys.version_info.minor}'   # 如 '3.13'
    _openssl = f'libcrypto-{_ver.replace(".", "")}-x64.dll'       # libcrypto-313-x64.dll
    _libssl = f'libssl-{_ver.replace(".", "")}-x64.dll'           # libssl-313-x64.dll
    # 3.13 之前没有 -x64 后缀
    if not os.path.exists(os.path.join(base_prefix, 'DLLs', _openssl)):
        _openssl = 'libcrypto-3-x64.dll'
        _libssl = 'libssl-3-x64.dll'

    wanted = {
        'libffi-8.dll',
        _openssl,
        _libssl,
        'sqlite3.dll',
        f'pywintypes{sys.version_info.major}{sys.version_info.minor}.dll',
    }
    # pywintypes 的实际文件名固定为 pywintypesXY.dll
    wanted = {w if w.startswith(('libffi', 'libcrypto', 'libssl', 'sqlite3')) else 'pywintypes313.dll'
              for w in wanted}

    found = {}
    for d in candidates:
        for name in wanted:
            if name in found:
                continue
            # libffi 只接受 3.13 的 x64 版本名，避免混进不兼容的 3.14 构建
            p = os.path.join(d, name)
            if os.path.exists(p):
                found[name] = p

    missing = wanted - set(found)
    if missing:
        print(f"[spec] 警告：未找到 {len(missing)} 个运行时 DLL: {', '.join(sorted(missing))}")
        print(f"[spec]   搜索目录: {[c for c in candidates]}")

    print(f"[spec] 补收集运行时 DLL {len(found)}/{len(wanted)} 个:")
    for name in sorted(found):
        print(f"    {name}  <-  {found[name]}")

    # 目标目录必须显式给 '.'（PyInstaller 6.x 拒绝空 DEST_DIR），
    # 但传 '.' 时 COLLECT 会把源所在目录名一起带出来 ——
    # pywintypes313.dll 会落到 _internal/pywin32_system32/ 下，
    # 而 win32api.pyd 找的是 _internal 根目录，照样 ImportError。
    # 解法：先把每个 DLL 复制到临时扁平目录，再从那里收集，
    # 这样源目录名是无关的临时名，COLLECT 会把文件平铺到 _internal 根。
    import tempfile as _tf
    _flat = _tf.mkdtemp(prefix='cn_dlls_')
    _entries = []
    for p in found.values():
        _dst = os.path.join(_flat, os.path.basename(p))
        import shutil as _sh
        _sh.copy2(p, _dst)
        _entries.append((_dst, '.'))
    print(f"[spec]   已平铺到临时目录: {_flat}")
    return _entries


_EXTRA_DLLS = _collect_extra_dlls()

a = Analysis(
    ['backend/main.py'],
    pathex=[os.path.abspath('.')],
    binaries=_EXTRA_DLLS,
    datas=_REQUIRED_DATAS + _opt_datas(_OPTIONAL_DATAS),
    hiddenimports=[
        'webview',
        'webview.platforms.winforms',
        'py7zr',  # 0基础安装：解压 ComfyUI 便携包
        'comfy_nexus_version',
        'backend',
        'backend.src',
        'backend.src.bridge',
        'backend.src.bridge.api',
        'backend.src.bridge.controllers',
        'backend.src.core',
        'backend.src.core.config',
        'backend.src.core.env',
        'backend.src.core.monitor',
        'backend.src.core.process',
        'backend.src.core.ai',
        'backend.src.core.ai.providers',
        'backend.src.core.ai.search',
        'backend.src.core.ai.migrations',
        'backend.src.core.plugin',
        'backend.src.core.marketplace',
        'backend.src.core.dependency',
        'backend.src.core.lora',
        'backend.src.core.prompt_library',
        'backend.src.core.updater',
        'backend.src.utils',
        # 图标/创作者信息缓存模块（2026-10-22 新增，磁盘源码优先引导已能覆盖，
        # 这里显式列出作为 PYZ 兜底，避免引导失效时 import 失败）
        'backend.src.utils.icon_cache',
        'backend.src.utils.creator_info',
        'backend.src.ui',
        'backend.src.gallery',
        'backend.src.gallery.nsfw',
        'onnxruntime',
        'yaml',
        'websockets',
        'psutil',
        'pathlib',
        'json',
        'asyncio',
        'subprocess',
        'socket',
        'cv2',
        # 说明：原 spec 里还声明了 aiofiles / httpx / dotenv / tkinter，
        # 但 backend/src 下没有任何代码 import 它们（已 grep 确认），
        # 且它们也不在 requirements.txt 里。属于历史遗留的僵尸声明，
        # 只会让每次打包都刷四条 "Hidden import not found" ERROR。
        # 已移除；若将来真的用到了，记得同步加进 requirements.txt。
        # tkinter 是标准库但本机 Python 未安装，api.py 已改为容错导入
        # （没有 tkinter 时仅「保存图片」对话框降级，其余功能不受影响）。
    ],
    hookspath=[os.path.join(os.path.abspath('.'), 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=False,
)

def filter_googleapiclient_datas(datas_list):
    filtered = []
    excluded_count = 0
    for item in datas_list:
        source = item[0] if isinstance(item, tuple) else str(item)
        source_lower = source.lower().replace('\\', '/')
        if 'googleapiclient' in source_lower and 'discovery_cache/documents' in source_lower:
            if 'customsearch.v1.json' in source_lower:
                filtered.append(item)
            else:
                excluded_count += 1
        else:
            filtered.append(item)
    print(f"[spec] googleapiclient: 排除了 {excluded_count} 个不需要的 discovery documents")
    return filtered

def filter_cv2_datas(datas_list):
    filtered = []
    excluded_count = 0
    for item in datas_list:
        source = item[0] if isinstance(item, tuple) else str(item)
        source_lower = source.lower()
        if 'haarcascade' in source_lower:
            excluded_count += 1
        else:
            filtered.append(item)
    print(f"[spec] cv2: 排除了 {excluded_count} 个 haarcascade 文件")
    return filtered

a.datas = filter_googleapiclient_datas(a.datas)
a.datas = filter_cv2_datas(a.datas)

# ============================================
# 打包瘦身：排除不需要的大文件
# ============================================
def filter_bloat(items_list, item_type='datas'):
    """统一过滤 datas 和 binaries 中的冗余文件"""
    filtered = []
    excluded = {}
    
    exclude_patterns = [
        # cv2: 类型提示文件，运行时不需要
        ('cv2/__init__.pyi', 'cv2 类型提示'),
        ('cv2\\__init__.pyi', 'cv2 类型提示'),
        # Pillow: AVIF 格式支持（7.5MB），项目不使用 AVIF
        ('_avif.cp', 'Pillow AVIF 插件'),
        # LibreHardwareMonitor: 调试符号和文档
        ('.pdb', 'PDB 调试符号'),
        # fake_useragent: 浏览器数据库（2.5MB）
        ('fake_useragent/data/browsers.jsonl', 'fake_useragent 数据库'),
        ('fake_useragent\\data\\browsers.jsonl', 'fake_useragent 数据库'),
        # onnxruntime: 排除不需要的子模块（只保留 capi 推理核心）
        ('onnxruntime/transformers', 'onnxruntime transformers'),
        ('onnxruntime\\transformers', 'onnxruntime transformers'),
        ('onnxruntime/quantization', 'onnxruntime quantization'),
        ('onnxruntime\\quantization', 'onnxruntime quantization'),
        ('onnxruntime/tools', 'onnxruntime tools'),
        ('onnxruntime\\tools', 'onnxruntime tools'),
        ('onnxruntime/datasets', 'onnxruntime datasets'),
        ('onnxruntime\\datasets', 'onnxruntime datasets'),
        # onnx: collect_all 带进来的多余依赖，推理不需要
        ('onnxscript', 'onnxscript'),
        # LibreHardwareMonitorLib: 只保留 win-x64，排除其他架构
        ('librehardwaremonitorlib/runtimes/win-x86', 'LibreHardwareMonitorLib win-x86'),
        ('librehardwaremonitorlib\\runtimes\\win-x86', 'LibreHardwareMonitorLib win-x86'),
        ('librehardwaremonitorlib/runtimes/win-arm64', 'LibreHardwareMonitorLib win-arm64'),
        ('librehardwaremonitorlib\\runtimes\\win-arm64', 'LibreHardwareMonitorLib win-arm64'),
    ]
    
    for item in items_list:
        source = item[0] if isinstance(item, tuple) else str(item)
        source_lower = source.lower().replace('\\', '/')
        
        should_exclude = False
        for pattern, reason in exclude_patterns:
            if pattern.lower() in source_lower:
                excluded[reason] = excluded.get(reason, 0) + 1
                should_exclude = True
                break
        
        if not should_exclude:
            filtered.append(item)
    
    total_excluded = sum(excluded.values())
    if total_excluded > 0:
        print(f"[spec] 瘦身过滤 ({item_type}): 共排除 {total_excluded} 个文件")
        for reason, count in sorted(excluded.items()):
            print(f"  - {reason}: {count} 个")
    
    return filtered

a.datas = filter_bloat(a.datas, 'datas')
a.binaries = filter_bloat(a.binaries, 'binaries')

# ============================================
# .NET 8 coreclr: 确保 pywebview lib 目录里是 netcoreapp3.0 版本的 WebView2 DLL
# 直接替换源文件，让 PyInstaller hook 自然收集正确的版本
# ============================================
import shutil as _shutil

_netcore_dir = os.path.join('backend', 'lib', 'webview2_netcore')
_webview_lib = os.path.join(os.path.abspath('.'), '.venv', 'Lib', 'site-packages', 'webview', 'lib')

if os.path.isdir(_webview_lib) and os.path.isdir(_netcore_dir):
    for _dll in ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']:
        _src = os.path.join(_netcore_dir, _dll)
        _dst = os.path.join(_webview_lib, _dll)
        if os.path.exists(_src):
            _shutil.copy2(_src, _dst)
            print(f"[spec] .NET 8: copied netcoreapp3.0 {_dll} to pywebview lib")

    # 清理 .bak 备份文件
    for _f in os.listdir(_webview_lib):
        if _f.endswith('.bak'):
            os.remove(os.path.join(_webview_lib, _f))
            print(f"[spec] .NET 8: removed {_f}")

# 排除 .bak 文件（以防万一）
a.binaries = [item for item in a.binaries if not item[0].endswith('.bak')]
a.datas = [item for item in a.datas if not item[0].endswith('.bak')]

# ============================================
# .NET 8 coreclr: 直接 patch venv 中 pywebview 的 winforms.py
# 该类的 OpenFolderDialog 使用反射访问 .NET Framework 内部类型，在 .NET 8 下不存在
# 必须在打包前 patch 源文件，因为 PyInstaller 会编译 .pyc 打包进去
# ============================================
import site
_winforms_candidates = [
    os.path.join(os.path.abspath('.'), '.venv', 'Lib', 'site-packages', 'webview', 'platforms', 'winforms.py'),
]
# 也搜索 site-packages
for sp in site.getsitepackages() if hasattr(site, 'getsitepackages') else []:
    _winforms_candidates.append(os.path.join(sp, 'webview', 'platforms', 'winforms.py'))

for _wf_path in _winforms_candidates:
    if os.path.exists(_wf_path):
        with open(_wf_path, 'r', encoding='utf-8') as _f:
            _wf_content = _f.read()
        
        if '# PATCHED_FOR_DOTNET8' in _wf_content:
            print(f"[spec] .NET 8: winforms.py already patched: {_wf_path}")
            break
        
        _modified = False

        # Patch 1: 修复 _is_chromium 检测（精简版 Windows 没有 .NET Framework 注册表键）
        _old_is_chromium = "is_chromium = not is_cef and _is_chromium() and forced_gui_ != 'mshtml'"
        _new_is_chromium = "is_chromium = not is_cef and (forced_gui_ == 'edgechromium' or _is_chromium()) and forced_gui_ != 'mshtml'  # PATCHED_FOR_DOTNET8"
        if _old_is_chromium in _wf_content:
            _wf_content = _wf_content.replace(_old_is_chromium, _new_is_chromium)
            _modified = True
            print(f"[spec] .NET 8: Patched _is_chromium detection")

        # Patch 2: 替换 OpenFolderDialog
        if 'FileDialogNative+IFileDialog' in _wf_content:
            _marker = "class OpenFolderDialog:"
            if _marker in _wf_content:
                _idx = _wf_content.index(_marker)
                _rest = _wf_content[_idx:]
                _lines = _rest.split('\n')
                _end = len(_lines)
                for _li, _ln in enumerate(_lines[1:], 1):
                    _s = _ln.strip()
                    if _ln and not _ln[0].isspace() and _s and not _s.startswith('#'):
                        _end = _li
                        break
                
                _repl = '''class OpenFolderDialog:  # PATCHED_FOR_DOTNET8
    """Folder dialog compatible with .NET 8"""
    foldersFilter = 'Folders|\\n'

    @classmethod
    def show(cls, parent=None, initialDirectory=None, allow_multiple=False, title=None):
        dialog = WinForms.FolderBrowserDialog()
        if initialDirectory:
            dialog.SelectedPath = initialDirectory
        if title:
            dialog.Description = title
        result = dialog.ShowDialog()
        if result == WinForms.DialogResult.OK:
            return (dialog.SelectedPath,)
        return None

'''
                _wf_content = _wf_content[:_idx] + _repl + '\n'.join(_lines[_end:])
                _modified = True
                print(f"[spec] .NET 8: Patched OpenFolderDialog")

        if _modified:
            with open(_wf_path, 'w', encoding='utf-8') as _f:
                _f.write(_wf_content)
            _pycache = os.path.join(os.path.dirname(_wf_path), '__pycache__')
            if os.path.exists(_pycache):
                import shutil
                shutil.rmtree(_pycache, ignore_errors=True)
            print(f"[spec] .NET 8: winforms.py patched: {_wf_path}")
        break

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ComfyNexus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    uac_admin=True,
    manifest='backend/uac.manifest',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ComfyNexus',
)

# ============================================
# 把 pywin32 的运行时 DLL 从子目录提到 _internal 根
# ============================================
# PyInstaller 的 pywin32 hook 固定把它们放到 _internal/pywin32_system32/，
# 但 win32api.pyd / win32ui.pyd 是按 _internal 根目录去 LoadLibrary 的，
# 找不到就在 import 阶段报 "DLL load failed"。
# 与其改 hook（脆弱），不如打包完成后直接挪位置。
_PYWIN32_SRC = os.path.join('dist', 'ComfyNexus', '_internal', 'pywin32_system32')
_PYWIN32_DST = os.path.join('dist', 'ComfyNexus', '_internal')

if os.path.isdir(_PYWIN32_SRC):
    import shutil as _sh3
    _moved = []
    for _f in os.listdir(_PYWIN32_SRC):
        if _f.lower().endswith('.dll'):
            _sh3.copy2(os.path.join(_PYWIN32_SRC, _f), os.path.join(_PYWIN32_DST, _f))
            _moved.append(_f)
    print(f"[spec] pywin32 DLL 已提到 _internal 根: {', '.join(_moved)}")
    _sh3.rmtree(_PYWIN32_SRC, ignore_errors=True)

# ============================================
# 拷贝内置 7zr.exe（0基础安装解压 BCJ2 便携包用）到 <exe同级>/tools/
_7ZR_SRC = os.path.join('backend', 'tools', '7zr.exe')
_7ZR_DEST = os.path.join('dist', 'ComfyNexus', 'tools', '7zr.exe')
if os.path.isfile(_7ZR_SRC):
    os.makedirs(os.path.dirname(_7ZR_DEST), exist_ok=True)
    import shutil as _sh3
    _sh3.copy2(_7ZR_SRC, _7ZR_DEST)
    print(f"[spec] 内置 7zr.exe 已拷贝到 {_7ZR_DEST}")
else:
    print(f"[spec] !! 警告：找不到 {_7ZR_SRC}（BCJ2 便携包解压将依赖系统 7-Zip）")

# 拷贝内置 aria2c.exe（大文件多线程下载加速）到 <exe同级>/tools/
_ARIA2_SRC = os.path.join('backend', 'tools', 'aria2c.exe')
_ARIA2_DEST = os.path.join('dist', 'ComfyNexus', 'tools', 'aria2c.exe')
if os.path.isfile(_ARIA2_SRC):
    import shutil as _sh4
    _sh4.copy2(_ARIA2_SRC, _ARIA2_DEST)
    print(f"[spec] 内置 aria2c.exe 已拷贝到 {_ARIA2_DEST}")
else:
    print(f"[spec] !! 警告：找不到 {_ARIA2_SRC}（大文件将退回单线程下载）")

# 拷贝内置 MinGit 到 <exe同级>/tools/mingit
# ============================================
# 为什么必须后处理而不能用 datas：
#   backend/src/utils/paths.py 的 get_mingit_dir() 在打包环境下返回
#   <exe同级>/tools/mingit（即 dist/ComfyNexus/tools/mingit），
#   而 PyInstaller 的 datas 一律解压到 _internal 下，路径对不上。
#
# 少了这一步的后果（实测）：
#   GitManager 检测不到内置 MinGit -> main.py 判定"Git 不可用"
#   -> 弹出 Git 配置引导窗口 -> 用户没交互 -> 应用直接 return 退出
#   -> 表现为"双击 exe 后窗口一闪就没了"。
#   README 承诺的"内置 MinGit，无需自装 Git"也随之落空。
_MINGIT_SRC = os.path.join('backend', 'MinGit-2.53.0-64-bit')
_MINGIT_DEST = os.path.join('dist', 'ComfyNexus', 'tools', 'mingit')

if os.path.isdir(_MINGIT_SRC):
    if os.path.isdir(_MINGIT_DEST):
        import shutil as _sh
        _sh.rmtree(_MINGIT_DEST, ignore_errors=True)
    os.makedirs(os.path.dirname(_MINGIT_DEST), exist_ok=True)
    import shutil as _sh2
    _sh2.copytree(_MINGIT_SRC, _MINGIT_DEST)

    def _dir_size(p):
        total = 0
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    print(f"[spec] 内置 MinGit 已拷贝到 {_MINGIT_DEST} ({_dir_size(_MINGIT_DEST) / 1024 / 1024:.1f} MB)")

    # 校验 git.exe 真的到位，避免又出现"打出来但不可用"
    _git_exe = os.path.join(_MINGIT_DEST, 'cmd', 'git.exe')
    if os.path.exists(_git_exe):
        print(f"[spec]   git.exe OK: {_git_exe}")
    else:
        print(f"[spec]   !! 警告：拷贝后仍找不到 {_git_exe}，运行时可能仍会走引导窗口")
else:
    print(f"[spec] !! 警告：找不到内置 MinGit ({_MINGIT_SRC})，")
    print(f"[spec]    打包出的 exe 首次启动会弹出 Git 配置引导窗口（需手动确认一次）")
