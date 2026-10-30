"""
生成 version.json（应用版本 + 完整更新日志）

## 数据结构（增量式，三段拼接）

`release_notes`  =  自有版本日志（本仓库开发的部分）
                  +  原仓库历史原文（Allen-xxa/ComfyNexus，一字不改）

具体：
  ① **当前版本**（如 v1.3.1）：来自 `scripts/changelog_versions.py` 的 body_zh
  ② **历史自有版本**（v1.3.0、v1.2.6 …）：同样来自 changelog_versions.py，
     用 `**vX.Y.Z · 日期**` 粗体行分隔，前端据此拆成可折叠的多张卡片
  ③ **原仓库历史**（v1.2.6 之前共 30 个版本）：来自 `scripts/original_releases.json`，
     逐字保留，由 `_verify_history_intact()` 硬校验

## 为什么这么设计（踩过的坑）

1. **本地 version.json 是权威源**：随包发布、离线可读、不受远端 Release 写错影响。
   远端 Releases 只作增量补充（见前端 `githubApi.ts::fetchReleases`）。

2. **历史段落不能丢**：曾经只用「当前版本正文」生成 release_notes，
   导致 48539 字的完整日志缩到 1920 字，历史版本全部消失，
   用户看到的就是「更新日志不完整」。现在由 `_verify_history_intact()`
   在构建阶段硬校验，任何缺失都会让构建直接失败。

3. **`**vX.Y.Z · 日期**` 是前端唯一认的分隔格式**：前端正则
   `^\\*\\*(.+?)\\s*·\\s*(\\d{4}-\\d{2}-\\d{2})\\*\\*\\s*$`。
   不用 `### <tag>`，因为原仓库正文自带 `## 问题修复` 这类二级标题，
   用 `###` 会导致层级倒挂、正文被切碎。

## 增量维护方式

新增一个版本时只需要：
  1. 在 `changelog_versions.py` 的 VERSIONS 里**追加一条**（不需要动旧条目）；
  2. 改本文件的 VERSION / PUBLISHED_AT；
  3. 运行 `python scripts/build_version_json.py`。
原仓库快照只在原作者发了新 Release 时才需要更新（`refresh_releases.py`）。

用法：python scripts/build_version_json.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 打包时 build_exe.spec 收集的是「仓库根 / version.json」（spec 里写作 ../version.json），
# 也就是说真正的发布源是仓库根那一份，而不是 source-code 下的同名文件。
# 两处内容必须一致，否则软件内「关于 - 更新日志」显示的是旧日志。
VERSION_FILE = ROOT.parent / "version.json"
MIRROR_VERSION_FILE = ROOT / "version.json"
ORIGINAL_RELEASES_FILE = Path(__file__).resolve().parent / "original_releases.json"

# 引入自有版本日志表
sys.path.insert(0, str(Path(__file__).resolve().parent))
from changelog_versions import VERSIONS, get_local_notes  # noqa: E402

VERSION = "v1.3.6"
PUBLISHED_AT = "2026-10-30T00:00:00Z"
REPO = "renxingblack/ComfyNexus"

HISTORY_TITLE = (
    "\n\n---\n\n## 📜 历史版本\n\n"
    "> 以下为本项目 [renxingblack/ComfyNexus](https://github.com/renxingblack/ComfyNexus) "
    "与原作者 [Allen-xxa/ComfyNexus](https://github.com/Allen-xxa/ComfyNexus) 的"
    "全部历史 Release 日志，按发布时间倒序。\n"
    "> 原作者部分**一字未改**，沿用其原有标题层级（可能包含多个一级标题），"
    "并非排版错误。\n\n"
)


def _load_original_releases() -> list:
    """读取原作者全部 Release 原文快照"""
    if not ORIGINAL_RELEASES_FILE.exists():
        print(f"[warn] 未找到原仓库日志快照: {ORIGINAL_RELEASES_FILE}")
        return []
    try:
        data = json.loads(ORIGINAL_RELEASES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[warn] 读取原仓库日志快照失败: {e}")
        return []


def normalize_tag(tag: str) -> str:
    """版本号归一：去空白、转小写、去前导 v。

    与前端 `githubApi.ts::normalizeTag()` 保持完全一致 ——
    否则 `v1.2.6` 与 `1.2.6` 会被当成两个不同版本，出现重复卡片。
    """
    return (tag or "").strip().lower().lstrip("v")


def _format_history(releases: list) -> str:
    """把原仓库 Release 列表拼成历史段落，**原文一字不改**

    用户明确要求：「原来仓库中 version.json 内容要做完全保留」。
    因此这里不做任何改写：

    - 不删除原文自带的 `# ComfyNexus vX.Y.Z 更新日志` 这类 H1；
    - 不降级原文的 `## 问题修复` 等标题；
    - 不重排、不合并、不删减任何一行。

    版本分隔用「粗体版本名 + 水平线」，而不是 `### <tag>`：
    这样既能把每个版本清楚分开，又不需要动原文的标题层级。
    """
    if not releases:
        return ""

    parts = []
    for rel in releases:
        tag = rel.get("tag_name") or ""
        date = (rel.get("published_at") or "")[:10]
        body = (rel.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
        body = body.strip()
        label = f"{tag} · {date}" if date else tag
        parts.append(f"**{label}**\n\n{body}\n")

    return "\n---\n\n".join(parts)


def _format_own_history(current_version: str) -> str:
    """把「除当前版本之外」的**自有**版本日志拼成历史段落。

    **必须排除原仓库已有的版本**（本项目是 v1.2.6 的分支）：
      v1.2.6 是原作者发布的版本，它的正文已经在 `original_releases.json`
      里逐字保留。若这里再拼一份，最终日志会出现**两个 v1.2.6 卡片**
      （实测出现 33 条而正确应为 32 条），用户看到重复版本。

    判据：只拼「原仓库快照里不存在」的版本号。
    格式与前端 `splitLocalChangelog()` 的正则严格对应：
        **vX.Y.Z · YYYY-MM-DD**
    任何改动都必须同步改前端正则，否则历史卡片会少几条。
    """
    upstream_tags = {normalize_tag(r.get("tag_name") or "")
                     for r in _load_original_releases()}
    parts = []
    for v in sorted(VERSIONS, key=lambda x: x.get("date") or "", reverse=True):
        ver = v.get("version") or ""
        if ver == current_version:
            continue
        # 原仓库已发布的版本 → 由 original_releases.json 提供，此处跳过
        if normalize_tag(ver) in upstream_tags:
            continue
        body = (v.get("body_zh") or "").strip()
        if not body:
            continue
        date = v.get("date") or ""
        label = f"{ver} · {date}" if date else ver
        parts.append(f"**{label}**\n\n{body}\n")
    return "\n---\n\n".join(parts)


def _verify_history_intact(notes: str, releases: list, own_versions: list) -> None:
    """强制校验：原仓库每个 Release 的正文必须逐字出现在最终日志里

    这是硬约束。之前为了「标题层级好看」删过原文 H1、降过原文标题，
    结果就是「原仓库内容没有完全保留」。现在任何改写都会在这里暴露。
    """
    if not releases:
        print("[warn] 无原仓库快照，跳过历史校验")
        return
    missing_tags = []
    lost_lines = []
    notes_lines = {ln.strip() for ln in notes.split("\n")}
    for rel in releases:
        tag = rel.get("tag_name") or ""
        if tag and tag not in notes:
            missing_tags.append(tag)
        body = (rel.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
        for ln in body.split("\n"):
            s = ln.strip()
            if not s:
                continue
            if s not in notes_lines:
                lost_lines.append((tag, s[:80]))
    if missing_tags:
        raise SystemExit(f"[FATAL] 原仓库历史版本缺失: {missing_tags}")
    if lost_lines:
        print(f"[FATAL] 原仓库正文有 {len(lost_lines)} 行未原样保留：")
        for tag, s in lost_lines[:10]:
            print(f"  [{tag}] {s}")
        raise SystemExit(1)

    # 自有版本也必须齐全
    own_missing = [v["version"] for v in own_versions
                   if v["version"] not in notes]
    if own_missing:
        raise SystemExit(f"[FATAL] 自有版本日志缺失: {own_missing}")

    total = sum(
        len([ln for ln in (r.get("body") or "").replace("\r\n", "\n").split("\n")
             if ln.strip()])
        for r in releases
    )
    print(f"[ok] 历史完整性校验通过：原仓库 {len(releases)} 个版本 / {total} 行正文原样保留")
    print(f"[ok] 自有版本 {len(own_versions)} 个全部存在")


def _count_entries(notes: str) -> int:
    """统计 `**vX.Y.Z · 日期**` 分隔行数量（= 前端能拆出的历史卡片数）"""
    re_sep = re.compile(r"^\*\*(.+?)\s*·\s*(\d{4}-\d{2}-\d{2})\*\*\s*$", re.M)
    return len(re_sep.findall(notes))


def _verify_split_shape(notes: str, releases: list, own_versions: list) -> None:
    """校验日志能被前端正确拆成「1 当前 + N 历史」的形状。

    **这条校验防的是「版本卡片被吞进当前版本」这类静默故障**：
    前端 `splitLocalChangelog()` 的判断逻辑是——
      - 找到第一个 `## 📜 历史版本` 标记；
      - 标记**之前**全部当作当前版本正文；
      - 标记**之后**按 `**版本 · 日期**` 逐条切分。

    所以只要提前放了 `**vX.Y.Z · 日期**` 这样的行，或者历史段被拆成
    两个不同标题的章节，就会出问题，而页面上不会报错，只是「少了一张卡片」
    或「当前版本里混进了上个版本的日志」—— 用户只能看出"日志不完整"。

    实测踩过两次：
      ① 自有历史单用 `## 📚 更早版本` → v1.3.0 整段并进当前版本正文（9758 字符）；
      ② v1.2.6 既有自有条目又在原仓库快照里 → 出现两个 v1.2.6 卡片（33 条而非 32 条）。
    """
    marker = "## 📜 历史版本"
    at = notes.find(marker)
    if at < 0:
        raise SystemExit(f"[FATAL] 日志缺少 `{marker}` 标记，历史版本不会显示")

    head = notes[:at]
    history = notes[at:]

    re_sep = re.compile(r"^\*\*(.+?)\s*·\s*(\d{4}-\d{2}-\d{2})\*\*\s*$", re.M)

    # ① 当前版本正文里不能出现版本分隔行
    stray = re_sep.findall(head)
    if stray:
        raise SystemExit(
            f"[FATAL] 当前版本正文里混入了版本分隔行: {[t for t, _ in stray]}"
            f"（会被前端当成正文，导致历史卡片消失）"
        )

    # ② 历史段里的版本号不能重复
    tags = [t.strip() for t, _ in re_sep.findall(history)]
    dup = {t for t in tags if tags.count(t) > 1}
    if dup:
        raise SystemExit(f"[FATAL] 历史版本号重复: {sorted(dup)}")

    # ③ 每个原仓库版本都要在历史段里
    upstream = {normalize_tag(r.get("tag_name") or "") for r in releases}
    got = {normalize_tag(t) for t in tags}
    missing = upstream - got
    if missing:
        raise SystemExit(f"[FATAL] 原仓库版本未出现在历史段: {sorted(missing)}")

    # ④ 自有历史版本（非原仓库发布过的）也要在历史段里
    for v in own_versions:
        ver = v.get("version") or ""
        if normalize_tag(ver) in upstream:
            continue          # 原仓库版本由快照提供
        if ver == VERSION:
            continue          # 当前版本就是正文
        if normalize_tag(ver) not in got:
            raise SystemExit(f"[FATAL] 自有历史版本未出现在历史段: {ver}")

    print(f"[ok] 拆分形状校验通过：当前版本 1 条 + 历史 {len(tags)} 条")


def build() -> dict:
    old = {}
    if VERSION_FILE.exists():
        try:
            old = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] 读取旧 version.json 失败: {e}")

    current = get_local_notes(VERSION)
    if not current.strip():
        raise SystemExit(f"[FATAL] 未找到 {VERSION} 的日志正文（changelog_versions.py）")

    header = (
        f"# ComfyNexus {VERSION} 更新日志\n\n"
        f"**发布日期**：{PUBLISHED_AT[:10]}  \n"
        f"**版本类型**：Stable  \n\n"
        f"---\n\n"
    )
    notes = header + current.strip()

    # 自有历史（v1.3.0 等）与原仓库历史必须放在**同一个 `## 📜 历史版本` 章节**下。
    #
    # 为什么不能分成两个章节（实测踩过）：
    #   前端 `splitLocalChangelog()` 只在**第一个** `## 📜 历史版本` 标记之后
    #   才开始按 `**vX.Y.Z · 日期**` 拆分。若自有历史单独用一个
    #   `## 📚 更早版本` 章节，它会被并进「当前版本」正文里
    #   （实测：当前版本正文长度 9758 字符，把 v1.3.0 整段吞了进去），
    #   于是 v1.3.0 没有独立卡片、当前版本卡片里混着上一个版本的日志。
    own_history = _format_own_history(VERSION)
    releases = _load_original_releases()
    history = _format_history(releases)

    blocks = [b for b in (own_history, history) if b]
    if blocks:
        notes += HISTORY_TITLE + "\n---\n\n".join(blocks)

    _verify_history_intact(notes, releases, VERSIONS)
    _verify_split_shape(notes, releases, VERSIONS)

    return {
        "version": VERSION,
        "published_at": PUBLISHED_AT,
        "download_url": (
            f"https://github.com/{REPO}/releases/download/{VERSION}/"
            f"ComfyNexus-{VERSION}-win64.zip"
        ),
        "file_size": old.get("file_size", 0),
        "file_hash": old.get("file_hash", ""),
        "release_notes": notes,
    }


def main() -> int:
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    for target in (VERSION_FILE, MIRROR_VERSION_FILE):
        target.write_text(text, encoding="utf-8")
        print(f"[ok] 已写入 {target}")
    notes = data["release_notes"]
    print(f"[ok] version={data['version']}")
    print(f"[ok] release_notes 长度={len(notes)} 字符")
    # 分清两个数字，别混着看（上一轮就被自己的打印误导过）：
    #   _count_entries 统计的是**历史分隔行**（不含当前版本）；
    #   UI 上看到的卡片数 = 1（当前版本）+ 历史条数。
    hist_n = _count_entries(notes)
    print(f"[ok] 历史版本条数={hist_n}"
          f"（自有历史 + 原仓库 {len(_load_original_releases())}）")
    print(f"[ok] UI 卡片总数={hist_n + 1}（1 当前 + {hist_n} 历史）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
