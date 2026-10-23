"""
统一退出协调器

修复「任务栏托盘右键 → 退出」后进程无法退出的问题。

原实现的三个缺陷（相互叠加导致点了退出进程还在）：

1. **退出意图没有统一标志**。托盘回调、窗口关闭事件、前端 closeApp API 三条
   退出路径各写一套清理逻辑，其中只有窗口关闭路径会设置 `_is_exiting` /
   `_app_exit_requested`。托盘路径没设，于是 `on_window_closing` 的守卫不成立，
   走到「最小化到托盘」分支 —— 而托盘此时已被 destroy() 销毁，
   结果窗口消失、托盘图标消失、进程却还活着。

2. **托盘回调跑在 pystray 线程**，直接调用 `window.destroy()` 跨线程操作
   GUI，pywebview 下不可靠：窗口可能销毁了，但 `webview.start()` 的消息循环
   没收到关闭通知，主线程永远阻塞在那里。

3. **没有强杀兜底**。项目里有一个 `daemon=False` 的健康检查线程，
   即使窗口销毁成功，CPython 退出时也会等待所有非 daemon 线程。
   项目其他两处退出路径（floating_window 看门狗、update_controller）
   都用了 `os._exit(0)`，唯独托盘路径漏了。

本模块把退出收敛成唯一入口：设置意图标志 → 幂等清理 → os._exit(0)。
"""

import os
import threading
import time
from typing import Optional

from backend.src.utils.logger import app_logger as logger


class ExitCoordinator:
    """应用退出协调器（单例语义：全进程只应有一个退出正在进行）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._exit_requested = False
        self._cleanup_done = False
        # 清理步骤：(名称, 可调用对象)。全部幂等，任一步失败不中断后续步骤。
        self._cleanup_steps = []
        # 清理完成信号，供需要等待收尾的调用方使用
        self._cleanup_finished = threading.Event()

    @property
    def exit_requested(self) -> bool:
        """是否已请求退出（供 on_window_closing 守卫使用）"""
        return self._exit_requested

    @property
    def cleanup_done(self) -> bool:
        return self._cleanup_done

    def register_cleanup(self, name: str, func) -> None:
        """
        注册一个清理步骤。

        Args:
            name: 步骤名，仅用于日志
            func: 无参可调用对象，必须自己吞掉异常
        """
        self._cleanup_steps.append((name, func))

    def request_exit(self, source: str = "unknown", hard_exit: bool = True) -> None:
        """
        请求退出应用。

        这是全应用唯一的退出入口，托盘 / 窗口关闭 / 前端 API 都应走这里。

        Args:
            source: 退出来源，仅用于日志（tray / window / api）
            hard_exit: 是否在清理后强制 os._exit(0)。
                       设为 False 可让调用方自行决定收尾（仅调试用）。
        """
        # 幂等：重复调用只执行第一次
        with self._lock:
            if self._exit_requested:
                logger.debug(f"[ExitCoordinator] 退出已在进行中，忽略来自 {source} 的重复请求")
                return
            self._exit_requested = True

        logger.info(f"[ExitCoordinator] 收到退出请求 (来源: {source})")

        # 清理可能耗时（taskkill 子进程最多十几秒），不能阻塞调用方线程 ——
        # 托盘回调线程被卡住会让用户感觉「点了没反应」。
        thread = threading.Thread(
            target=self._shutdown_and_exit,
            args=(source, hard_exit),
            daemon=True,
            name="exit-coordinator",
        )
        thread.start()

    def _shutdown_and_exit(self, source: str, hard_exit: bool) -> None:
        """执行清理并在必要时强制退出"""
        try:
            self._run_cleanup(source)
        except Exception as e:
            logger.error(f"[ExitCoordinator] 清理过程异常: {e}")

        if not hard_exit:
            logger.info("[ExitCoordinator] 清理完成（未强制退出，由调用方决定后续）")
            return

        # 短暂延迟：让 pywebview 有机会处理完窗口销毁消息，
        # 避免窗口"闪一下"再消失。已经 destroy 过窗口的话不会有副作用。
        time.sleep(0.3)

        logger.info(f"[ExitCoordinator] 退出完成 (来源: {source})")
        # 必须用 os._exit：跳过 atexit 与非 daemon 线程 join。
        # 健康检查线程是 daemon=False，sys.exit 路径会永久卡在等它。
        os._exit(0)

    def wait_for_cleanup(self, timeout: float = 30.0) -> bool:
        """
        等待清理完成（测试与诊断用）

        Args:
            timeout: 最长等待秒数

        Returns:
            是否在超时前完成
        """
        return self._cleanup_finished.wait(timeout=timeout)

    def _run_cleanup(self, source: str) -> None:
        """按注册顺序执行所有清理步骤，每步独立容错"""
        if self._cleanup_done:
            self._cleanup_finished.set()
            return
        self._cleanup_done = True

        try:
            for name, func in list(self._cleanup_steps):
                try:
                    func()
                    logger.dev(f"[ExitCoordinator] 清理完成: {name}")
                except Exception as e:
                    # 单步失败不得影响后续步骤（如 ComfyUI 没启动就不该跳过托盘销毁）
                    logger.warning(f"[ExitCoordinator] 清理步骤失败 ({name}): {e}")
        finally:
            self._cleanup_finished.set()


# 全局单例
exit_coordinator = ExitCoordinator()
