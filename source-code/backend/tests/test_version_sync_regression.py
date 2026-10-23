"""
问题 1 回归测试：ComfyUI 版本列表被永久钉在旧版本

复现原 bug 的三个条件：
  1. fetch 失败/超时被静默吞掉 → 代码继续用本地陈旧 tag
  2. 「无新标签」时无条件 touch_cache_timestamp → 24h TTL 被无限续期
  3. 缓存未过期时直接返回，永不校验远端

用真实的本地 git 仓库当 ComfyUI 仓库，不 mock git。
"""
import os
import subprocess
import sys
import tempfile
import shutil
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]        # .../source-code/backend
SRC_ROOT = BACKEND.parent                              # .../source-code  (含 backend 包)
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(BACKEND))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {detail}" if detail and not cond else ""))


def git(args, cwd, env=None):
    e = os.environ.copy()
    e.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
              "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
              "GIT_TERMINAL_PROMPT": "0"})
    if env:
        e.update(env)
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, env=e, timeout=120)


def make_repo(root: Path):
    """origin(裸) + work + client 三个仓库，模拟 ComfyUI 发布新 tag"""
    root.mkdir(parents=True, exist_ok=True)
    origin = root / "origin.git"
    work = root / "work"
    client = root / "client"

    git(["init", "-q", "--bare", str(origin)], root)
    work.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "master"], work)
    git(["remote", "add", "origin", str(origin)], work)
    git(["commit", "-q", "--allow-empty", "-m", "init"], work)
    git(["push", "-q", "origin", "master"], work)
    git(["tag", "v0.38.0"], work)
    git(["push", "-q", "origin", "v0.38.0"], work)

    git(["clone", "-q", str(origin), str(client)], root)
    return origin, work, client


def publish_new_tag(work: Path, origin: Path, tag: str):
    git(["checkout", "-q", "-b", f"rel-{tag}"], work)
    for i in range(3):
        git(["commit", "-q", "--allow-empty", "-m", f"{tag}-{i}"], work)
    git(["tag", tag], work)
    git(["push", "-q", "origin", f"rel-{tag}"], work)
    git(["push", "-q", "origin", tag], work)
    git(["checkout", "-q", "master"], work)


def max_version(result):
    from backend.src.core.version_cache import _parse_version
    tags = [v.get("version") or v.get("tag") or v.get("name", "") for v in result["versions"]]
    tags = [t for t in tags if t]
    return max(tags, key=_parse_version) if tags else None


def test_new_tag_detected(root: Path):
    """测试 1：远端发了新 tag 后，缓存过期时应能发现"""
    print("\n[测试1] 远端发布新 tag 后能被检测到")
    origin, work, client = make_repo(root / "t1")

    from backend.src.core.git_manager import GitManager
    from backend.src.core import version_cache as vc

    gm = GitManager(repo_path=str(client))
    cache = vc.VersionCache(cache_dir=root / "cache1")

    r1 = gm._get_versions_stable_incremental(cache, 1, 10, force_refresh=True)
    v1 = max_version(r1)
    check("初次能取到 v0.38.0", v1 == "v0.38.0", f"实际={v1} err={r1.get('error')}")

    publish_new_tag(work, origin, "v0.41.0")

    # 强制过期缓存，模拟 24h 后再次打开
    cp = cache._get_cache_path(str(client), "stable")
    data = cache._read_json_file(cp)
    data["updated_at"] = (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 90000)))
    cache._write_json_file(cp, data)

    r2 = gm._get_versions_stable_incremental(cache, 1, 10, force_refresh=True)
    v2 = max_version(r2)
    check("能取到新版本 v0.41.0", v2 == "v0.41.0", f"实际={v2} err={r2.get('error')}")


def test_failed_fetch_does_not_renew_ttl(root: Path):
    """测试 2（核心）：fetch 失败绝不能续期 TTL"""
    print("\n[测试2] fetch 失败不续期 TTL（原 bug 的核心）")
    origin, work, client = make_repo(root / "t2")
    # 把 remote 指向不存在的路径，让 fetch 必然失败
    # （不用 shutil.rmtree 删裸仓库：Windows 上 git 对象的只读属性会导致删不掉）
    broken = root / "t2" / "no_such_origin.git"
    git(["remote", "set-url", "origin", str(broken)], client)

    from backend.src.core.git_manager import GitManager
    from backend.src.core import version_cache as vc

    gm = GitManager(repo_path=str(client))
    cache = vc.VersionCache(cache_dir=root / "cache2")

    # 先造一份"陈旧但新鲜时间戳"的缓存，模拟用户看到的 0.38.0
    cache.set_tag_details(str(client), {"v0.38.0": {"version": "v0.38.0"}}, ["v0.38.0"])
    cp = cache._get_cache_path(str(client), "stable")
    d0 = cache._read_json_file(cp)
    age_before = cache.get_cache_age(str(client), "stable")
    check("初始缓存年龄很小", age_before < 10, f"age={age_before}")

    # 跑一次「非 force」路径：缓存未过期 → 旧代码会直接返回并永不 fetch
    # 我们模拟后台更新任务：fetch 失败
    fetch_result = gm._fetch_with_tags()
    check("fetch 确实失败", not fetch_result["success"], "remote 指向不存在路径却成功了")

    failure = gm._fetch_failure_result(fetch_result)
    check("失败被识别为 fetch_failed 而非静默放行",
          failure is not None and failure.get("error_type") == "fetch_failed",
          f"实际={failure}")

    # 后台任务失败后的行为
    cache.mark_stale(str(client), "stable")
    d1 = cache._read_json_file(cp)
    check("updated_at 未被刷新（TTL 保持原值）",
          d1["updated_at"] == d0["updated_at"],
          f"before={d0['updated_at']} after={d1['updated_at']}")
    check("缓存被标记为 stale", d1.get("stale") is True)
    check("is_stale 返回 True", cache.is_stale(str(client), "stable") is True)

    # 陈旧缓存必须重新触发后台更新，不能当成新鲜的直接返回
    r = gm._get_versions_stable_incremental(cache, 1, 10, force_refresh=False)
    check("stale 缓存会触发更新（needBackgroundUpdate=True）",
          r.get("needBackgroundUpdate") is True,
          f"实际={r.get('needBackgroundUpdate')} fromCache={r.get('fromCache')}")
    check("响应中标记 isStale", r.get("isStale") is True, f"实际={r.get('isStale')}")

    # 再次读取时 age 依然很小，但 stale 让它不会被误认为新鲜
    age_after = cache.get_cache_age(str(client), "stable")
    check("TTL 未被无限续期（age 未跳变）", age_after < age_before + 10,
          f"before={age_before} after={age_after}")


def test_set_tag_details_empty_no_renew(root: Path):
    """测试 3：空 tag_details 不续期（防自愈循环复发）"""
    print("\n[测试3] set_tag_details 传空字典时不续期")
    origin, work, client = make_repo(root / "t3")

    from backend.src.core import version_cache as vc
    cache = vc.VersionCache(cache_dir=root / "cache3")

    cache.set_tag_details(str(client), {"v0.38.0": {"version": "v0.38.0"}}, ["v0.38.0"])
    cp = cache._get_cache_path(str(client), "stable")
    d0 = cache._read_json_file(cp)

    time.sleep(1.1)
    cache.set_tag_details(str(client), {}, None)   # 无新标签
    d1 = cache._read_json_file(cp)
    check("空更新不刷新 updated_at", d1["updated_at"] == d0["updated_at"],
          f"before={d0['updated_at']} after={d1['updated_at']}")

    time.sleep(1.1)
    cache.set_tag_details(str(client), {"v0.41.0": {"version": "v0.41.0"}}, ["v0.41.0"])
    d2 = cache._read_json_file(cp)
    check("有真实新标签时刷新 updated_at", d2["updated_at"] != d0["updated_at"])
    check("写入后 stale 被清除", d2.get("stale") is False)


def test_touch_throttle(root: Path):
    """测试 4：touch_cache_timestamp 高频调用被节流"""
    print("\n[测试4] touch_cache_timestamp 节流")
    from backend.src.core import version_cache as vc
    cache = vc.VersionCache(cache_dir=root / "cache4")
    repo = "C:/fake-repo-for-throttle-test"
    cache.set_tag_details(repo, {"v0.1.0": {}}, ["v0.1.0"])

    cp = cache._get_cache_path(repo, "stable")
    d0 = cache._read_json_file(cp)
    for _ in range(20):
        cache.touch_cache_timestamp(repo, "stable")
    d1 = cache._read_json_file(cp)
    check("20 次高频 touch 只写盘 0 次", d1["updated_at"] == d0["updated_at"],
          f"被刷新了: {d0['updated_at']} -> {d1['updated_at']}")

    cache.touch_cache_timestamp(repo, "stable", force=True)
    d2 = cache._read_json_file(cp)
    check("force=True 时强制刷新", d2["updated_at"] != d0["updated_at"])


def test_fetch_timeout_configured():
    """测试 5：fetch 使用长超时而非 30s"""
    print("\n[测试5] fetch 超时配置")
    from backend.src.core import git_manager as gm_mod
    src = (BACKEND / "src/core/git_manager.py").read_text(encoding="utf-8")
    check("FETCH_GIT_TIMEOUT = 300", gm_mod.FETCH_GIT_TIMEOUT == 300,
          f"实际={gm_mod.FETCH_GIT_TIMEOUT}")
    check("_fetch_with_tags 显式带 --tags",
          "'--tags'" in src.split("def _fetch_with_tags")[1].split("def ")[0])
    check("已无裸 fetch 调用（全部走 _fetch_with_tags）",
          src.count("self._run_git_command(['fetch', 'origin', '--prune'])") == 0,
          f"残留 {src.count(chr(39)+'fetch'+chr(39)+', '+chr(39)+'origin'+chr(39)+', '+chr(39)+'--prune'+chr(39)+chr(41))} 处")


def main():
    root = Path(tempfile.mkdtemp(prefix="cn_version_test_"))
    try:
        test_fetch_timeout_configured()
        test_new_tag_detected(root)
        test_failed_fetch_does_not_renew_ttl(root)
        test_set_tag_details_empty_no_renew(root)
        test_touch_throttle(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)

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
