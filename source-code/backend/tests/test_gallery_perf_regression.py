"""
问题 2/3 回归测试：资产库大量资产时的卡顿与内存占用

验证四件事：
  1. 缩略图：图片资产生成 WebP 缩略图，体积远小于原图
  2. 存储：批量入库不再 O(n²) 全量重写 JSON
  3. 索引：按 id 查找走 O(1) 索引，且索引与数据保持一致
  4. 分页：分页接口返回固定大小的页，不随总量膨胀

用真实的 PIL 图片 + 真实的文件 IO，不 mock 存储层。
"""
import os
import sys
import time
import json
import shutil
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND.parent
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(BACKEND))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {detail}" if detail and not cond else ""))


def make_image(path: Path, size=(1024, 1024), seed=0):
    """
    造一张真实 PNG。

    用平滑渐变而非纯随机噪声：ComfyUI 出图是连续色调，
    纯随机噪声在 WebP 下几乎压不动（压缩率会失真地接近 1:1），
    用噪声会高估缩略图的实际收益。
    """
    from PIL import Image
    import math
    img = Image.new("RGB", size)
    px = img.load()
    w, h = size
    for y in range(h):
        for x in range(0, w, 2):
            r = int(127 + 100 * math.sin((x + seed * 37) / 90.0))
            g = int(127 + 100 * math.sin((y + seed * 71) / 70.0))
            b = int(127 + 100 * math.sin((x + y + seed * 13) / 110.0))
            px[x, y] = (r, g, b)
            if x + 1 < w:
                px[x + 1, y] = (r, g, b)
    img.save(path, "PNG")


def test_thumbnail_shrinks_image(root: Path):
    """测试1：图片缩略图体积远小于原图"""
    print("\n[测试1] 图片缩略图生成")
    from PIL import Image

    lib = root / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    src = lib / "big.png"
    make_image(src, (1600, 1200), seed=1)
    orig_size = src.stat().st_size

    from backend.src.gallery.scanner import GalleryScanner
    scanner = GalleryScanner()
    scanner._thumbnails_dir = root / "thumbs"
    scanner._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    rel = scanner._generate_image_thumbnail(src)
    check("缩略图生成成功", rel is not None, "返回 None")

    if rel:
        thumb = root / "thumbs" / Path(rel).name
        check("缩略图文件存在", thumb.exists())
        if thumb.exists():
            t_size = thumb.stat().st_size
            ratio = t_size / orig_size
            check(f"缩略图体积显著更小 ({orig_size//1024}KB -> {t_size//1024}KB)",
                  ratio < 0.1, f"比例={ratio:.3f}")

            with Image.open(thumb) as im:
                w, h = im.size
            check("长边被限制到 512", max(w, h) <= 512, f"实际={w}x{h}")

    # 重复调用应复用已有文件，不重新生成
    mtime_before = (root / "thumbs" / Path(rel).name).stat().st_mtime_ns if rel else 0
    scanner._generate_image_thumbnail(src)
    mtime_after = (root / "thumbs" / Path(rel).name).stat().st_mtime_ns if rel else 0
    check("重复调用复用已有缩略图", mtime_before == mtime_after, "文件被重新生成了")


def test_asset_gets_thumbnail_path(root: Path):
    """测试2：入库时图片资产带上 thumbnail_path（前端才能走缩略图端点）"""
    print("\n[测试2] 入库时写入 thumbnail_path")
    from backend.src.gallery.models import Asset, GallerySettings
    from backend.src.gallery import storage as storage_mod

    lib = root / "lib2"
    lib.mkdir(parents=True, exist_ok=True)
    src = lib / "shot.png"
    make_image(src, (1024, 1024), seed=7)

    st = storage_mod.GalleryStorage()
    st._data_dir = root / "gdata"
    st._assets_file = root / "gdata" / "assets.json"
    st._thumbnails_dir = root / "gdata" / "thumbnails"
    st._data_dir.mkdir(parents=True, exist_ok=True)
    st._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    scanner = storage_mod.scanner if hasattr(storage_mod, "scanner") else None
    from backend.src.gallery.scanner import GalleryScanner
    sc = GalleryScanner()
    sc._thumbnails_dir = st._thumbnails_dir

    asset = sc._create_asset(src)
    check("资产创建成功", asset is not None)
    if asset:
        check("图片资产带 thumbnail_path", bool(asset.thumbnail_path),
              f"实际={asset.thumbnail_path!r}（这是前端退回加载原图的根因）")
        check("thumbnail_path 指向 webp",
              bool(asset.thumbnail_path) and asset.thumbnail_path.endswith(".webp"),
              f"实际={asset.thumbnail_path!r}")


def test_batch_save_not_quadratic(root: Path):
    """测试3：批量入库不再每次全量重写 JSON（核心卡顿点）"""
    print("\n[测试3] 批量入库落盘次数（防抖合并）")
    from backend.src.gallery.models import Asset
    from backend.src.gallery import storage as storage_mod

    st = storage_mod.GalleryStorage()
    st._data_dir = root / "gdata3"
    st._assets_file = root / "gdata3" / "assets.json"
    st._thumbnails_dir = root / "gdata3" / "thumbnails"
    st._data_dir.mkdir(parents=True, exist_ok=True)
    st._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    # 统计实际写盘次数
    writes = []
    orig_write = st._write_to_disk
    def counting_write():
        writes.append(1)
        return orig_write()
    st._write_to_disk = counting_write

    n = 300
    t0 = time.time()
    for i in range(n):
        st.add_asset(Asset(id=f"a{i}", filename=f"f{i}.png", file_path=f"/x/f{i}.png",
                           asset_type="image", width=512, height=512, size=1000,
                           created_at="2026-01-01T00:00:00"))
    add_elapsed = time.time() - t0

    check(f"{n} 次 add_asset 的写盘次数 <= 3（防抖生效）",
          len(writes) <= 3, f"实际写盘 {len(writes)} 次")
    print(f"       {n} 次入库耗时 {add_elapsed:.2f}s，写盘 {len(writes)} 次")

    # flush 后数据必须落盘
    st.flush()
    check("flush 后文件已写入", st._assets_file.exists())
    if st._assets_file.exists():
        data = json.loads(st._assets_file.read_text(encoding="utf-8"))
        check("flush 后数据完整（无丢失）",
              len(data.get("assets", [])) == n,
              f"实际 {len(data.get('assets', []))} / {n}")


def test_id_index_consistency(root: Path):
    """测试4：O(1) id 索引与数据保持一致"""
    print("\n[测试4] id 索引一致性")
    from backend.src.gallery.models import Asset
    from backend.src.gallery import storage as storage_mod

    st = storage_mod.GalleryStorage()
    st._data_dir = root / "gdata4"
    st._assets_file = root / "gdata4" / "assets.json"
    st._thumbnails_dir = root / "gdata4" / "thumbnails"
    st._data_dir.mkdir(parents=True, exist_ok=True)
    st._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    def mk(i):
        return Asset(id=f"x{i}", filename=f"n{i}.png", file_path=f"/p/n{i}.png",
                     asset_type="image", width=1, height=1, size=1,
                     created_at="2026-01-01T00:00:00")

    for i in range(20):
        st.add_asset(mk(i), immediate=True)

    check("按 id 能取到资产", st.get_asset_by_id("x7") is not None)
    check("不存在的 id 返回 None", st.get_asset_by_id("nope") is None)

    st.delete_asset("x7")
    check("删除后索引同步移除", st.get_asset_by_id("x7") is None)
    check("删除后数据也移除", len(st.get_assets()) == 19, f"实际 {len(st.get_assets())}")

    st.toggle_favorite("x1")
    check("toggle_favorite 生效", st.get_asset_by_id("x1").is_favorite is True)
    st.toggle_favorite("x1")
    check("再次 toggle 恢复", st.get_asset_by_id("x1").is_favorite is False)

    st.update_asset("x2", rating=5, description="hi")
    a = st.get_asset_by_id("x2")
    check("update_asset 生效", a.rating == 5 and a.description == "hi")

    st.batch_delete_assets(["x3", "x4", "x5"])
    check("批量删除后索引同步",
          st.get_asset_by_id("x3") is None and st.get_asset_by_id("x4") is None)
    check("批量删除数量正确", len(st.get_assets()) == 16, f"实际 {len(st.get_assets())}")


def test_index_after_reload(root: Path):
    """测试5：重新加载后索引仍然可用（弱化缓存失效路径）"""
    print("\n[测试5] 重新加载后索引可用")
    from backend.src.gallery.models import Asset
    from backend.src.gallery import storage as storage_mod

    d = root / "gdata5"
    st = storage_mod.GalleryStorage()
    st._data_dir = d
    st._assets_file = d / "assets.json"
    st._thumbnails_dir = d / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    st._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    for i in range(5):
        st.add_asset(Asset(id=f"r{i}", filename=f"r{i}.png", file_path=f"/p/r{i}.png",
                           asset_type="image", width=1, height=1, size=1,
                           created_at="2026-01-01T00:00:00"), immediate=True)

    # 模拟进程重启：全新实例从磁盘加载
    st2 = storage_mod.GalleryStorage()
    st2._data_dir = d
    st2._assets_file = d / "assets.json"
    st2._thumbnails_dir = d / "thumbnails"
    st2.load()
    check("重载后按 id 能取到", st2.get_asset_by_id("r3") is not None)
    check("重载后总数正确", len(st2.get_assets()) == 5)


def test_pagination(root: Path):
    """测试6：分页返回固定大小，不随总量膨胀"""
    print("\n[测试6] 分页接口")
    from backend.src.gallery.models import Asset
    from backend.src.gallery import storage as storage_mod
    from backend.src.gallery.controller import GalleryController

    st = storage_mod.GalleryStorage()
    d = root / "gdata6"
    st._data_dir = d
    st._assets_file = d / "assets.json"
    st._thumbnails_dir = d / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    st._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    total_n = 250
    for i in range(total_n):
        st.add_asset(Asset(id=f"p{i}", filename=f"p{i:04d}.png", file_path=f"/p/p{i}.png",
                           asset_type="image", width=512, height=512, size=1000 + i,
                           created_at=f"2026-01-{(i % 28) + 1:02d}T00:00:00",
                           is_favorite=(i % 10 == 0)), immediate=False)
    st.flush()

    # 让 controller 用我们的 storage 实例
    ctrl = GalleryController()
    ctrl._data_dir = d
    ctrl._thumbnails_dir = d / "thumbnails"
    import backend.src.gallery.controller as ctrl_mod
    orig = ctrl_mod.gallery_storage
    ctrl_mod.gallery_storage = st
    try:
        r1 = ctrl.gallery_get_assets_page(page=1, page_size=60)
        check("第 1 页返回 60 条", len(r1["assets"]) == 60, f"实际 {len(r1['assets'])}")
        check("total 正确", r1["total"] == total_n, f"实际 {r1['total']}")
        check("has_more 为 True", r1["has_more"] is True)

        r5 = ctrl.gallery_get_assets_page(page=5, page_size=60)
        check("第 5 页返回剩余 10 条", len(r5["assets"]) == 10, f"实际 {len(r5['assets'])}")
        check("末页 has_more 为 False", r5["has_more"] is False)

        rf = ctrl.gallery_get_assets_page(page=1, page_size=60, category_id="favorites")
        check("收藏过滤生效", rf["total"] == 25, f"实际 {rf['total']}")

        rs = ctrl.gallery_get_assets_page(page=1, page_size=10, search="p001")
        check("搜索过滤生效", rs["total"] > 0, f"实际 {rs['total']}")
        check("搜索结果都含关键词",
              all("p001" in a["filename"] for a in rs["assets"]),
              "混入了不匹配项")

        # 越界页
        rb = ctrl.gallery_get_assets_page(page=999, page_size=60)
        check("越界页返回空列表", len(rb["assets"]) == 0)

        # 单页 JSON 体积应远小于全量
        page_json = len(json.dumps(r1["assets"]))
        full_json = len(json.dumps([a.to_dict() for a in st.get_assets()]))
        check(f"单页体积显著小于全量 ({page_json//1024}KB vs {full_json//1024}KB)",
              page_json < full_json * 0.4,
              f"比例 {page_json/full_json:.2f}")
    finally:
        ctrl_mod.gallery_storage = orig


def test_nsfw_cache_bounded(root: Path):
    """测试7：NSFW 结果缓存有上限，不会无限增长"""
    print("\n[测试7] NSFW 缓存上限")
    from backend.src.gallery.scanner import GalleryScanner
    sc = GalleryScanner()
    check("定义了缓存上限常量", GalleryScanner.NSFW_CACHE_MAX > 0,
          f"实际={GalleryScanner.NSFW_CACHE_MAX}")
    check("实例有缓存容器", isinstance(sc._nsfw_cache, dict))
    check("初始为空", len(sc._nsfw_cache) == 0)


def test_source_has_thumbnail_for_images(root: Path):
    """测试8：静态检查：图片资产会走缩略图生成"""
    print("\n[测试8] 源码检查")
    src = (BACKEND / "src/gallery/scanner.py").read_text(encoding="utf-8")
    check("定义了 _generate_image_thumbnail", "def _generate_image_thumbnail" in src)
    check("图片分支调用了缩略图生成",
          "_generate_image_thumbnail" in src.split("thumbnail_path = None")[1][:300])

    store = (BACKEND / "src/gallery/storage.py").read_text(encoding="utf-8")
    check("存储层有 flush()", "def flush" in store)
    check("存储层有防抖配置", "BATCH_SAVE_DEBOUNCE" in store)
    check("有 id 索引", "_asset_index" in store)

    proc = (BACKEND.parent / "frontend/src/stores/useProcessStore.ts").read_text(encoding="utf-8")
    check("进程日志有上限", "MAX_LOG_LINES" in proc and ".slice(-MAX_LOG_LINES)" in proc)

    dep = (BACKEND.parent / "frontend/src/stores/useDependencyStore.ts").read_text(encoding="utf-8")
    check("依赖日志有上限", "MAX_LOG_LINES" in dep and ".slice(-MAX_LOG_LINES)" in dep)

    grid = (BACKEND.parent / "frontend/src/components/asset/AssetMasonryGrid.tsx").read_text(encoding="utf-8")
    check("瀑布流渐进渲染", "IntersectionObserver" in grid)
    check("渐进渲染有初始上限", "INITIAL_RENDER_COUNT" in grid)


def main():
    root = Path(tempfile.mkdtemp(prefix="cn_gallery_test_"))
    try:
        for fn in (test_source_has_thumbnail_for_images,
                   test_nsfw_cache_bounded,
                   test_thumbnail_shrinks_image,
                   test_asset_gets_thumbnail_path,
                   test_batch_save_not_quadratic,
                   test_id_index_consistency,
                   test_index_after_reload,
                   test_pagination):
            try:
                fn(root)
            except Exception as e:
                import traceback
                print(f"  [ERROR] {fn.__name__}: {e}")
                FAIL.append(f"{fn.__name__} 异常: {e}")
                traceback.print_exc()
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
