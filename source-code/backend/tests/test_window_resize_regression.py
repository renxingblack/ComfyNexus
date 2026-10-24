"""窗口四角缩放回归测试（静态源码断言）

为什么是静态断言而不是跑真实拖动：
  真实的缩放链路依赖 WebView2 + 真实鼠标 + CDP 派发事件，只能在打包后的
  产物上做端到端验收（见 D:/Downloads/ComfyNexus/_verify_corners.py，28 项断言）。
  但那条链路的几个**关键设计约束**很容易被后来者"顺手优化掉"，
  一旦改错就退回到"拖不动"，而且极难从现象反推原因。
  所以这里用源码级断言把约束钉死：谁改坏了，跑这个测试立刻报错。

覆盖的四个历史故障（都是实测踩出来的）：
  1. 依赖 WM_NCLBUTTONDOWN 模态环 —— WebView2 抢走鼠标捕获，尺寸永远不变。
  2. 只用 GetAsyncKeyState 判松手 —— 合成/远程输入下恒为"已松开"，第 0 帧退出。
  3. GetCursorPos 用错 POINT 结构 —— ctypes 严格类型校验直接 TypeError。
  4. 最大化状态下写回尺寸 —— 把用户拖出来的尺寸覆盖成屏幕工作区尺寸。
"""
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WB = ROOT / "backend" / "src" / "utils" / "window_bounds.py"
API = ROOT / "backend" / "src" / "bridge" / "api.py"
RH = ROOT / "frontend" / "src" / "components" / "layout" / "ResizeHandles.tsx"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def read(p):
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def func_body(src, fname):
    """用 ast 精确取出某函数的源码段（方法在类里也能找到）。

    注意用 ast.walk 而不是只遍历 tree.body：maximizeApp 是类方法，
    在 ClassDef.body 里，顶层遍历会漏掉（这里踩过，导致误判"函数不存在"）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fname:
            # 先按 ast 的 body 精确剔除 docstring（它是函数体第一句 Expr/Constant），
            # 再交给 token 处理 —— docstring 里会写"不用 WM_NCLBUTTONDOWN"这类
            # 历史说明，留着会把"已废弃方案"误判成"仍在使用"。
            body_nodes = list(node.body)
            doc = None
            if (body_nodes and isinstance(body_nodes[0], ast.Expr)
                    and isinstance(body_nodes[0].value, ast.Constant)
                    and isinstance(body_nodes[0].value.value, str)):
                doc = body_nodes[0]
            if doc is not None and len(body_nodes) > 1:
                start = body_nodes[1].lineno - 1
            else:
                start = node.lineno - 1
            end = node.end_lineno or start + 1
            body = "\n".join(lines[start:end])
            # 保留字符串：`corner == "top-left"` 的关键信息就在字符串里
            return strip_comments(body, keep_strings=True)
    return ""


def strip_comments(src, keep_strings=False):
    """去掉 Python 注释（可选保留字符串字面量），只留可执行代码。

    为什么要去注释：本项目的修复都带大段"为什么不用旧方案"的注释，
    里面会提到 WM_NCLBUTTONDOWN、wintypes.POINT 等字样。
    若直接字符串搜索，注释会误命中，把"已废弃的方案"判成"仍在使用"。

    **keep_strings 很关键**：`corner == "top-left"` 这类判断里，
    关键信息本身就在字符串里。默认剥掉 STRING 会让它退化成 `corner==`，
    断言永远匹配不上（这里踩过）。需要比字符串值时传 keep_strings=True。

    返回紧凑拼接的 token 串（不加分隔符），这样跨换行/空格的写法也能匹配，
    配合 compact() 使用。
    """
    out = []
    drop = {tokenize.COMMENT}
    if not keep_strings:
        drop.add(tokenize.STRING)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in drop:
                continue
            if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENCODING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        return src
    return "".join(out)


def compact(s):
    """去掉所有空白，便于跨换行/空格做子串匹配。"""
    return re.sub(r"\s+", "", s or "")


def main():
    wb = read(WB)
    api = read(API)
    rh = read(RH)

    check("三个关键文件都存在", all([wb, api, rh]),
          f"wb={len(wb)} api={len(api)} rh={len(rh)}")

    print("\n[1] 轮询缩放实现存在（不是模态环方案）")
    poll = func_body(wb, "start_polling_resize")
    check("window_bounds 有 start_polling_resize", bool(poll), f"{len(poll)} chars")
    check("轮询使用 GetCursorPos 读全局光标", "GetCursorPos" in poll or
          "_cursor_pos" in poll)
    check("轮询使用 SetWindowPos 驱动尺寸", "SetWindowPos" in poll)
    check("有停止信号机制 _resize_stop", "_resize_stop" in poll)
    check("有最长生存期兜底 _MAX_LIFETIME", "_MAX_LIFETIME" in poll)

    print("\n[2] 不再依赖 WM_NCLBUTTONDOWN 模态环")
    sn = func_body(api, "startNativeResize")
    check("startNativeResize 存在", bool(sn), f"{len(sn)} chars")
    # 用已剥离注释的代码判断：docstring 里会写"不用 WM_NCLBUTTONDOWN"，
    # 直接搜原文件会把说明文字误判成"仍在使用"。
    check("startNativeResize 的可执行代码里不再发 WM_NCLBUTTONDOWN",
          "WM_NCLBUTTONDOWN" not in sn,
          "该调用在 WebView2 下无效（鼠标捕获被子窗口抢走）")
    check("startNativeResize 调用 start_polling_resize",
          "start_polling_resize" in sn)
    check("存在 stopNativeResize 方法", "def stopNativeResize" in api)

    print("\n[3] GetAsyncKeyState 只作兜底，且必须先观测到按下")
    # 关键：必须有 seen_down 前提，否则合成事件下第 0 帧就退出
    check("轮询里有 seen_down 前提判断", "seen_down" in poll,
          "缺了就退化为'合成输入下第0帧退出'")
    check("released_frames 计数在 seen_down 之后才递增",
          "elifseen_down:" in compact(poll),
          "必须 elif seen_down 分支才累加")

    print("\n[4] GetCursorPos 的 POINT 结构一致性")
    check("模块内定义了 POINT 结构", "class POINT" in wb or "POINT = " in wb)
    check("argtypes 用的是模块内 POINT",
          "ctypes.POINTER(POINT)" in compact(wb),
          "传 wintypes.POINT 或自定义结构都会 TypeError")
    # _cursor_pos 内部必须用裸 POINT()，不能是 wintypes.POINT()
    cp = func_body(wb, "_cursor_pos")
    check("_cursor_pos 用裸 POINT() 而非 wintypes.POINT()",
          "POINT()" in cp and "wintypes.POINT()" not in compact(cp),
          cp[:60])

    print("\n[5] 最小尺寸 / 对边固定逻辑")
    check("钳制了最小宽度", "min_w" in poll)
    check("钳制了最小高度", "min_h" in poll)
    check("左上角拖动时改 new_left/new_top",
          'corner=="top-left"' in compact(poll))
    check("从被拖边'顶住'最小尺寸（对边不动）",
          "start_x+start_w-min_w" in compact(poll),
          "缺了会变成'窗口跟着鼠标平移'")

    print("\n[6] 尺寸持久化的两个坑")
    check("api.py 不再调用不存在的 updateSystemSettings",
          "self.updateSystemSettings(" not in api,
          "后端没有这个方法，调用抛 AttributeError 被静默吞掉")
    check("改用 update_settings 并写 appearance.windowSize",
          "update_settings(" in api and '"appearance"' in api)
    check("_window_state 在 update_settings **之后**赋值",
          # 因为 update_settings 内部会把 _window_state 置 None
          api.index("self._window_state = final_rect") >
          api.index("self.update_settings(")
          if "self._window_state = final_rect" in api
          and "self.update_settings(" in api else False,
          "顺序反了会丢位置，还原时窗口跳到 (100,100)")

    print("\n[7] 最大化状态不能污染保存的尺寸（前端）")
    check("ResizeHandles 有 isMaximized 状态", "isMaximized" in rh)
    check("scheduleSave 里排除最大化状态",
          bool(re.search(r"if\s*\(\s*isMaximized\s*\)\s*return", rh)),
          "缺了会把屏幕工作区尺寸写进设置，覆盖用户拖出来的尺寸")
    check("scheduleSave 依赖数组含 isMaximized",
          bool(re.search(r"\}, \[[^\]]*isMaximized[^\]]*\]\)", rh)),
          "漏依赖会读到陈旧的 isMaximized")
    check("前端 mousedown 调用 stopNativeResize 结束信号",
          "stopNativeResize" in rh)

    print("\n[8] 最大化还原必须先 SW_RESTORE")
    mz = func_body(api, "maximizeApp")
    check("maximizeApp 存在", bool(mz), f"{len(mz)} chars")
    check("还原分支调用了 SW_RESTORE(9) 或 ShowWindow",
          "ShowWindow(hwnd,9)" in compact(mz) or "IsZoomed(hwnd)" in compact(mz),
          "WS_MAXIMIZE 未清时 SetWindowPos 改尺寸无效")
    check("maximizeApp 有返回值（便于判定成败）",
          "return{" in compact(mz))

    print("\n[9] 最大化必须用 SW_MAXIMIZE 而不是硬摆矩形")
    mzc = compact(mz)
    check("最大化分支用 ShowWindow(hwnd,3) 设 WS_MAXIMIZE 位",
          "ShowWindow(hwnd,3)" in mzc,
          "只用 SetWindowPos 摆矩形不会置 WS_MAXIMIZE，IsZoomed 恒 False，"
          "导致 isMaximized() 误报、还原走错分支")
    check("isMaximized() 做了真实状态校准",
          "IsZoomed" in compact(func_body(api, "isMaximized")),
          "内部标志有多个写入点，必须用系统真实状态校准")
    check("maximizeApp 先校准标志再判断分支",
          "really_maximized" in mzc,
          "直接信内部标志会在标志失同步时走错分支（点了没反应）")

    print("\n[10] 拖动、保存、还原三者边界口径必须一致（都钳工作区）")
    # 关键教训：曾经让拖动允许拖到整屏（含任务栏区），还原按工作区钳制，
    # 结果「拖成 1680x1080 → 底部热区在 y=1071 落在任务栏下面 → 点不到」；
    # 反过来让还原也放宽成 clamp=False，就变成"窗口盖住任务栏、角够不着"。
    # 唯一自洽的答案是三者都钳工作区。
    check("还原分支用 clamp=True（钳工作区）",
          "apply_window_rect(hwnd,x,y,width,height,clamp=True)" in mzc,
          "放宽会盖住任务栏，底部热区点不到")
    pollc = compact(poll)
    check("拖动边界用 work_rect 而非 monitor_rect",
          "work_right,work_bottom=wr,wb" in pollc,
          "用 mr/mb 会允许拖到任务栏区域，导致底部热区被遮挡")
    check("拖动边界不再用显示器全矩形",
          "work_right,work_bottom=mr,mb" not in pollc)

    print("\n[11] 版本号来源")
    ver_py = ROOT / "comfy_nexus_version.py"
    vtxt = read(ver_py).strip()
    check("comfy_nexus_version.py 存在且有 __version__",
          "__version__" in vtxt, vtxt[:40])
    # getAppInfo 读的是这个文件，不是 version.json
    check("getAppInfo 的版本来自 backend.get_version()",
          "backend.get_version()" in api,
          "改 version.json 不会改变界面上显示的版本号")

    print("\n" + "=" * 50)
    print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("\n失败项：")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
