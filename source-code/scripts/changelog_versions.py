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
    # v1.3.3
    # ------------------------------------------------------------------
    {
        "version": "v1.3.3",
        "date": "2026-10-26",
        "type": "修复版（Stable）",
        "body_zh": """## 🐛 问题修复

- **修复「关于」页在小窗口下布局被压扁、更新日志看不到也无法下拉** - 窗口拉小后各板块被无限压缩，更新日志只剩一条窄缝，内容看不全也滚不动；现改为给更新日志一个固定的可读高度，窗口装不下时整页上下滚动，滚到即可完整查看
- **修复「关于」页在中等窗口下更新日志可视区域过小** - 原先在 1280×800 这类尺寸下仍强行排成三列，日志区只剩很窄一条；现改为该尺寸走单列滚动布局，日志区高度与其他尺寸保持一致

## 🎨 界面优化

- **「关于」页布局按可用空间自适应** - 窗口宽高都充足时，各板块铺满一屏、日志在版块内滚动；空间不足时自动切换为单列、整页滚动，任何窗口尺寸下都能把更新日志完整看到
- **版本更新至 v1.3.3**

---

## 🐛 Bug Fixes

- **Fixed: the About page layout collapsed in small windows, making the changelog unreadable and unscrollable** - Shrinking the window squeezed every panel without limit until the changelog was reduced to a narrow slit that could neither be read nor scrolled. The changelog now keeps a fixed readable height, and when the window cannot fit everything the whole page scrolls, so it is fully viewable once scrolled to
- **Fixed: the changelog viewport was too small on medium-sized windows** - At sizes like 1280x800 the page still forced a three-column layout, leaving only a thin strip for the log. Such sizes now use the single-column scrolling layout, keeping the log area the same height as on other sizes

## 🎨 UI/UX Improvements

- **The About page now adapts to available space** - When the window is both wide and tall enough, panels fill one screen and the log scrolls inside its own panel; when space is tight it switches to a single column with whole-page scrolling, so the changelog is always fully viewable at any window size
- **Version bumped to v1.3.3**""",
        "body_en": "",
    },
    # ------------------------------------------------------------------
    # v1.3.2
    # ------------------------------------------------------------------
    {
        "version": "v1.3.2",
        "date": "2026-10-25",
        "type": "优化版（Stable）",
        "body_zh": """## ✨ 新增功能

- **更新日志底部新增两个独立日志链接** - 分别跳转「原项目日志」（Allen-xxa/ComfyNexus）与「当前项目日志」（renxingblack/ComfyNexus），一眼区分两个仓库的更新记录

## 🐛 问题修复

- **修复「关于→更新日志」仅显示精简摘要、无法查看各版本完整内容** - 现改为直接渲染各版本的完整 Markdown 正文，与首次打开弹窗内容一致
- **修复历史版本日志被折叠、默认不展开导致内容看不到** - 现各版本默认全部展开，所有标题与说明清晰可见
- **修复「拖动窗口四角改变大小」失效** - 在 Windows 11 上按标题查找主窗口会先命中资源管理器的「标签页代理窗口」（同名、属于 explorer.exe），导致窗口样式与消息钩子全部施加到外部进程上并被系统拒绝，真实窗口因此丢失可缩放边框，四角拖拽彻底失效。现改为按「本进程 + 窗口类名」精确定位真实窗口，四角缩放恢复正常
- **修复「重复启动时不激活已打开窗口」** - 同上根因，再次启动时会去激活资源管理器的同名窗口而非本程序；现按进程归属过滤，找不到本程序窗口时不激活任何外部窗口
- **修复「系统监控悬浮窗位置偶尔错乱」** - 同上根因，悬浮窗的定位参照物可能取到别的进程窗口；现统一使用同一套精确定位

## 🎨 界面优化

- **「更新日志」改为版块内独立滚动** - 不再一次性铺满整页，与其他板块一起铺满当前窗口，长日志在版块内上下滚动查看
- **「支持项目」「加入TG群组」版块缩放至合适大小** - 不再被拉伸放大，可完整显示在一个屏幕中
- **版本更新至 v1.3.2**

---

## ✨ New Features

- **Two separate changelog links at the bottom** - Jump to the "Original Project Log" (Allen-xxa/ComfyNexus) and the "Current Project Log" (renxingblack/ComfyNexus) respectively, so you can tell the two repositories' release notes apart at a glance

## 🐛 Bug Fixes

- **Fixed: "About → Changelog" only showed a brief summary and hid each version's full content** - It now renders each version's complete Markdown body, identical to the popup shown on first launch
- **Fixed: history version logs were collapsed and hidden by default** - All versions now expand by default, so every heading and note is clearly visible
- **Fixed: dragging the window corners to resize did not work** - On Windows 11, looking up the main window by title matches Explorer's tab proxy window first (same title, owned by explorer.exe), so window styles and message hooks were applied to a foreign process and rejected by the system; the real window thereby lost its resizable frame and corner dragging failed entirely. The real window is now located precisely by owning process plus window class, and corner resizing works again
- **Fixed: relaunching did not bring the already-running window to front** - Same root cause; a second launch focused Explorer's look-alike window instead of this application. Results are now filtered by owning process, and no foreign window is activated when this application's window cannot be found
- **Fixed: the system-monitor floating window occasionally appeared in the wrong place** - Same root cause; the positioning reference could resolve to another process's window. It now uses the same precise lookup

## 🎨 UI/UX Improvements

- **"Changelog" now scrolls inside its own panel** - It no longer fills the whole page; it shares the window with other panels, and long logs scroll vertically within the panel
- **"Support Project" and "Join TG Group" panels scaled to a fitting size** - They are no longer stretched and fit entirely on one screen
- **Version bumped to v1.3.2**""",
        "body_en": "",
    },
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

### 🗂 模型管理（全新模块）

- **本地模型库浏览**
  - 递归扫描环境 `models/` 目录下全部子目录，自动按类型分组（checkpoints / loras / vae / controlnet 等）
  - 支持关键字搜索模型文件名，输入即时过滤
  - 支持按名称、大小、修改时间三种方式排序
  - 提供三种查看方式：详细列表、宽松平铺、紧凑平铺
  - 扫描结果缓存并防抖落盘，重复进入秒级加载
- **网络模型下载（多源自动识别）**
  - 自动识别 HuggingFace、HF-Mirror、魔搭社区（ModelScope）、Civitai 及任意直链
  - HuggingFace 官方源失败时自动切换 `hf-mirror.com` 国内镜像重试
  - 支持断点续传（`.part` 临时文件 + Range 请求，服务器不支持时自动退回全量下载）
  - 下载任务串行入队，实时显示进度、速度与剩余时间，完成后可清空已完成任务
- **本地模型文件夹多路径**
  - 支持配置多个模型目录，每个路径可单独启用、禁用或删除
  - 默认扫描 ComfyUI 环境的 `models` 目录，首次使用给出引导
- **网络链接同步与关联**
  - 「同步链接」一键为所有未关联的本地模型自动匹配网络链接（魔搭优先，其次 HuggingFace）
  - 单文件手动关联，候选链接点击选择或手动输入，可覆盖
  - 支持移除已关联的链接
- **模型删除**：删除操作二次确认，不可恢复

### 🧩 LoRA 管理增强

- **本地 LoRA 文件夹多路径**：支持配置多个 LoRA 目录，逐个启用 / 禁用 / 删除
- **刷新按钮**：磁盘文件变动后可一键重新扫描并同步列表
- **空路径可保存**：允许把路径保存为空，不再强制保留旧值
- **Civitai 信息拉取**：支持全量拉取与增量拉取两种模式（增量仅处理未查询过的模型）
- **模型资料完善**：支持预览图上传 / 删除、触发词、默认权重、采样器 / 调度器、自定义标签、备注信息
- **快速筛选与统计**：支持按分类快速筛选，显示模型总数与总大小

### 🔌 插件管理

- **新增「大小」列**：插件列表展示每个插件占用的磁盘空间，便于清理
- **更完整的列表信息**：显示启用状态、分支、版本、安装日期、更新时间
- **批量开关**：支持一键全部启用 / 全部禁用

### 🪟 窗口与界面

- **窗口尺寸预设**：设置页提供常用尺寸一键切换，保存后立即生效
- **窗口最小尺寸保护**：窗口不小于 1024×640，避免拖得过小导致界面元素无法完整显示
- **内容随窗口自适应**：窗口缩放时界面布局自动重排，内容不再溢出

### 🚀 零基础安装（全新引导）

- **安装步骤重排**：按真实依赖顺序展示为 安装位置 → ComfyUI 版本 → 注意力后端 → 模型（仅链接）→ 插件 → 确认安装，降低新手理解成本
- **进度按字节总量计算**：下载进度以实际字节数为准，不再出现百分比跳变
- **依赖滚动展示**：长列表依赖在固定区域内滚动，不再撑高页面
- **工作流多源下载**：内置官方 10 条推荐工作流，支持多个下载源自动切换
- **安装资源持久化**：已下载的安装资源保留在本地，重装无需重复下载
- **安装状态自动恢复**：安装线程后台运行，切页后自动恢复到进度页，不渲染空进度页

### 📦 安装包

- **默认安装路径 `D:\\Program\\ComfyNexus\\`** ：安装时自动创建目录
- **支持自定义安装目录**：安装向导可选择任意路径

## 🐛 问题修复

### 窗口相关

- 修复拖动四角时窗口平移、尺寸不变的问题，窗口不再跟随鼠标移动
- 修复缩小时界面四周显示不全，最大化 / 关闭等按钮不再被挤出可视区
- 修复缩放窗口时界面卡死，缩放过程不再触发全站样式重算
- 修复窗口变窄后内容溢出，内容自动收缩不再溢出到窗口外
- 修复四周露出边框、内容被裁掉，窗口边缘与内容对齐
- 修复点一下四角就变成最大化，拖动角不再误触发最大化
- 修复窗口大小设置后无效，设置页选择的尺寸立即生效
- 修复进出全屏后四角缩放失效，全屏切换后四角仍可正常拖动

### 其他修复

- 修复打开工作流无响应，工作流文件可正常载入
- 修复工作流名称显示为 `Unsaved Workflow`，正确显示实际文件名
- 修复工作流文件结构校验缺失，无效文件给出明确提示
- 修复桥接 API 返回值被二次包装，前端不再拿到嵌套数据
- 修复核心管理「版本更新」失败，版本更新流程可正常完成
- 修复插件安装卡在 40%，安装进度可正常完成
- 修复「自动下载缺失节点」开关无效，开关状态正确生效
- 修复「添加环境」进入空白页，页面正常加载
- 修复常用工具图标显示为地球，图标正确匹配
- 修复白屏闪退，启动稳定性提升
- 修复插件目录删除后仍显示，列表与实际目录保持同步

## 🎨 界面优化

- **万级列表渐进渲染**：大量条目分批加载，滚动更流畅
- **批量写入合并**：频繁保存时合并写盘，减少卡顿
- **版本号统一**：关于页、标题栏、安装包三处版本号显示一致

## 📌 升级说明

- 本版本基于原作者 v1.2.6 继续开发，原作者全部历史日志已完整保留在「历史版本」章节
- 支持自定义安装目录，默认路径为 `D:\\Program\\ComfyNexus\\`

---

## ✨ New Features

### 🗂 Model Management (brand-new module)

- **Local model library browsing**
  - Recursively scans every subdirectory under `models/`, grouping entries by type (checkpoints / loras / vae / controlnet, etc.)
  - Keyword search by filename with instant filtering
  - Sort by name, size, or modified time
  - Three view modes: detailed list, loose grid, compact grid
  - Scan results are cached and debounce-flushed to disk for near-instant reload
- **Multi-source model downloads**
  - Auto-detects HuggingFace, HF-Mirror, ModelScope, Civitai, and any direct link
  - HuggingFace's official source automatically falls back to the `hf-mirror.com` domestic mirror on failure
  - Resumable downloads (`.part` temp file + Range requests; falls back to full download when unsupported)
  - Serial download queue with live progress, speed, and ETA; finished tasks can be cleared
- **Multiple local model folders**
  - Configure several model directories, each individually enabled, disabled, or removed
  - Scans the ComfyUI environment's `models` directory by default, with first-run guidance
- **Online link sync & association**
  - One-click "Sync Links" auto-matches online links for all unlinked local models (ModelScope first, then HuggingFace)
  - Per-file manual association with click-to-pick candidates or manual input
  - Remove an existing association at any time
- **Model deletion** with a confirmation dialog (irreversible)

### 🧩 LoRA Management Enhancements

- **Multiple local LoRA folders**: configure several LoRA directories, each individually enabled / disabled / removed
- **Refresh button**: rescan and resync the list after on-disk changes with one click
- **Empty paths can be saved**: no longer forced to keep the old value
- **Civitai metadata pull**: full and incremental modes (incremental only processes models not yet queried)
- **Richer model metadata**: preview image upload / delete, trigger words, default weight, sampler / scheduler, custom tags, notes
- **Quick filter & stats**: filter by category and see total count and total size

### 🔌 Plugin Management

- **New Size column**: the plugin list shows disk space per plugin, making cleanup easier
- **Fuller list info**: enabled state, branch, version, install date, and update time
- **Bulk toggle**: enable all / disable all with one click

### 🪟 Window & Interface

- **Window size presets**: one-click switching between common sizes in Settings, applied immediately
- **Minimum window size protection**: never shrinks below 1024×640 so UI elements stay fully visible
- **Content adapts to window size**: layout reflows on resize with no overflow

### 🚀 Zero-Basics Installation (new guided wizard)

- **Reordered steps**: Install location → ComfyUI version → Attention backend → Models (links only) → Plugins → Confirm, following the real dependency order for newcomers
- **Byte-based progress**: download progress reflects actual bytes, eliminating percentage jumps
- **Scrollable dependency list**: long dependency lists scroll inside a fixed area instead of stretching the page
- **Multi-source workflow downloads**: 10 built-in official recommended workflows with automatic source switching
- **Persistent install assets**: downloaded assets are kept locally so reinstalling requires no re-download
- **Auto-resume install state**: the install thread runs in the background and auto-returns to the progress page on navigation, never rendering an empty progress view

### 📦 Installer

- **Default install path `D:\\Program\\ComfyNexus\\`** : created automatically during installation
- **Custom install directory**: choose any path in the setup wizard

## 🐛 Bug Fixes

### Window

- Fixed window shifting without resizing when dragging a corner; the window no longer moves with the cursor
- Fixed UI being clipped when shrinking the window; maximize/close buttons are no longer pushed out of view
- Fixed the interface freezing while resizing; resizing no longer triggers site-wide style recalculation
- Fixed content overflowing when the window narrowed; content now shrinks instead of overflowing
- Fixed borders showing around the edges with content cropped; window edges now align with content
- Fixed a single corner click maximizing the window; dragging a corner no longer triggers maximize
- Fixed the window size setting having no effect; the chosen size now applies immediately
- Fixed corner resizing breaking after toggling fullscreen; corners still work after fullscreen transitions

### Other Fixes

- Fixed opening a workflow doing nothing; workflow files now load correctly
- Fixed workflow names showing as `Unsaved Workflow`; the actual filename is now displayed
- Fixed missing workflow structure validation; invalid files now produce a clear message
- Fixed bridge API return values being double-wrapped; the frontend no longer receives nested data
- Fixed the version update in core management failing; the update flow now completes normally
- Fixed plugin installation stalling at 40%; installation progress now finishes
- Fixed the Auto-download missing nodes toggle having no effect; the toggle state now applies correctly
- Fixed Add Environment opening a blank page; the page now loads normally
- Fixed common tool icons showing a globe; icons now match correctly
- Fixed white-screen crash; improved startup stability
- Fixed deleted plugin directories still appearing; the list stays in sync with actual directories

## 🎨 UI/UX Improvements

- **Progressive rendering for huge lists**: large lists load in batches for smoother scrolling
- **Batched writes**: frequent saves are merged into a single disk write, reducing stutter
- **Unified version number**: consistent across the About page, title bar, and installer

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
