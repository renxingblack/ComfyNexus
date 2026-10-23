"""推荐关注创作者的持久化（自定义添加）

内置推荐列表在前端硬编码；用户手动添加的创作者存到本地 JSON，
前端合并展示。字段对齐前端 Creator 类型。
"""

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from backend.src.utils.logger import app_logger as logger

_lock = threading.Lock()
_custom: Optional[Dict[str, Dict]] = None


def _file() -> Path:
    try:
        from backend.src.utils.paths import get_app_data_dir
        base = Path(get_app_data_dir())
    except Exception:
        base = Path.home() / ".comfynexus"
    d = base / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d / "custom_creators.json"


def _load() -> Dict[str, Dict]:
    global _custom
    with _lock:
        if _custom is None:
            try:
                _custom = json.loads(_file().read_text(encoding="utf-8"))
            except Exception:
                _custom = {}
        return _custom


def _save(data: Dict[str, Dict]):
    global _custom
    with _lock:
        _custom = data
        try:
            _file().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[CreatorStore] 保存失败: {e}")


def add_creator(name: str, link: str, description: str = "",
                platform: str = "bilibili", avatar: str = "") -> Dict:
    """添加自定义创作者，返回 {success, id, error}"""
    name = (name or "").strip()
    link = (link or "").strip()
    if not name or not link:
        return {"success": False, "error": "名称和链接不能为空"}
    data = _load()
    # 链接去重
    for cid, c in data.items():
        if c.get("link") == link:
            return {"success": False, "error": "该创作者已存在"}
    new_id = str(max((int(i) for i in data.keys() if i.isdigit()), default=10000) + 1)
    data[new_id] = {
        "id": int(new_id),
        "name": name,
        "avatar": avatar,
        "description": description or "",
        "link": link,
        "platform": platform or "bilibili",
        "custom": True,
    }
    _save(data)
    return {"success": True, "id": int(new_id),
            "avatar": avatar or "", "description": description or ""}


def remove_creator(creator_id) -> Dict:
    data = _load()
    removed = data.pop(str(creator_id), None)
    _save(data)
    # 同步删除该创作者已缓存的头像/logo（本地存储与列表保持一致）
    if removed:
        try:
            from backend.src.utils import icon_cache
            for key in ("avatar", "icon"):
                u = (removed.get(key) or "").strip()
                if u:
                    icon_cache.remove_cached_icon(u)
        except Exception as e:
            logger.debug(f"[CreatorStore] 清理头像缓存失败: {e}")
    return {"success": True}


def list_custom() -> List[Dict]:
    return list(_load().values())
