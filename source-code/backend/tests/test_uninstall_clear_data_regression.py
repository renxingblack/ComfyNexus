# -*- coding: utf-8 -*-
"""
卸载「清除数据」逻辑防回退测试

这些断言全部针对源码文本，防止后人把安全逻辑改回危险写法。
每一个都对应一次真实踩坑或用户明确提出的硬要求。

运行：python backend/tests/test_uninstall_clear_data_regression.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent          # source-code/
REPO = ROOT.parent                                            # 仓库根
ISSINC = ROOT / "scripts" / "uninstall_clear_data.issinc"
ISS = ROOT / "build_installer.iss"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def main():
    if not ISSINC.exists():
        print(f"缺少文件：{ISSINC}")
        return 1
    if not ISS.exists():
        print(f"缺少文件：{ISS}")
        return 1

    inc = ISSINC.read_text(encoding="utf-8")
    iss = ISS.read_text(encoding="utf-8")

    print("\n[1] 入口与挂载")
    check("1.1 安装器 include 了卸载逻辑",
          "uninstall_clear_data.issinc" in iss)
    check("1.2 有 InitializeUninstall 询问函数",
          "function InitializeUninstall" in iss)
    check("1.3 有 CurUninstallStepChanged",
          "procedure CurUninstallStepChanged" in iss)
    check("1.4 在 usUninstall 阶段清除（程序文件仍在，指纹可查）",
          "usUninstall" in iss and "CNX_ClearAppData" in iss)

    print("\n[2] 绝不允许整目录强删（用户核心要求）")
    # 危险写法：把安装目录整个 DelTree 掉，或按顶层目录名直接 DelTree
    bad_patterns = [
        (r"DelTree\s*\(\s*ExpandConstant\('\{app\}'\)", "DelTree(ExpandConstant('{app}'))"),
        (r"DelTree\s*\(\s*Root\s*,", "DelTree(Root, ...)"),
        (r"DelTree\s*\(\s*AppDir\s*,", "DelTree(AppDir, ...)"),
    ]
    for pat, label in bad_patterns:
        check(f"2.x 未出现 {label}", not re.search(pat, inc))

    # 顶层 data/config/logs/cache 不能走 CNX_PurgeTree（整棵删）
    tree_calls = re.findall(r"Rc := CNX_PurgeTree\(Target", inc)
    check("2.y CNX_PurgeTree 只允许用于 _internal / download",
          len(tree_calls) == 2, f"实际 {len(tree_calls)} 处")

    print("\n[3] 条目级白名单")
    for item in ["ai_assistant.db", "gallery", "plugins", "comfynexus_*.log",
                 "settings.json", "environments.json"]:
        check(f"3.x 白名单含 {item}", item in inc)
    check("3.y 有通配匹配函数 CNX_NameMatches", "function CNX_NameMatches" in inc)
    check("3.z 不在白名单的条目会保留", "非本程序文件，保留" in inc)

    print("\n[4] ComfyUI 保护区")
    check("4.1 读取 config\\environments.json",
          r"config\environments.json" in inc)
    check("4.2 用 Utf8Decode 解码（路径可能含中文）",
          "Utf8Decode" in inc)
    check("4.3 抽取绝对路径而非依赖字段名",
          "CNX_ExtractProtectedPaths" in inc)
    check("4.4 区分盘符路径与 UNC",
          r"':\'" in inc or "':\\'" in inc)
    check("4.5 命中保护区即跳过（文件与目录都判）",
          "CNX_HitProtected" in inc and inc.count("CNX_HitProtected(") >= 3)
    check("4.6 嵌套在 data 内时只保留该子树（PARTIAL 而非整层放过）",
          "PARTIAL" in inc or "已清可删内容" in inc)
    check("4.7 报告里写明保护了哪些路径",
          "ComfyUI 环境/模型路径，已保护" in inc)

    print("\n[5] 指纹校验（认不出来就不删）")
    check("5.1 有 CNX_IsPlausibleAppDir", "function CNX_IsPlausibleAppDir" in inc)
    check("5.2 拒绝盘符根", "Length(R) <= 3" in inc)
    check("5.3 拒绝系统目录", "CNX_Inside(ExpandConstant('{win}'), R)" in inc)
    check("5.4 有逐项指纹 CNX_OwnedByApp", "function CNX_OwnedByApp" in inc)
    check("5.5 指纹不符时保留并记录",
          "未发现本程序特征" in inc)

    print("\n[6] 符号链接 / junction 不跟随")
    check("6.1 用 GetFileAttributesW 判断",
          "CNX_GetFileAttributesW" in inc)
    check("6.2 检查 reparse point 标志", "CNX_ATTR_REPARSE" in inc
          or "$400" in inc)
    check("6.3 有 CNX_IsReparsePoint", "function CNX_IsReparsePoint" in inc)

    print("\n[7] 目录只在空了之后才移除")
    check("7.1 用 RemoveDir（空目录才能删）", "RemoveDir(" in inc)
    check("7.2 安装器用 dirifempty 兜底",
          "dirifempty" in iss)

    print("\n[8] 静默卸载默认保留数据")
    check("8.1 静默模式下默认不清数据",
          "UninstallSilent()" in iss)
    check("8.2 默认按钮是「否」", "MB_DEFBUTTON2" in iss)
    check("8.3 支持 /CLEARDATA 显式指定",
          "/CLEARDATA" in iss)

    print("\n[9] uninst 收尾：必须异步、必须在卸载器退出之后")
    # 历史教训：曾经在 usPostUninstall 里同步调 CNX_CleanupUninstallerDir，
    # 卸载器还要写 _unins-done.tmp，被提前清空后整个收尾中断。
    if "usPostUninstall" in iss:
        seg = iss[iss.index("usPostUninstall"):]
        seg = seg[:600]
        check("9.1 usPostUninstall 段内不全同步清理",
              "DelTree" not in seg and "RemoveDir" not in seg)
    else:
        check("9.1 未使用 usPostUninstall", True)

    # 现在改用「脱离进程的外部脚本」：卸载器删不掉正在运行的自己
    # （unins000.exe 占用 -> uninst 非空 -> dirifempty 失效 -> 独立目录残留）。
    check("9.2 定义了延迟收尾函数",
          "function CNX_ScheduleUninstallerCleanup" in inc)
    check("9.3 安装器在 usUninstall 里排入该脚本",
          "CNX_ScheduleUninstallerCleanup" in iss)
    check("9.4 脚本必须异步启动（ewNoWait，否则挡住卸载器退出）",
          "ewNoWait" in inc)
    check("9.5 Windows 下隐藏窗口（SW_HIDE）", "SW_HIDE" in inc)
    # 顺序铁律：先等 unins*.exe 删得掉（= 卸载器已退出），才能动 uninst。
    retry_at = inc.find(":retry")
    settle_at = inc.find(":settle")
    drop_at = inc.find(":dropapp")
    check("9.6 脚本先轮询等卸载器退出，再收尾",
          -1 < retry_at < settle_at < drop_at,
          f"retry={retry_at} settle={settle_at} drop={drop_at}")
    # 关键安全点：删安装目录本身之前必须确认 uninst 已经没了，
    # 否则可能在他人还有文件时误删（rd 对非空目录本就失败，这里是双保险）。
    check("9.7 只有 uninst 清掉后才尝试删安装目录",
          "if exist \"%UNI%\" goto done" in inc and "rd \"%APP%\"" in inc)
    check("9.8 用普通 rd 删安装目录（非空必失败，天然保护混用目录）",
          "rd /s /q \"%APP%\"" not in inc)
    check("9.9 脚本自删，不留在 %TEMP%",
          "del /f /q \"%~f0\"" in inc)

    print("\n[10] 像素级安全网：注释不能含 { 模板（会截断 Pascal 注释）")
    # {app} 出现在 { } 注释里会让注释提前结束并引发语法错，
    # 编译期就炸。这里只检查 { } 注释块内。
    brace_comments = re.findall(r"\{[^{}]*\}", inc)
    bad = [c for c in brace_comments if "{app}" in c or "<安装目录>" in c and False]
    check("10.1 花括号注释里无模板占位", not bad,
          str(bad[:2]))

    print("\n[11] 版本号一致性")
    ver_py = (ROOT / "comfy_nexus_version.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(v[\d.]+)"', ver_py)
    ver = m.group(1) if m else ""
    check("11.1 comfy_nexus_version.py 有版本号", bool(ver), ver)
    bv = (ROOT / "scripts" / "build_version_json.py").read_text(encoding="utf-8")
    mb = re.search(r'^VERSION\s*=\s*"(v[\d.]+)"', bv, re.M)
    check("11.2 build_version_json.py VERSION 与之一致",
          bool(mb) and mb.group(1) == ver, f"{mb.group(1) if mb else '?'} vs {ver}")
    mi = re.search(r'#define MyAppVersion "([\d.]+)"', iss)
    check("11.3 build_installer.iss MyAppVersion 一致",
          bool(mi) and f"v{mi.group(1)}" == ver, f"{mi.group(1) if mi else '?'}")
    cv = (ROOT / "scripts" / "changelog_versions.py").read_text(encoding="utf-8")
    check("11.4 changelog_versions.py 有该版本条目",
          f'"version": "{ver}"' in cv)

    print("\n[12] 反馈链接指向本项目仓库")
    fb = ROOT / "frontend" / "src" / "pages" / "FeedbackPage.tsx"
    txt = fb.read_text(encoding="utf-8")
    check("12.1 提交链接为 renxingblack/ComfyNexus",
          "renxingblack/ComfyNexus/issues/new" in txt)
    # 只检查实际 URL 字面量，注释里提到旧仓库是允许的
    urls = re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)/issues/new", txt)
    check("12.2 不含指向原作者仓库的 issues URL",
          all(u == "renxingblack/ComfyNexus" for u in urls), str(urls))

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'=' * 62}")
    print(f"合计 {len(results)} 项：{passed} PASS / {len(failed)} FAIL")
    if failed:
        for n in failed:
            print("  -", n)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
