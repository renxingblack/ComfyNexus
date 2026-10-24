# -*- coding: utf-8 -*-
"""
ComfyNexus 自有版本更新日志（v1.2.6 → v1.3.1）

设计原则（用户明确要求）：
1. **只写结果**：新增功能 / 问题修复 / 界面优化三类，不写过程、原理、实现方法；
2. **中英双文**：每个版本先中文、后英文，方便国内外用户阅读；
3. **格式对齐原仓库**（Allen-xxa/ComfyNexus）：
   顶部 `# ComfyNexus vX.Y.Z 更新日志` + `**发布日期**` / `**版本类型**` +
   水平线 + `## <emoji> 章节名` + `- **功能名** - 一句话说明`。

本文件只提供「当前自有版本」的日志正文；
原作者 v1.2.6 及更早的历史版本由 `original_releases.json` 原文提供，二者
在 `build_version_json.py` 里拼接成完整的 `release_notes`。

维护方式（增量）：
- 新增版本 → 在 VERSIONS 里追加一条（order 最新在前）；
- 不需要改动历史条目，也不需要碰 JSON 快照。
"""

# 每个版本的日志正文（Markdown）
# 顺序：最新在前
VERSIONS = [
    # ------------------------------------------------------------------
    # v1.3.1
    # ------------------------------------------------------------------
    {
        "version": "v1.3.1",
        "date": "2026-10-24",
        "type": "修复版（Stable）",
        "body_zh": """## ✨ 新增功能

- **窗口四角自由调整大小** - 拖动窗口任意一角即可按需调整尺寸，四个角均可用，缩放时对角固定不动
- **窗口最小尺寸保护** - 窗口不小于 1024×640，避免拖得过小导致界面元素无法完整显示
- **窗口尺寸自动记忆** - 调整后的尺寸自动保存，下次启动还原时回到上次的大小

## 🐛 问题修复

- **修复无法拖动四角调整窗口大小** - v1.3.0 中拖动四角完全无响应，只能在设置页选择固定尺寸；现已可自由拖动
- **修复拖动四角时窗口整体平移** - 拖动时对角固定，窗口跟随鼠标平移的问题已消除
- **修复调整后的窗口尺寸不被记住** - 下次启动时尺寸回退为默认值的问题已解决
- **修复调整后的尺寸被最大化尺寸覆盖** - 冷启动自动最大化时不再把屏幕尺寸写入设置，用户设定的尺寸得以保留
- **修复「还原」按钮点击无效** - 最大化状态下点击还原无法恢复窗口，现已正常
- **修复最大化状态误判** - 最大化后系统状态与实际不一致，导致还原操作走错分支的问题已修正
- **修复窗口贴近屏幕边缘后四角无法再拖动** - 窗口拖到工作区边缘后四角仍可正常操作
- **修复窗口被任务栏遮挡** - 窗口底部不再被任务栏挡住，底部两个角始终可点击
- **修复全屏与最大化行为混淆** - 最大化保留任务栏、全屏覆盖任务栏，二者边界清晰
- **修复启动时日志版本号显示旧版本** - 版本号统一显示为 v1.3.1

## 🎨 界面优化

- **窗口拖动操作跟随鼠标更顺滑** - 拖动过程中窗口实时跟随，松手立即定格
- **窗口状态切换后立即生效** - 全屏、最大化、还原之间切换无需重启

## 📌 升级说明

- 本版本聚焦窗口缩放体验修复，其余功能与 v1.3.0 保持一致
- 若此前使用过小于 1024×640 的自定义窗口，升级后请重新调整

---

## ✨ New Features

- **Free-resize from any window corner** - Drag any corner of the window to resize freely; all four corners work, and the opposite corner stays fixed
- **Minimum window size protection** - The window never shrinks below 1024×640, so UI elements always remain fully visible
- **Automatic window size memory** - Your adjusted size is saved automatically and restored on the next launch

## 🐛 Bug Fixes

- **Fixed: window could not be resized by dragging corners** - Dragging corners had no effect in v1.3.0 and the size could only be changed via a fixed preset in Settings; corners now resize freely
- **Fixed: window shifted as a whole while dragging a corner** - The opposite corner now stays fixed instead of the window moving with the cursor
- **Fixed: adjusted window size was not remembered** - The window no longer reverts to its default size on the next launch
- **Fixed: adjusted size was overwritten by the maximized size** - Auto-maximizing on startup no longer writes the screen size into settings, so your chosen size is preserved
- **Fixed: the Restore button did nothing** - Restoring from a maximized window now works correctly
- **Fixed: maximized state was misdetected** - The system state and internal state now stay in sync, so restore no longer takes the wrong path
- **Fixed: corners stopped working after dragging the window to the screen edge** - All four corners remain operable at the edge of the work area
- **Fixed: the window was obscured by the taskbar** - The bottom edge is no longer hidden behind the taskbar, so both bottom corners stay clickable
- **Fixed: fullscreen and maximize behaved ambiguously** - Maximize keeps the taskbar while fullscreen covers it, and the two are now clearly separated
- **Fixed: the log showed an outdated version number at startup** - The version now consistently reports v1.3.1

## 🎨 UI/UX Improvements

- **Smoother corner-drag tracking** - The window follows the cursor in real time and locks in place the moment you release
- **Window state changes take effect immediately** - Switching between fullscreen, maximize, and restore no longer requires a restart

## 📌 Upgrade Notes

- This release focuses on window resizing; all other features are unchanged from v1.3.0
- If you previously used a custom window smaller than 1024×640, please adjust it again after upgrading""",
        "body_en": "",
    },
    # ------------------------------------------------------------------
    # v1.3.0
    # ------------------------------------------------------------------
    {
        "version": "v1.3.0",
        "date": "2026-10-23",
        "type": "功能版（Stable）",
        "body_zh": """## ✨ 新增功能

### 🗂 模型管理

- **本地模型库浏览** - 递归扫描环境 `models/` 下全部子目录，按类型分组展示，支持关键字搜索
- **模型多源下载** - 自动识别 HuggingFace、HF-Mirror、魔搭社区、Civitai 及任意直链，失败时自动切换国内镜像
- **模型文件夹多路径设置** - 支持配置多个模型目录，逐个开关与删除
- **网络链接同步** - 可将在线模型库链接加入本地列表，直接浏览与下载
- **默认链接源可切换** - 内置多个模型库链接源，可随时切换
- **单文件手动关联** - 下载后的文件可手动关联到指定模型类型

### 🔌 插件管理

- **新增「大小」列** - 插件列表展示每个插件占用磁盘空间，便于清理

### 🪟 窗口与界面

- **窗口尺寸预设** - 设置页提供常用尺寸一键切换
- **内容随窗口自适应** - 窗口缩放时界面布局自动重排

### 🚀 0 基础安装

- **安装步骤重排** - 按实际依赖顺序展示，降低新手理解成本
- **依赖滚动展示** - 长列表依赖在固定区域内滚动，不再撑高页面
- **进度按字节总量计算** - 下载进度以实际字节数为准，不再出现百分比跳变
- **工作流多源下载** - 工作流资源支持多个下载源自动切换
- **安装资源持久化** - 已下载的安装资源保留在本地，重装无需重复下载

### 🧩 LoRA 管理

- **本地文件夹多路径设置** - 支持配置多个 LoRA 目录，逐个开关与删除
- **刷新按钮** - 磁盘文件变动后可一键重新扫描同步
- **空路径可保存** - 允许把路径保存为空，不再强制保留旧值

### 📦 安装包

- **默认安装路径 `D:\\Program\\ComfyNexus\\`** - 安装时自动创建目录
- **支持自定义安装目录** - 安装向导可选择任意路径

## 🐛 问题修复

### 窗口相关

- **修复拖动四角时窗口平移、尺寸不变** - 窗口不再跟随鼠标移动
- **修复缩小时界面四周显示不全** - 最大化、关闭等按钮不再被挤出可视区
- **修复缩放窗口时界面卡死** - 缩放过程不再触发全站样式重算
- **修复窗口变窄后内容溢出** - 内容自动收缩，不再溢出到窗口外
- **修复四周露出边框、内容被裁掉** - 窗口边缘与内容对齐
- **修复点一下四角就变成最大化** - 拖动角不再误触发最大化
- **修复窗口大小设置后无效** - 设置页选择的尺寸立即生效
- **修复进出全屏后四角缩放失效** - 全屏切换后四角仍可正常拖动

### 其他修复

- **修复打开工作流无响应** - 工作流文件可正常载入
- **修复工作流名称显示为 `Unsaved Workflow`** - 正确显示实际文件名
- **修复工作流文件结构校验缺失** - 无效文件给出明确提示
- **修复桥接 API 返回值被二次包装** - 前端不再拿到嵌套数据
- **修复核心管理「版本更新」失败** - 版本更新流程正常完成
- **修复插件安装卡在 40%** - 安装进度可正常完成
- **修复「自动下载缺失节点」开关无效** - 开关状态正确生效
- **修复「添加环境」进入空白页** - 页面正常加载
- **修复常用工具图标显示为地球** - 图标正确匹配
- **修复白屏闪退** - 启动稳定性提升
- **修复插件目录删除后仍显示** - 列表与实际目录保持同步

## 🎨 界面优化

- **万级列表渐进渲染** - 大量条目分批加载，滚动更流畅
- **批量写入合并** - 频繁保存时合并写盘，减少卡顿
- **版本号统一** - 关于页、标题栏、安装包显示一致

## 📌 升级说明

- 本版本基于原作者 v1.2.6 继续开发，原作者全部历史日志已完整保留在「历史版本」章节
- 支持自定义安装目录，默认路径为 `D:\\Program\\ComfyNexus\\`

---

## ✨ New Features

### 🗂 Model Management

- **Local model library browsing** - Recursively scans every subdirectory under `models/`, groups entries by type, and supports keyword search
- **Multi-source model downloads** - Automatically detects HuggingFace, HF-Mirror, ModelScope, Civitai, and any direct link, switching to a domestic mirror on failure
- **Multiple model folder paths** - Configure several model directories with per-path enable/disable and deletion
- **Online library link sync** - Add online model library links to your local list for direct browsing and downloading
- **Switchable default link sources** - Multiple built-in model library sources you can switch between at any time
- **Manual single-file association** - Map a downloaded file to a specific model type by hand

### 🔌 Plugin Management

- **New Size column** - The plugin list shows how much disk space each plugin occupies, making cleanup easier

### 🪟 Window & Interface

- **Window size presets** - One-click switching between common sizes in Settings
- **Content adapts to window size** - The layout reflows automatically as the window is resized

### 🚀 Zero-Basics Installation

- **Reordered installation steps** - Steps follow the real dependency order, easier for newcomers
- **Scrollable dependency list** - Long dependency lists scroll inside a fixed area instead of stretching the page
- **Byte-based progress** - Download progress reflects actual bytes transferred, eliminating percentage jumps
- **Multi-source workflow downloads** - Workflow assets switch between several download sources automatically
- **Persistent install assets** - Downloaded install assets are kept locally, so reinstalling requires no re-download

### 🧩 LoRA Management

- **Multiple LoRA folder paths** - Configure several LoRA directories with per-path enable/disable and deletion
- **Refresh button** - Rescan and resync after changes on disk with one click
- **Empty paths can be saved** - Paths may now be saved as empty instead of being forced to keep the old value

### 📦 Installer

- **Default install path `D:\\Program\\ComfyNexus\\`** - Created automatically during installation
- **Custom install directory** - Choose any path in the setup wizard

## 🐛 Bug Fixes

### Window

- **Fixed: window shifted while dragging a corner without resizing** - The window no longer moves with the cursor
- **Fixed: UI was clipped when shrinking the window** - Maximize and close buttons are no longer pushed out of view
- **Fixed: interface froze while resizing** - Resizing no longer triggers site-wide style recalculation
- **Fixed: content overflowed when the window narrowed** - Content now shrinks instead of overflowing
- **Fixed: borders showed around the edges and content was cropped** - Window edges now align with content
- **Fixed: a single click on a corner maximized the window** - Dragging a corner no longer triggers maximize
- **Fixed: the window size setting had no effect** - The size chosen in Settings now applies immediately
- **Fixed: corner resizing broke after toggling fullscreen** - Corners still work after fullscreen transitions

### Other Fixes

- **Fixed: opening a workflow did nothing** - Workflow files now load correctly
- **Fixed: workflow names showed as `Unsaved Workflow`** - The actual filename is now displayed
- **Fixed: missing workflow file structure validation** - Invalid files now produce a clear message
- **Fixed: bridge API return values were double-wrapped** - The frontend no longer receives nested data
- **Fixed: version update in core management failed** - The update flow now completes normally
- **Fixed: plugin installation stalled at 40%** - Installation progress now finishes
- **Fixed: the Auto-download missing nodes toggle had no effect** - The toggle state now applies correctly
- **Fixed: Add Environment opened a blank page** - The page now loads normally
- **Fixed: common tool icons showed a globe** - Icons now match correctly
- **Fixed: white-screen crash** - Improved startup stability
- **Fixed: deleted plugin directories still appeared** - The list stays in sync with the actual directories

## 🎨 UI/UX Improvements

- **Progressive rendering for huge lists** - Large lists load in batches for smoother scrolling
- **Batched writes** - Frequent saves are merged into a single disk write, reducing stutter
- **Unified version number** - Consistent across the About page, title bar, and installer

## 📌 Upgrade Notes

- This release continues from the original author's v1.2.6, whose full changelog is preserved in the History section
- A custom install directory is supported; the default path is `D:\\Program\\ComfyNexus\\`""",
        "body_en": "",
    },
    # ------------------------------------------------------------------
    # v1.2.6
    # ------------------------------------------------------------------
    {
        "version": "v1.2.6",
        "date": "2026-07-07",
        "type": "Stable",
        "body_zh": """## 🐛 问题修复

- **修复启动时更新检查阻塞主进程** - 版本检查改为后台执行，启动更流畅
- **修复首次网络请求卡顿** - 首次 HTTPS 请求响应更快
- **修复全屏退出后任务栏无法正常最小化/恢复窗口** - 全屏退出后窗口可正常最小化与恢复

## 🎨 界面优化

- **标题栏停止按钮图标更新** - 停止按钮改用 Power 图标

---

## 🐛 Bug Fixes

- **Fixed: update check blocked the main process at startup** - The version check now runs in the background for a smoother launch
- **Fixed: the first network request stalled** - The first HTTPS request now responds faster
- **Fixed: the taskbar could not minimize or restore the window after leaving fullscreen** - Minimize and restore work normally after exiting fullscreen

## 🎨 UI/UX Improvements

- **Updated title bar stop button icon** - The stop button now uses the Power icon""",
        "body_en": "",
    },
]


def get_local_notes(version: str) -> str:
    """取某个自有版本的日志正文（Markdown）。找不到返回空串。"""
    for v in VERSIONS:
        if v["version"] == version:
            return v["body_zh"]
    return ""


def get_all_versions_sorted() -> list:
    """返回按日期倒序排列的自有版本列表"""
    return sorted(VERSIONS, key=lambda x: x.get("date") or "", reverse=True)
