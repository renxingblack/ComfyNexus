"""
生成 version.json（应用版本 + 更新日志）

- 版本号：v1.3.0
- release_notes：本版本（相对原仓库 v1.2.6）的新增/优化说明 + 保留原仓库历史日志
- 用法：python scripts/build_version_json.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "version.json"

VERSION = "v1.3.0"
PUBLISHED_AT = "2026-10-23T10:30:00Z"
REPO = "renxingblack/ComfyNexus"

NEW_RELEASE_NOTES = """# 更新日志 - v1.3.0

**发布日期**：2026-10-23
**版本类型**：正式版
**对比基准**：原仓库 v1.2.6

---

## ✨ 新增功能

### 🗂 模型管理（全新模块）
- **本地模型库扫描** - 扫描环境 `models/` 下全部子目录（checkpoints / loras / vae / controlnet / text_encoders 等），统一列表管理
- **多源网络下载** - 自动识别 HuggingFace / HF-Mirror / ModelScope / Civitai / 任意直链，失败自动切换国内镜像重试，支持断点续传与统一下载缓存
- **本地模型文件夹多路径设置** - 可设置多个模型文件夹、逐个开启/关闭、随时删除；默认自动填入「当前环境 models 目录 + 共享模型目录」
- **扫描路径语义明确** - 用户清空路径后不再显示任何模型；输入了哪些文件夹，就只显示哪些文件夹（不会被自动恢复）
- **网络链接同步** - 为本地模型自动匹配网络下载地址：默认**魔搭社区优先、没有则用 HuggingFace**
- **默认链接源可切换** - 魔搭社区 / HuggingFace / 自动（魔搭优先，无则 HF）三种策略随时切换
- **单文件手动关联** - 每个模型可单独打开关联弹窗，默认展示魔搭社区与 HuggingFace 上匹配到的候选链接供直接点选，也支持手动输入任意下载链接，并可一键解除关联

### 🔌 插件管理
- **新增「大小」列** - 插件名称后展示插件文件夹占用总大小（不含 `.git` 内部对象），支持点击表头按大小排序

### 🪟 窗口与界面
- **窗口任意缩放** - 四角 + 四条边均可拖动调整大小，不再只能拖角；最小窗口尺寸放宽至 1024×640
- **常用窗口尺寸预设** - 「系统设置 - 外观 - 窗口大小」新增 4K / 带鱼屏 / 2K / 全高清 / 笔记本等 9 组常见分辨率

### 🚀 0 基础安装
- **安装步骤重排** - 注意力 → 大模型 → 插件 → 工作流 → 自定义工作流 → 依赖，流程更符合直觉
- **依赖滚动展示** - 实时显示当前正在安装的依赖包，不再只有一条进度
- **进度按字节总量计算** - 多文件并行下载时进度条按实际字节总量推进，不跳变
- **工作流多源下载** - 单链接优先、慢速换源，最多回退 10 个源，全部失败自动跳过不阻塞安装
- **安装资源持久化** - 常用工具与推荐关注等内容本地留存，重启不丢

### 🧩 LoRA 管理
- **本地文件夹多路径设置** - 支持多个 LoRA 目录、逐个开关与删除
- **新增「刷新」按钮** - 磁盘文件变动后可一键重新扫描同步
- **空路径可保存** - 允许将路径保存为空，不再强制保留旧值

---

## 🔧 优化与修复

- **修复打开工作流无响应** - ComfyUI 已运行时统一走工作台加载，并加入握手重试与失败提示
- **修复工作流名称显示为 `Unsaved Workflow`** - 通过 `loadGraphData` 第四参数传入真实文件名
- **修复工作流文件结构校验缺失** - 桥接插件增加 `nodes` 数组防御，避免 `e is not iterable` 报错
- **修复核心管理「版本更新」失败** - 镜像源缺少新发布包版本时，自动追加 `--extra-index-url` 回退官方 PyPI 重试
- **修复插件安装卡在 40%** - GitHub 直连失败时自动切换加速镜像重试克隆
- **修复「自动下载缺失节点」开关无效** - 直接对应 ComfyUI-Manager 的 `security_level` 配置（ON→normal / OFF→strong）
- **修复「添加环境」进入空白页** - 欢迎页判定条件补齐 `forceWelcome` 分支
- **修复常用工具图标显示为地球** - 图标/头像改为后端抓取落盘缓存，直链图片优先于 favicon，并支持长 logo 等比显示
- **修复白屏闪退** - 部署产物 `index.html` 与 `assets` 必须来自同一次构建，杜绝入口 JS 404
- **修复插件目录删除后仍显示** - 删除时同步清理关联缓存与链接记录

---

## ⚡ 性能与稳定性

- **万级列表渐进渲染** - LoRA / 工作流 / 提示词 / 模型 / 资产库统一接入渐进渲染钩子，DOM 数量与数据总量解耦
- **批量写 JSON 防抖合并** - 消除逐条落盘造成的 O(n²) 全量重写
- **磁盘源码优先加载** - 打包环境下优先加载磁盘上的后端源码，热部署改动立即生效
- **退出流程单一入口** - 托盘 / 关窗 / 前端关闭 / 悬浮窗看门狗四条路径统一收口，避免状态不一致
- **统一版本号** - 应用版本与各内部模块（桥接插件、配置管理器、AI 模块等）统一升级为 1.3.0

---

## 📌 升级说明

- 本版本基于原仓库 v1.2.6 继续开发，原仓库功能与更新日志完整保留（见下方历史版本）
- 升级方式：下载 `ComfyNexus-v1.3.0-win64.zip` 覆盖安装，或使用应用内「检查更新」
- 窗口最小尺寸调整为 1024×640，若此前使用过更小的自定义窗口，升级后请重新调整
"""

HISTORY_TITLE = "\n\n---\n\n## 📜 历史版本（原仓库更新日志，保留）\n\n"


def build() -> dict:
    old = {}
    if VERSION_FILE.exists():
        try:
            old = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] 读取旧 version.json 失败: {e}")

    old_notes = (old.get("release_notes") or "").strip()
    notes = NEW_RELEASE_NOTES
    if old_notes:
        # 保留原仓库日志原文（若旧日志本身已带历史标题，则不再重复添加标题）
        if "历史版本" in old_notes:
            notes = notes + "\n\n" + old_notes
        else:
            notes = notes + HISTORY_TITLE + old_notes

    return {
        "version": VERSION,
        "published_at": PUBLISHED_AT,
        "download_url": f"https://github.com/{REPO}/releases/download/{VERSION}/ComfyNexus-{VERSION}-win64.zip",
        "file_size": old.get("file_size", 0),
        "file_hash": old.get("file_hash", ""),
        "release_notes": notes,
    }


def main() -> int:
    data = build()
    VERSION_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ok] 已生成 {VERSION_FILE}（version={data['version']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
