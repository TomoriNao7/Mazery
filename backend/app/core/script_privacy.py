#剧本信息权限裁剪（PRD 6.4）
"""剧本信息权限裁剪：L3 主持层（真凶/手法/动机/时间线/线索指向）永不对玩家返回。

完整剧本（含真相）只存储在 scripts.full_script，仅在服务端内部消费
（剧本生成落库、GM 主持、真相揭晓）；任何客户端可访问的 API 一律返回
public_script_view 裁剪后的 L1 公共视图。
"""

import json
from typing import Any, Dict


def public_field(public: Any, *keys: str) -> Any:
    """从角色 public 字典容错取字段（支持中英文键），返回第一个非空值。"""
    if not isinstance(public, dict):
        return None
    for k in keys:
        if public.get(k):
            return public[k]
    return None


def script_text_size(full: Any) -> int:
    """统计 full_script 字典中所有字符串字符总数（书架'文本量'）。"""
    if isinstance(full, str):
        return len(full)
    if isinstance(full, dict):
        return sum(script_text_size(v) for v in full.values())
    if isinstance(full, list):
        return sum(script_text_size(v) for v in full)
    return 0


def public_script_view(script: Any) -> Dict[str, Any]:
    """把 Script ORM 对象裁剪为玩家可见的 L1 公共视图。

    保留：剧本基础信息 + 世界观（L1）+ 角色公开层（L1）。
    剥离：case_core（真凶/手法/动机/时间线）、clues（位置与指向）、
          act_structure（含线索释放计划）、review、known_issues 等 L3。
    """
    data: Dict[str, Any] = {
        "id": script.id,
        "title": script.title,
        "category": script.category,
        "scene": script.scene,
        "player_count": script.player_count,
        "summary": getattr(script, "summary", None),
        "created_at": script.created_at,
    }

    if not script.full_script:
        return data

    try:
        full = json.loads(script.full_script)
    except (json.JSONDecodeError, TypeError):
        return data
    if not isinstance(full, dict):
        return data

    # L1：世界观（时代背景、场景氛围）
    if full.get("world_setting"):
        data["world_setting"] = full["world_setting"]

    # L1：角色公开层（身份/外貌/公开性格），不含秘密/动机/真相
    characters = full.get("characters")
    if isinstance(characters, dict) and characters.get("characters"):
        data["characters"] = [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "public": c.get("public") if isinstance(c, dict) else None,
            }
            for c in characters["characters"]
            if isinstance(c, dict)
        ]

    return data
