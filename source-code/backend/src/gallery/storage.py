"""
资产库存储服务
负责 assets.json 的读写操作
"""

import json
import uuid
import shutil
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from backend.src.utils.paths import get_data_dir
from backend.src.utils.logger import app_logger as logger
from .models import GalleryData, GallerySettings, AssetCategory, Asset


class GalleryStorage:
    """资产库存储服务"""

    # 批量操作时的延迟落盘窗口（秒）。扫描上千张图时，
    # 原本每 add_asset 一次就全量重写 assets.json，整体是 O(n²)。
    # 标脏 + 窗口内合并落盘，把 n 次全量写压成 1 次。
    BATCH_SAVE_DEBOUNCE = 1.0

    def __init__(self):
        self._data_dir = get_data_dir() / "gallery"
        self._assets_file = self._data_dir / "assets.json"
        self._thumbnails_dir = self._data_dir / "thumbnails"
        self._data: Optional[GalleryData] = None
        self._lock = threading.Lock()
        # id -> Asset 索引，避免 get_asset_by_id / update_asset 等线性查找
        self._asset_index: dict[str, Asset] = {}
        # 延迟落盘状态
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._index_dirty = False

    def _ensure_dirs(self):
        """确保目录存在"""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    def _rebuild_index(self) -> None:
        """重建 id -> Asset 索引（资产集合变动后调用）"""
        data = self._data
        if data is None:
            self._asset_index = {}
            return
        self._asset_index = {a.id: a for a in data.assets}
        self._index_dirty = False

    def load(self) -> GalleryData:
        """加载资产库数据"""
        if self._data is not None:
            return self._data

        with self._lock:
            # 双重检查：拿到锁后再检查一次，避免重复加载
            if self._data is not None:
                return self._data

            self._ensure_dirs()

            if self._assets_file.exists():
                try:
                    with open(self._assets_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._data = GalleryData.from_dict(data)
                    self._rebuild_index()
                    logger.info(f"[GalleryStorage] 加载资产库数据: {len(self._data.assets)} 个资产, {len(self._data.categories)} 个分类")
                except Exception as e:
                    logger.error(f"[GalleryStorage] 加载资产库数据失败: {e}")
                    self._data = self._create_default_data()
                    self._asset_index = {}
            else:
                logger.info("[GalleryStorage] 资产库数据文件不存在，创建默认数据")
                self._data = self._create_default_data()
                self._asset_index = {}
                self.save(immediate=True)

            return self._data

    def save(self, immediate: bool = False) -> bool:
        """
        保存资产库数据

        Args:
            immediate: True 立即落盘（用于单次操作、退出前等必须保证持久化的场景）；
                       False 标脏并在 BATCH_SAVE_DEBOUNCE 秒后合并落盘。

        批量场景（扫描入库、NSFW 批量分级）用 False：原本每加一张图就全量
        json.dump 一遍，n 张图就是 n 次全量序列化，整体 O(n²)，几千张图会卡到分钟级。
        """
        if self._data is None:
            return False

        if not immediate:
            self._schedule_save()
            return True

        # 取消待执行的延迟落盘，避免写两次
        self._cancel_scheduled_save()
        self._write_to_disk()
        return True

    def _write_to_disk(self) -> bool:
        """真正执行 JSON 全量写盘"""
        self._ensure_dirs()
        try:
            # 先写临时文件再原子替换：避免写到一半崩溃导致 assets.json 损坏
            tmp_file = self._assets_file.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._data.to_dict(), f, ensure_ascii=False, indent=2)
            tmp_file.replace(self._assets_file)
            self._dirty = False
            logger.info(f"[GalleryStorage] 保存资产库数据成功 ({len(self._data.assets)} 个资产)")
            return True
        except Exception as e:
            logger.error(f"[GalleryStorage] 保存资产库数据失败: {e}")
            return False

    def _schedule_save(self) -> None:
        """标脏并安排一次延迟落盘（同一窗口内的多次调用会合并为一次写盘）"""
        self._dirty = True
        if self._save_timer is not None:
            # 已有待执行的落盘，交给它即可（滑动窗口）
            return

        def _delayed():
            self._save_timer = None
            if self._dirty:
                self._write_to_disk()

        self._save_timer = threading.Timer(self.BATCH_SAVE_DEBOUNCE, _delayed)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _cancel_scheduled_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None

    def flush(self) -> bool:
        """强制落盘所有待写入变更（应用退出 / 扫描结束前调用）"""
        if self._data is None:
            return False
        if not self._dirty:
            return True
        self._cancel_scheduled_save()
        return self._write_to_disk()

    def mark_index_dirty(self) -> None:
        """标记 id 索引需要重建（资产增删后调用）"""
        self._index_dirty = True

    def _get_indexed(self, asset_id: str) -> Optional[Asset]:
        """O(1) 按 id 取资产；索引缺失时自动重建"""
        if self._index_dirty or not self._asset_index:
            self._rebuild_index()
        return self._asset_index.get(asset_id)

    def _create_default_data(self) -> GalleryData:
        """创建默认数据"""
        return GalleryData(
            version="1.0",
            settings=GallerySettings(library_path=""),
            categories=[
                AssetCategory(id="all", name="全部", is_system=True, sort_order=0),
                AssetCategory(id="favorites", name="收藏", is_system=True, sort_order=1),
            ],
            assets=[]
        )

    def get_settings(self) -> GallerySettings:
        """获取设置"""
        data = self.load()
        return data.settings

    def update_settings(self, library_path: Optional[str] = None, last_scan_time: Optional[str] = None) -> bool:
        """更新设置"""
        data = self.load()
        if library_path is not None:
            data.settings.library_path = library_path
        if last_scan_time is not None:
            data.settings.last_scan_time = last_scan_time
        else:
            data.settings.last_scan_time = datetime.now().isoformat()
        return self.save()

    def update_nsfw_settings(
        self,
        nsfw_auto_classify: Optional[bool] = None,
        nsfw_threshold: Optional[float] = None,
        nsfw_auto_blur: Optional[bool] = None
    ) -> bool:
        """更新 NSFW 分级设置"""
        data = self.load()
        if nsfw_auto_classify is not None:
            data.settings.nsfw_auto_classify = nsfw_auto_classify
        if nsfw_threshold is not None:
            data.settings.nsfw_threshold = nsfw_threshold
        if nsfw_auto_blur is not None:
            data.settings.nsfw_auto_blur = nsfw_auto_blur
        return self.save()

    def clear_all_data(self) -> bool:
        """清空所有资产和分类数据（保留设置和系统分类）"""
        data = self.load()
        data.assets = []
        data.categories = [c for c in data.categories if c.is_system]
        self._asset_index = {}
        return self.save(immediate=True)

    def update_asset_nsfw(
        self,
        asset_id: str,
        nsfw_score: Optional[float] = None,
        nsfw_label: Optional[str] = None,
        tags: Optional[list[str]] = None
    ) -> Optional[Asset]:
        """更新单个资产的 NSFW 分级结果"""
        self.load()
        asset = self._get_indexed(asset_id)
        if asset is None:
            return None
        if nsfw_score is not None:
            asset.nsfw_score = nsfw_score
        if nsfw_label is not None:
            asset.nsfw_label = nsfw_label
        if tags is not None:
            asset.tags = tags
        self.save()
        return asset

    def batch_update_nsfw_labels(
        self,
        updates: list[dict]
    ) -> int:
        """
        批量更新资产的 NSFW 分级结果
        
        Args:
            updates: 更新列表，每项包含 {"asset_id": str, "nsfw_score": float, "nsfw_label": str, "tags": list}
            
        Returns:
            更新成功的资产数量
        """
        data = self.load()
        asset_map = {a.id: a for a in data.assets}
        count = 0
        
        for update in updates:
            asset_id = update.get("asset_id")
            if asset_id and asset_id in asset_map:
                asset = asset_map[asset_id]
                if "nsfw_score" in update:
                    asset.nsfw_score = update["nsfw_score"]
                if "nsfw_label" in update:
                    asset.nsfw_label = update["nsfw_label"]
                if "tags" in update:
                    asset.tags = update["tags"]
                count += 1
        
        if count > 0:
            self.save()
        return count

    def get_categories(self) -> list[AssetCategory]:
        """获取分类列表"""
        data = self.load()
        return data.categories

    def add_category(self, name: str, parent_id: Optional[str] = None, folder_path: Optional[str] = None) -> AssetCategory:
        """添加分类"""
        data = self.load()
        category = AssetCategory(
            id=f"cat-{uuid.uuid4().hex[:8]}",
            name=name,
            is_system=False,
            parent_id=parent_id,
            sort_order=len([c for c in data.categories if not c.is_system]),
            folder_path=folder_path
        )
        data.categories.append(category)
        self.save()
        return category

    def update_category(self, category_id: str, name: Optional[str] = None, folder_path: Optional[str] = None) -> Optional[AssetCategory]:
        """更新分类"""
        data = self.load()
        for category in data.categories:
            if category.id == category_id:
                if name is not None:
                    category.name = name
                if folder_path is not None:
                    category.folder_path = folder_path
                self.save()
                return category
        return None

    def get_category_by_id(self, category_id: str) -> Optional[AssetCategory]:
        """根据 ID 获取分类"""
        data = self.load()
        for category in data.categories:
            if category.id == category_id:
                return category
        return None

    def get_category_by_folder_path(self, folder_path: str) -> Optional[AssetCategory]:
        """根据文件夹路径获取分类"""
        data = self.load()
        for category in data.categories:
            if category.folder_path == folder_path:
                return category
        return None

    def delete_category(self, category_id: str) -> bool:
        """删除分类"""
        data = self.load()
        for i, category in enumerate(data.categories):
            if category.id == category_id and not category.is_system:
                data.categories.pop(i)
                for asset in data.assets:
                    if asset.category_id == category_id:
                        asset.category_id = None
                self.save()
                return True
        return False

    def get_category_content_info(self, category_id: str) -> dict:
        """获取分类内容信息（资产数量、子分类ID列表）"""
        data = self.load()
        
        asset_count = sum(1 for a in data.assets if a.category_id == category_id)
        child_ids = [c.id for c in data.categories if c.parent_id == category_id]
        
        return {
            "asset_count": asset_count,
            "child_ids": child_ids,
            "child_count": len(child_ids)
        }

    def delete_category_cascade(self, category_id: str) -> dict:
        """级联删除分类（包括子分类和资产）"""
        data = self.load()
        
        ids_to_delete = [category_id]
        
        def collect_child_ids(parent_id: str):
            for cat in data.categories:
                if cat.parent_id == parent_id:
                    ids_to_delete.append(cat.id)
                    collect_child_ids(cat.id)
        
        collect_child_ids(category_id)
        
        deleted_asset_count = sum(1 for a in data.assets if a.category_id in ids_to_delete)
        
        data.assets = [a for a in data.assets if a.category_id not in ids_to_delete]
        data.categories = [c for c in data.categories if c.id not in ids_to_delete]

        self.mark_index_dirty()
        self.save(immediate=True)
        
        return {
            "success": True,
            "deleted_categories": len(ids_to_delete),
            "deleted_assets": deleted_asset_count
        }

    def get_assets(self) -> list[Asset]:
        """获取资产列表"""
        data = self.load()
        return data.assets

    def get_asset_by_id(self, asset_id: str) -> Optional[Asset]:
        """根据 ID 获取资产（O(1) 索引查找）"""
        self.load()
        return self._get_indexed(asset_id)

    def add_asset(self, asset: Asset, immediate: bool = False) -> bool:
        """
        添加资产

        Args:
            asset: 资产对象
            immediate: True 立即落盘。批量扫描入库时应传 False（默认），
                       走防抖合并，避免每加一张图就全量重写一次 JSON。
        """
        data = self.load()
        data.assets.append(asset)
        self._asset_index[asset.id] = asset
        return self.save(immediate=immediate)

    def update_asset(self, asset_id: str, **kwargs) -> Optional[Asset]:
        """更新资产（O(1) 索引查找）"""
        self.load()
        asset = self._get_indexed(asset_id)
        if asset is None:
            return None
        for key, value in kwargs.items():
            if hasattr(asset, key):
                setattr(asset, key, value)
        self.save(immediate=True)
        return asset

    def delete_asset(self, asset_id: str) -> bool:
        """删除资产（从数据中移除）"""
        data = self.load()
        removed = False
        for i, asset in enumerate(data.assets):
            if asset.id == asset_id:
                data.assets.pop(i)
                removed = True
                break
        if not removed:
            return False
        self._asset_index.pop(asset_id, None)
        self.save(immediate=True)
        return True

    def toggle_favorite(self, asset_id: str) -> Optional[bool]:
        """切换收藏状态"""
        self.load()
        asset = self._get_indexed(asset_id)
        if asset is None:
            return None
        asset.is_favorite = not asset.is_favorite
        self.save(immediate=True)
        return asset.is_favorite

    def update_asset_preview_blurred(self, asset_id: str, blurred: bool) -> Optional[Asset]:
        """更新资产的模糊预览状态"""
        self.load()
        asset = self._get_indexed(asset_id)
        if asset is None:
            return None
        asset.preview_blurred = blurred
        self.save(immediate=True)
        return asset

    def update_asset_info(
        self,
        asset_id: str,
        filename: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        rating: Optional[int] = None
    ) -> Optional[Asset]:
        """更新资产的基本信息（文件名、备注、标签、评分）"""
        self.load()
        asset = self._get_indexed(asset_id)
        if asset is None:
            return None

        if filename is not None:
            import os
            old_path = asset.file_path
            dir_path = os.path.dirname(old_path)
            ext = os.path.splitext(old_path)[1]
            new_path = os.path.join(dir_path, filename + ext)

            if os.path.exists(old_path) and not os.path.exists(new_path):
                try:
                    os.rename(old_path, new_path)
                    asset.filename = filename + ext
                    asset.file_path = new_path
                except Exception as e:
                    logger.error(f"[GalleryStorage] 重命名文件失败: {e}")
                    return None

        if description is not None:
            asset.description = description

        if tags is not None:
            asset.tags = tags

        if rating is not None:
            asset.rating = max(0, min(5, rating))

        self.save(immediate=True)
        return asset

    def batch_toggle_favorite(self, asset_ids: list[str], favorite: bool) -> int:
        """批量设置收藏状态"""
        data = self.load()
        id_set = set(asset_ids)
        count = 0
        for asset in data.assets:
            if asset.id in id_set:
                asset.is_favorite = favorite
                count += 1
        if count > 0:
            self.save()
        return count

    def batch_delete_assets(self, asset_ids: list[str]) -> int:
        """批量删除资产"""
        data = self.load()
        id_set = set(asset_ids)
        original_count = len(data.assets)
        data.assets = [a for a in data.assets if a.id not in id_set]
        deleted_count = original_count - len(data.assets)
        if deleted_count > 0:
            for aid in id_set:
                self._asset_index.pop(aid, None)
            self.save(immediate=True)
        return deleted_count

    def move_assets_to_category(self, asset_ids: list[str], category_id: Optional[str]) -> int:
        """批量移动资产到分类"""
        data = self.load()
        id_set = set(asset_ids)
        count = 0
        for asset in data.assets:
            if asset.id in id_set:
                asset.category_id = category_id
                count += 1
        if count > 0:
            self.save()
        return count

    @property
    def data_dir(self) -> Path:
        """获取数据目录"""
        return self._data_dir

    @property
    def thumbnails_dir(self) -> Path:
        """获取缩略图目录"""
        return self._thumbnails_dir


gallery_storage = GalleryStorage()
