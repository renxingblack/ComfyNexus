"""关于页布局回归测试（静态源码断言）

为什么是静态断言而不是跑真实窗口：
  真实排版要靠 CDP 在打包产物上量（见 D:/Downloads/ComfyNexus/_verify_about_layout.py
  与 _audit_about_geom.py）。但排版正确性依赖的几个**关键约束**极容易被后人
  "顺手清理掉"，而一旦清理就会退回用户报的那个 bug，且从现象极难反推。
  所以这里把约束钉死，谁改坏了跑这个测试立刻报错。

覆盖的历史故障（都是实测踩出来的，2026-10-26）：
  1. 根容器锁死 h-full + overflow-hidden —— 小窗内容远超窗口时直接裁掉，
     【更新日志】被压成几十像素，看不见内容也无法下拉。
  2. 无下限的 flex 压缩（min-h-0 + flex-1）—— 窗口一变矮就无限压扁，
     1280x800 时更新日志内部滚动区只剩 106px。
  3. 去掉 roomy:h-full —— flex-1 失去"可分配剩余空间"前提，退化成按内容取高，
     日志全文 4.9 万像素把卡片撑到 49142px（真实回归）。
  4. ChangelogSection 内部硬编码 h-full —— 与调用方高度类冲突，
     谁生效取决于 CSS 生成顺序，不可控。
  5. roomy 只用宽度断点 —— 1024x640 宽度够但高度差太多，必须同时判高度。
  6. roomy 阈值过低 —— 1280x800 被误判为 roomy，硬塞 3 列导致日志区过小。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ABOUT = ROOT / "frontend" / "src" / "pages" / "AboutPage.tsx"
CHANGELOG = ROOT / "frontend" / "src" / "components" / "about" / "ChangelogSection.tsx"
ABOUTSECTION = ROOT / "frontend" / "src" / "components" / "about" / "AboutSection.tsx"
TW = ROOT / "frontend" / "tailwind.config.js"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def read(p):
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def main():
    about = read(ABOUT)
    changelog = read(CHANGELOG)
    aboutsec = read(ABOUTSECTION)
    tw = read(TW)

    check("AboutPage.tsx 存在", bool(about), str(ABOUT))
    check("ChangelogSection.tsx 存在", bool(changelog), str(CHANGELOG))
    check("tailwind.config.js 存在", bool(tw), str(TW))
    if not (about and changelog and tw):
        print("\n关键文件缺失，后续断言跳过")
        return 1

    print("\n[1] 根容器：必须可滚，且不能写死 overflow-hidden")
    # 根容器带 data-page="about" 作为锚点（验证脚本依赖它）
    check("根容器有 data-page=\"about\" 锚点",
          'data-page="about"' in about,
          "CDP 验证脚本靠它定位关于页")
    # 抓根容器那一行
    root = ""
    for line in about.splitlines():
        if 'data-page="about"' in line:
            root = line
            break
    check("根容器带 overflow-y-auto", "overflow-y-auto" in root, root.strip())
    check("根容器高度用 h-full 锁一屏", "h-full" in root, root.strip())
    # 关键：不能出现 roomy:overflow-hidden（那会把"撑破"变成"裁掉"）
    check("根容器没有 roomy:overflow-hidden",
          "roomy:overflow-hidden" not in about,
          "写死 hidden 正是最初那个 bug 的形状")

    print("\n[2] 内层：min-h-full 给底，roomy 时 h-full 锁高")
    inner = ""
    for line in about.splitlines():
        if "min-h-full" in line and "flex" in line and "flex-col" in line:
            inner = line
            break
    check("内层是 flex flex-col + min-h-full", bool(inner), inner.strip())
    check("内层 roomy 时回 h-full",
          "roomy:h-full" in inner,
          "去掉它 flex-1 会退化→日志把卡片撑到 4.9 万像素")

    print("\n[3] 主体：roomy 才切 3 列，且网格行下限不能是 0")
    body = ""
    for line in about.splitlines():
        if "roomy:grid" in line and "grid-cols-3" in line:
            body = line
            break
    check("主体 roomy 时切 3 列网格", bool(body), body.strip() if body else "未找到")
    check("主体 roomy 时带 min-h-0",
          "roomy:min-h-0" in body,
          "缺它网格行会被内容顶破")
    check("网格行用 grid-rows-[1fr] 而不是 grid-rows-1",
          "roomy:grid-rows-[1fr]" in body and "roomy:grid-rows-1\"" not in body,
          "grid-rows-1 = minmax(0,1fr)，下限 0 会被压扁")

    print("\n[4] 更新日志：必须有可读下限")
    cl_line = ""
    for line in about.splitlines():
        if "ChangelogSection" in line and "className" in line:
            cl_line = line
            break
    check("compact 模式给固定高度 h-[420px]",
          "h-[420px]" in cl_line, cl_line.strip())
    check("roomy 模式用 roomy:h-auto 让 flex-1 接管",
          "roomy:h-auto" in cl_line, cl_line.strip())
    check("roomy 模式有 min-h-[340px] 可读下限",
          "roomy:min-h-[340px]" in cl_line,
          "防窗口变矮时被无限压扁")
    check("有 roomy:flex-1 吃掉剩余空间",
          "roomy:flex-1" in cl_line, cl_line.strip())

    print("\n[5] ChangelogSection 内部不得写死高度")
    # 组件内不能出现 h-full / size-full 之类与调用方冲突的高度类
    card_line = ""
    for line in changelog.splitlines():
        if "<Card" in line and "className" in line:
            card_line = line
            break
    check("Card 不硬编码 h-full", "h-full" not in card_line,
          card_line.strip())
    check("Card 保留 flex flex-col", "flex-col" in card_line, card_line.strip())

    print("\n[6] roomy 断点：必须同时判宽高，且阈值覆盖真实需求")
    m = re.search(r"roomy:\s*\{\s*raw:\s*'([^']+)'", tw)
    check("tailwind.config.js 定义了 roomy raw 断点", bool(m), m.group(1) if m else "未找到")
    if m:
        raw = m.group(1)
        check("断点同时判 min-width", "min-width" in raw, raw)
        check("断点同时判 min-height", "min-height" in raw, raw)
        check("断点用 and 组合", "and" in raw, raw)
        hm = re.search(r"min-height:\s*(\d+)px", raw)
        check("高度阈值 >= 820px", bool(hm) and int(hm.group(1)) >= 820,
              f"{hm.group(1)}px" if hm else "未找到")
        wm = re.search(r"min-width:\s*(\d+)px", raw)
        check("宽度阈值 >= 768px", bool(wm) and int(wm.group(1)) >= 768,
              f"{wm.group(1)}px" if wm else "未找到")
    # 必须写在 extend 里，否则覆盖默认 sm/md/lg
    check("roomy 定义在 extend 内（不覆盖默认断点）",
          re.search(r"extend:\s*\{[\s\S]{0,1200}?screens:\s*\{", tw) is not None,
          "写在外层会让全项目 md: 类失效")

    print("\n[7] 关于项目：标题与标语同行，且不溢出")
    # 注意：只扫 className="..." 里的类名，不要扫整个文件 ——
    # 文件注释里会写到「不要用 ml-[12ch]」这类反面说明，直接 grep 全文会误判。
    classnames = " ".join(re.findall(r'className="([^"]*)"', aboutsec))
    check("用 gap-x-[12ch] 而不是 ml-[12ch]",
          "gap-x-[12ch]" in classnames and "ml-[12ch]" not in classnames,
          "ml 在窄窗会把标语顶出容器")
    check("标题行允许 flex-wrap 换行",
          "flex-wrap" in classnames,
          "空间不足时才能优雅换行")

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
