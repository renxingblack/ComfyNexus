"""
原仓库更新日志「增量同步」脚本

## 职责

维护 `scripts/original_releases.json` 这份原仓库（Allen-xxa/ComfyNexus）
Release 原文快照，**只增不删**：

  - 远端有、本地没有的版本 → 追加（增量保存）
  - 本地有、远端也有的版本 → 若远端正文更长（作者补写了内容）则更新正文，
    否则保留本地原文（避免重复拉取把已有内容改坏）
  - 本地有、远端没有的版本 → **保留**（原仓库删过 Release 也不丢历史）

## 为什么必须「增量」而不是「整体覆盖」

用户明确要求：「在保存的原仓库日志基础上，不断增量保存日志」。

整体覆盖有三个实际风险（本项目都遇到过）：
  1. 网络失败时 `per_page` 默认值偏小 → 只回来几条，直接把 31 条历史冲成 3 条；
  2. 原仓库某条 Release 被作者手滑编辑成空 body → 覆盖后本地完整正文丢失；
  3. 原仓库删掉旧 Release → 覆盖后用户再也看不到那段历史。

增量合并从根上避免这三件事：网络拿到的永远只用来**补充**和**加长**，
从不用于缩短或删除本地已有的内容。

## 用法

    python scripts/sync_original_releases.py            # 增量同步
    python scripts/sync_original_releases.py --dry-run  # 只看会变什么
    python scripts/sync_original_releases.py --repo Allen-xxa/ComfyNexus
"""

import argparse
import json
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "original_releases.json"
DEFAULT_REPO = "Allen-xxa/ComfyNexus"

# 只保留这些字段，控制快照体积（body 必须完整）
KEEP_FIELDS = ("tag_name", "name", "body", "published_at",
               "html_url", "prerelease", "draft")


def normalize_tag(tag: str) -> str:
    """版本号归一：去空白、转小写、去前导 v（与前端 normalizeTag 一致）"""
    return (tag or "").strip().lower().lstrip("v")


def fetch_releases(repo: str, per_page: int = 100, timeout: int = 60) -> list:
    """拉取远端全部 Release。**per_page 必须是 100**（GitHub 单页上限）。

    曾经默认 3，导致远端 31 个 Release 只回来 3 条，
    历史日志整段缺失 —— 这是「更新日志不完整」的历史根因之一。
    """
    ctx = ssl.create_default_context()
    # 某些环境证书链不完整，这里放宽（只读公开 API，无凭据风险）
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),          # 绕开系统代理
        urllib.request.HTTPSHandler(context=ctx),
    )
    out = []
    page = 1
    while True:
        url = (f"https://api.github.com/repos/{repo}/releases"
               f"?per_page={per_page}&page={page}")
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ComfyNexus-ChangelogSync",
        })
        try:
            with opener.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"[warn] 第 {page} 页拉取失败: {e}")
            break
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < per_page:
            break
        page += 1
        if page > 10:      # 防御：最多 1000 条
            break
    return out


def load_snapshot() -> list:
    if not SNAPSHOT.exists():
        return []
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[warn] 本地快照读取失败（当作空）: {e}")
        return []


def merge_incremental(local: list, remote: list) -> tuple:
    """增量合并：**只增不删、只长不短**

    Returns:
        (merged, stats)  stats = {"added": [...], "extended": [...],
                                  "kept": n, "remote_only_dropped": 0}
    """
    by_key = {}
    for rel in local:
        by_key[normalize_tag(rel.get("tag_name") or "")] = dict(rel)

    added, extended = [], []
    for rel in remote:
        key = normalize_tag(rel.get("tag_name") or "")
        if not key:
            continue
        slim = {k: rel.get(k) for k in KEEP_FIELDS}
        slim["body"] = (slim.get("body") or "").replace("\r\n", "\n")
        if key not in by_key:
            by_key[key] = slim
            added.append(slim.get("tag_name"))
        else:
            old = by_key[key]
            old_body = (old.get("body") or "")
            new_body = slim.get("body") or ""
            # 只在远端正文**更长**时才替换（作者补写了内容）
            if len(new_body) > len(old_body):
                merged = dict(old)
                merged.update({k: v for k, v in slim.items() if v is not None})
                by_key[key] = merged
                extended.append((slim.get("tag_name"),
                                 len(old_body), len(new_body)))
            # 其余情况保留本地（防止空 body / 短 body 把完整正文冲掉）

    # 排序：按发布日期倒序；无日期的排最后
    merged_list = sorted(
        by_key.values(),
        key=lambda r: (r.get("published_at") or ""),
        reverse=True,
    )
    stats = {
        "added": added,
        "extended": extended,
        "kept": len(local),
        "total": len(merged_list),
    }
    return merged_list, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="增量同步原仓库更新日志快照")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    local = load_snapshot()
    print(f"[info] 本地快照: {len(local)} 个版本")
    if local:
        total_chars = sum(len(r.get("body") or "") for r in local)
        print(f"[info] 本地正文合计: {total_chars} 字符")

    remote = fetch_releases(args.repo)
    print(f"[info] 远端拉取: {len(remote)} 个版本")
    if not remote:
        print("[warn] 远端无数据（网络失败？）—— **不做任何修改**，保留本地快照")
        return 1

    merged, stats = merge_incremental(local, remote)
    print(f"[info] 合并结果: {stats['total']} 个版本"
          f"（新增 {len(stats['added'])} / 正文加长 {len(stats['extended'])}）")
    for t in stats["added"]:
        print(f"    + 新增 {t}")
    for t, old_len, new_len in stats["extended"]:
        print(f"    ↑ 加长 {t}: {old_len} → {new_len} 字符")

    if args.dry_run:
        print("[dry-run] 不写入文件")
        return 0

    # 备份后写入
    if SNAPSHOT.exists():
        backup = SNAPSHOT.with_suffix(".json.bak")
        backup.write_bytes(SNAPSHOT.read_bytes())
        print(f"[ok] 已备份 → {backup.name}")

    SNAPSHOT.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    total_chars = sum(len(r.get("body") or "") for r in merged)
    print(f"[ok] 已写入 {SNAPSHOT}")
    print(f"[ok] 共 {len(merged)} 个版本 / {total_chars} 字符正文")
    print(f"[ok] 同步时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
