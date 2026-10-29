# -*- coding: utf-8 -*-
"""
环境配置「字段往返完整性」防回退测试

背景（用户实际反馈）：
    环境设置 → 通用设置 → 工作区目录映射 → 工作流目录，
    填了路径、点保存，提示保存成功，但界面回来还是空的。

根因：
    后端有两张白名单映射表，`update_environment` 用它们把前端驼峰写进磁盘，
    `_format_acceleration_config` 用它们把磁盘蛇形回给前端。
    表里漏了 `workflowDirectory <-> workflow_directory`，于是：
      - 写入时被丢弃 → 磁盘上根本没有这个键
      - 读取时被过滤 → 即便磁盘上有，回给前端也没有
    两种情况表现都是「保存不成功」。

这类 bug 极难自查：接口返回 success、日志没有 error、前端也 setState 了，
只是字段被静默吃掉。所以这里做**表驱动**的全字段往返校验 ——
以后再往 AccelerationSettings 加字段，忘了同步映射表就会立刻红。

运行：python backend/tests/test_env_config_roundtrip.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent      # source-code/
sys.path.insert(0, str(ROOT))

from backend.src.core.env.config_transformer import ConfigTransformer   # noqa: E402
from backend.src.core.env.environment_manager import (    # noqa: E402
    _ACCELERATION_DEFAULTS,
    _ACCELERATION_FIELD_MAPPING,
    _GENERAL_FIELD_MAPPING,
    EnvironmentManager,
)
from backend.src.core.env.types import (                  # noqa: E402
    AccelerationSettings,
    GeneralSettings,
)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def disk_roundtrip():
    """真写一个 environments.json，验证保存路径确实落盘。"""
    import json
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="cnx_cfg_"))
    cfg_file = tmp / "environments.json"
    comfy = str(tmp / "comfy")
    cfg_file.write_text(json.dumps({
        "environments": [{
            "id": "e1", "name": "t", "alias": "测试", "path": comfy,
            "config": {
                "general": {"comfyui_path": comfy, "python_path": "", "pip_path": "", "git_path": ""},
                "acceleration": {}, "folder_shortcuts": [], "advanced_env_vars": "",
            },
        }],
        "current_environment_id": "e1",
    }, ensure_ascii=False), encoding="utf-8")

    class FakeCM:
        def load_config(self):
            return json.loads(cfg_file.read_text(encoding="utf-8"))

        def save_config(self, d):
            cfg_file.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            return True

        def get_current_environment_id(self):
            return "e1"

    mgr = EnvironmentManager.__new__(EnvironmentManager)
    mgr.config_manager = FakeCM()

    wf = "D:" + chr(92) + "我的工作流" + chr(92) + "作品目录"
    res = mgr.update_environment("e1", {"acceleration": {"workflowDirectory": wf}})
    if not res.get("success"):
        return False, f"update_environment 失败: {res.get('error_message')}"

    on_disk = (json.loads(cfg_file.read_text(encoding="utf-8"))
               ["environments"][0]["config"]["acceleration"].get("workflow_directory"))
    if on_disk != wf:
        return False, f"磁盘值为 {on_disk!r}，期望 {wf!r}"

    # 再确认能原样回给前端
    back = res["environment"].get("acceleration", {}).get("workflowDirectory")
    if back != wf:
        return False, f"读回值为 {back!r}，期望 {wf!r}"
    return True, ""


def main():
    print("\n[1] 用户报的那个字段：工作流目录")
    check("1.1 读取映射表含 workflow_directory",
          "workflow_directory" in _ACCELERATION_FIELD_MAPPING,
          "读回来会丢字段")
    check("1.2 映射目标就是前端用的 workflowDirectory",
          _ACCELERATION_FIELD_MAPPING.get("workflow_directory") == "workflowDirectory")
    check("1.3 默认值表含 workflow_directory（否则兜底成 None）",
          "workflow_directory" in _ACCELERATION_DEFAULTS,
          f"实际默认 {_ACCELERATION_DEFAULTS.get('workflow_directory')!r}")
    check("1.4 默认值是空字符串而非 None",
          _ACCELERATION_DEFAULTS.get("workflow_directory") == "")

    # 写入侧：update_environment 内部的驼峰->蛇形表必须含该字段
    src = (ROOT / "backend" / "src" / "core" / "env" / "environment_manager.py").read_text(encoding="utf-8")
    upd = src[src.index("def update_environment"):]
    upd = upd[: upd.index("def ", 100)]
    check("1.5 保存时会把 workflowDirectory 写进磁盘",
          '"workflowDirectory": "workflow_directory"' in upd,
          "写不进去 -> 磁盘上没有这个键")

    print("\n[2] 全字段往返：AccelerationSettings 每个字段都必须能存能取")
    # 这是本篇的核心。不做单字段特判，而是按 dataclass 的实际字段逐个走一遍，
    # 保证「新增字段忘了加映射」这种错误不会在悄悄发生。
    acc_field_names = list(AccelerationSettings.__dataclass_fields__.keys())
    # geek_mode 是嵌套对象，单独处理，不参与平面映射
    skip = {"geek_mode"}
    unmapped = [
        f for f in acc_field_names
        if f not in skip and f not in _ACCELERATION_FIELD_MAPPING
    ]
    check("2.1 AccelerationSettings 的所有平面字段都在映射表中",
          not unmapped,
          f"漏了 {unmapped}" if unmapped else f"{len(acc_field_names) - len(skip)} 个字段全覆盖")

    # 每个前端键必须能对应回一个后端键（双向唯一，防止两个字段映射到同一处）
    front_to_back = {}
    dup = []
    for back, front in _ACCELERATION_FIELD_MAPPING.items():
        if front in front_to_back:
            dup.append(front)
        front_to_back[front] = back
    check("2.2 前端键无重复映射", not dup, f"重复 {dup}" if dup else "")

    print("\n[3] 默认值表与映射表必须同键")
    missing_defaults = [k for k in _ACCELERATION_FIELD_MAPPING if k not in _ACCELERATION_DEFAULTS]
    check("3.1 每个映射字段都有默认值",
          not missing_defaults,
          f"缺默认 {missing_defaults}" if missing_defaults else "")

    print("\n[4] general 配置同样做往返校验")
    gen_fields = list(GeneralSettings.__dataclass_fields__.keys())
    gen_missing = [f for f in gen_fields if f not in _GENERAL_FIELD_MAPPING]
    check("4.1 GeneralSettings 所有字段都在映射表中",
          not gen_missing,
          f"漏了 {gen_missing}" if gen_missing else f"{len(gen_fields)} 个字段全覆盖")

    print("\n[5] 端到端：写进去的值读回来必须一模一样")
    mgr = EnvironmentManager.__new__(EnvironmentManager)   # 只借格式化方法，不碰磁盘
    sample_cn = r"D:\我的工作流\作品目录"                    # 中文 + 空格敏感路径
    backend_accel = {
        "workflow_directory": sample_cn,
        "input_directory": "in",
        "output_directory": "out",
        "user_directory": "user",
    }
    formatted = mgr._format_acceleration_config(backend_accel)
    check("5.1 中文路径原样回给前端",
          formatted.get("workflowDirectory") == sample_cn,
          repr(formatted.get("workflowDirectory")))
    check("5.2 其它同级字段未受影响",
          formatted.get("inputDirectory") == "in" and formatted.get("userDirectory") == "user")

    # 空环境（从未配置过）不应崩，且给空串
    empty_formatted = mgr._format_acceleration_config({})
    check("5.3 未配置过的环境返回空串而非 None",
          empty_formatted.get("workflowDirectory") == "",
          repr(empty_formatted.get("workflowDirectory")))

    print("\n[6] types 层：from_dict 要兼容两种命名")
    # 历史数据里可能存的是驼峰（老版本写的），必须都能读
    a1 = AccelerationSettings.from_dict({"workflow_directory": sample_cn})
    a2 = AccelerationSettings.from_dict({"workflowDirectory": sample_cn})
    check("6.1 蛇形命名可读", a1.workflow_directory == sample_cn)
    check("6.2 驼峰命名可读（兼容老配置）", a2.workflow_directory == sample_cn)
    check("6.3 to_dict 统一写蛇形",
          a1.to_dict().get("workflow_directory") == sample_cn)
    # Windows 路径的反斜杠必须一个字都不改：后续交给 mklink /J，
    # 一旦被换成 / 或规范化，联接就会指向错误的目录。
    bs = "D:" + chr(92) + "a" + chr(92) + "b"
    check("6.4 反斜杠原样保留（不做路径规范化）",
          AccelerationSettings.from_dict(
              {"workflow_directory": bs}).workflow_directory == bs,
          repr(AccelerationSettings.from_dict({"workflow_directory": bs}).workflow_directory))

    print("\n[7] 前端侧：字段声明与保存链路")
    ts = (ROOT / "frontend" / "src" / "types" / "environment.ts").read_text(encoding="utf-8")
    check("7.1 前端类型声明了 workflowDirectory", "workflowDirectory" in ts)

    tab = (ROOT / "frontend" / "src" / "components" / "env" / "TabContainer.tsx").read_text(encoding="utf-8")
    check("7.2 TabContainer 把该字段归入 acceleration（不在白名单会被静默丢弃）",
          "workflowDirectory" in tab,
          "未列入 knownAccelerationFields 时会被 console.warn 丢弃")

    general = (ROOT / "frontend" / "src" / "components" / "env" / "GeneralTab.tsx").read_text(encoding="utf-8")
    check("7.3 GeneralTab 的 pathFields 含 workflowDirectory",
          "workflowDirectory" in general)

    print("\n[8] 启动前确实会建立目录联接")
    ctrl = (ROOT / "backend" / "src" / "bridge" / "controllers" / "environment_controller.py").read_text(encoding="utf-8")
    check("8.1 构建启动参数前调用 ensure_workflow_junction",
          "ensure_workflow_junction" in ctrl)
    check("8.2 调用点在 build_args 之前",
          ctrl.index("ensure_workflow_junction") < ctrl.index("build_args", ctrl.index("ensure_workflow_junction")),
          "")

    print("\n[9] 第三张映射表：config_transformer（导入导出 / 预设）")
    # 这张表用于配置导入导出和预设应用。未映射的键会「保持原样」，
    # 所以不会崩、也不报错，但导入时驼峰 key 写不进后端的蛇形字段 —— 静默丢。
    ct_acc_missing = sorted(
        set(AccelerationSettings.__dataclass_fields__)
        - skip
        - set(ConfigTransformer.FRONTEND_TO_BACKEND.values())
    )
    check("9.1 转换器覆盖 acceleration 全部字段",
          not ct_acc_missing,
          f"漏了 {ct_acc_missing}" if ct_acc_missing else "全覆盖")

    ct_gen_missing = sorted(
        set(GeneralSettings.__dataclass_fields__)
        - set(ConfigTransformer.FRONTEND_TO_BACKEND.values())
    )
    check("9.2 转换器覆盖 general 全部字段",
          not ct_gen_missing,
          f"漏了 {ct_gen_missing}" if ct_gen_missing else "全覆盖")

    not_roundtrip = [
        k for k in ConfigTransformer.FRONTEND_TO_BACKEND
        if ConfigTransformer.BACKEND_TO_FRONTEND.get(
            ConfigTransformer.FRONTEND_TO_BACKEND[k]) != k
    ]
    check("9.3 双向映射自洽（驼峰->蛇形->驼峰能还原）",
          not not_roundtrip,
          f"不自洽 {not_roundtrip}" if not_roundtrip else "")

    print("\n[10] 真实磁盘往返：update_environment 写盘后能原样读回")
    # 前面都是纯内存校验。这一节真的写一个 environments.json 到临时目录，
    # 走 update_environment 的完整写盘路径 —— 因为用户感受到的「没保存」
    # 就是磁盘上真的没有这个键。
    ok, detail = disk_roundtrip()
    check("10.1 磁盘上出现 workflow_directory 且值正确", ok, detail)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'=' * 58}")
    print(f"合计 {len(results)} 项：{passed} PASS / {len(failed)} FAIL")
    if failed:
        print("失败项：")
        for n in failed:
            print("  -", n)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
