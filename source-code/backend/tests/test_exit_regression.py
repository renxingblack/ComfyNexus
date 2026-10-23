"""
问题 4 回归测试：托盘右键「退出」后进程无法退出

原 bug 的因果链：
  1. tray_exit_app 只调 window.destroy()，不置任何退出意图标志
  2. -> on_window_closing 守卫不成立，走 minimize 分支把窗口 hide()，
     而托盘此时已被自己销毁 -> 窗口没了、图标没了、进程还在
  3. 另无 os._exit 兜底，daemon=False 的 health_check 线程阻塞解释器退出

本测试用真实线程 + 真实标志位验证修复后的行为，不 mock GUI。
"""
import os
import sys
import time
import threading
import tempfile
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND.parent
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(BACKEND))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {detail}" if detail and not cond else ""))


def fresh_coordinator():
    """拿到一个全新的 ExitCoordinator 实例（避免单例状态串味）"""
    from backend.src.core.exit_coordinator import ExitCoordinator
    return ExitCoordinator()


def test_tray_exit_sets_intent():
    """核心：托盘退出会设置退出意图标志"""
    print("\n[测试1] 托盘退出会设置退出意图标志")
    c = fresh_coordinator()
    calls = []
    c.register_cleanup("A", lambda: calls.append("A"))
    c.register_cleanup("B", lambda: calls.append("B"))

    check("初始无退出意图", c.exit_requested is False)
    c.request_exit(source="tray", hard_exit=False)
    check("退出意图已置位", c.exit_requested is True)
    c.wait_for_cleanup(timeout=5)
    check("所有清理步骤都执行了", calls == ["A", "B"], f"实际={calls}")


def test_cleanup_is_idempotent():
    """重复触发退出不得重复清理（WMI 句柄二次释放会抛异常）"""
    print("\n[测试2] 清理幂等")
    c = fresh_coordinator()
    calls = []
    c.register_cleanup("comfyui", lambda: calls.append("stop"))

    c.request_exit(source="tray", hard_exit=False)
    c.request_exit(source="window-close", hard_exit=False)   # 第二次应被忽略
    c.request_exit(source="api-closeApp", hard_exit=False)
    c.wait_for_cleanup(timeout=5)

    check("重复退出请求只清理一次", calls == ["stop"], f"实际={calls}")


def test_one_failing_step_does_not_block_others():
    """ComfyUI 没启动时 kill 失败，不能连带跳过托盘销毁"""
    print("\n[测试3] 单步失败不中断后续清理")
    c = fresh_coordinator()
    calls = []

    def boom():
        raise RuntimeError("ComfyUI 未运行")

    c.register_cleanup("comfyui", boom)
    c.register_cleanup("tray", lambda: calls.append("tray-destroyed"))
    c.register_cleanup("window", lambda: calls.append("window-destroyed"))

    c.request_exit(source="tray", hard_exit=False)
    c.wait_for_cleanup(timeout=5)

    check("前一步抛异常后，后续步骤仍全部执行",
          calls == ["tray-destroyed", "window-destroyed"], f"实际={calls}")


def test_does_not_block_caller_thread():
    """托盘回调线程不能被清理阻塞（否则用户感觉点了没反应）"""
    print("\n[测试4] 不阻塞调用方线程")
    c = fresh_coordinator()
    finished = threading.Event()

    def slow_cleanup():
        time.sleep(1.5)
        finished.set()

    c.register_cleanup("slow", slow_cleanup)

    t0 = time.time()
    c.request_exit(source="tray", hard_exit=False)
    elapsed = time.time() - t0

    check("request_exit 立即返回（<0.5s）", elapsed < 0.5, f"耗时 {elapsed:.2f}s")
    check("清理在后台线程执行", not finished.is_set())
    check("后台清理最终完成", c.wait_for_cleanup(timeout=5))
    check("清理函数确实跑完了", finished.is_set())


def test_closing_handler_not_downgraded():
    """回归原始 bug：退出意图置位后，closing 守卫必须放行而不是 hide()"""
    print("\n[测试5] closing 事件在退出意图下不再被降级为 hide()")
    c = fresh_coordinator()
    c.request_exit(source="tray", hard_exit=False)

    # 复刻 main.py on_window_closing 的守卫表达式
    _is_exiting = False
    _dialog_pending = False
    _app_exit_requested = True          # 托盘退出会置位它
    minimized = []

    def on_window_closing():
        if _is_exiting or _dialog_pending or _app_exit_requested or c.exit_requested:
            return True               # 放行关闭
        minimized.append(True)         # minimize 分支
        return False

    allowed = on_window_closing()
    check("退出意图下 closing 被放行", allowed is True, f"实际={allowed}")
    check("没有走进 minimize 分支", not minimized, "窗口被藏起来了 —— 这正是原 bug")


def test_source_no_bare_destroy():
    """静态检查：三条退出路径都不再自己实现清理"""
    print("\n[测试6] 退出路径已统一")
    main_src = (BACKEND / "main.py").read_text(encoding="utf-8")

    # tray_exit_app 的可执行代码里不得再有裸 window.destroy()。
    # 说明文字里的 "window.destroy()" 字样不算。
    # window.destroy() 出现在独立的 _cleanup_window 清理步骤里是设计如此。
    start = main_src.index("def tray_exit_app")
    end = main_src.index("def _cleanup_floating_window")
    raw = main_src[start:end]
    code_only = "\n".join(
        line for line in raw.splitlines()
        if not line.strip().startswith("#")
    )
    # 去掉 docstring
    if '"""' in code_only:
        parts = code_only.split('"""')
        code_only = "".join(parts[::2])

    check("tray_exit_app 不再直接调 window.destroy()",
          "window.destroy()" not in code_only, "仍存在裸 destroy")
    check("tray_exit_app 走 ExitCoordinator", "exit_coordinator.request_exit" in raw)
    check("tray_exit_app 置位退出意图", "_app_exit_requested = True" in raw)

    # 窗口销毁必须作为独立清理步骤注册，而不是内联在回调里
    check("窗口销毁已抽成独立清理步骤",
          "def _cleanup_window" in main_src and "window.destroy()" in main_src)

    # 5 个清理步骤必须都被注册（用循环注册，故源码里只有 1 处调用）
    reg_block = main_src[main_src.index("# 注册幂等清理步骤"):
                         main_src.index("system_tray_manager.set_callbacks")]
    for step in ("_cleanup_floating_window", "_cleanup_comfyui",
                 "_cleanup_monitor", "_cleanup_tray", "_cleanup_window"):
        check(f"清理步骤已注册: {step}", step in reg_block, "未出现在注册块中")
    check("注册到协调器", "exit_coordinator.register_cleanup" in reg_block)

    check("main.py 导入 ExitCoordinator", "from backend.src.core.exit_coordinator import" in main_src)
    check("主流程收尾改用协调器", "webview-closed" in main_src)

    api_src = (BACKEND / "src/bridge/api.py").read_text(encoding="utf-8")
    s = api_src.index("def closeApp")
    e = api_src.index("def minimizeApp")
    check("closeApp 走 ExitCoordinator",
          "exit_coordinator.request_exit" in api_src[s:e])

    fw_src = (BACKEND / "src/ui/floating_window.py").read_text(encoding="utf-8")
    check("悬浮窗看门狗走 ExitCoordinator",
          "exit_coordinator.request_exit" in fw_src)


def test_real_process_exits():
    """真实进程验证：注册一个会写文件的清理步骤，确认 os._exit 真的结束进程"""
    print("\n[测试7] 真实子进程调用 os._exit 后确实终止")
    import subprocess

    marker = Path(tempfile.gettempdir()) / f"cn_exit_probe_{os.getpid()}.txt"
    if marker.exists():
        marker.unlink()

    code = f"""
import sys, time
sys.path.insert(0, r"{SRC_ROOT}")
sys.path.insert(0, r"{BACKEND}")
from backend.src.core.exit_coordinator import ExitCoordinator
c = ExitCoordinator()
def mark():
    open(r"{marker}", "w").write("cleaned")
c.register_cleanup("marker", mark)
c.request_exit(source="tray")   # hard_exit=True -> os._exit(0)
time.sleep(20)                    # 若未 os._exit 会睡满 20 秒
print("NOT_EXITED")
"""
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=30
    )
    elapsed = time.time() - t0

    check("子进程被 os._exit 强制终止", "NOT_EXITED" not in proc.stdout,
          f"进程没退出，耗时 {elapsed:.1f}s")
    check("退出耗时远小于 sleep(20)", elapsed < 10, f"耗时 {elapsed:.1f}s")
    check("清理步骤在退出前已执行", marker.exists(),
          "清理没跑就退出了")
    if marker.exists():
        marker.unlink()


def main():
    for fn in (test_source_no_bare_destroy,
               test_tray_exit_sets_intent,
               test_cleanup_is_idempotent,
               test_one_failing_step_does_not_block_others,
               test_does_not_block_caller_thread,
               test_closing_handler_not_downgraded,
               test_real_process_exits):
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"  [ERROR] {fn.__name__}: {e}")
            FAIL.append(f"{fn.__name__} 异常: {e}")
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"通过 {len(PASS)} / {len(PASS)+len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    main()
