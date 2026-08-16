#Character Designer Agent（Phase 3：角色生成）
"""Phase 3 CharacterDesigner：NPC 角色卡（L1-L5）、关系网、声音指纹（TRD 8.2/8.3）。"""

import re
from typing import Any, Dict, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent

# 命中等式：指向凶手的表述（与"知道凶手/怀疑凶手"等泄露同义）
_MURDER_KEYWORDS = ("凶手", "杀人", "谋杀", "下毒", "毒杀", "真凶",
                    "害死", "杀害", "杀人者", "杀了他")

# 反模式 AP10：知识边界只写“知道…”，不允许写“不知道…”凑数
_IGNORANCE_PREFIX = ("不知道", "不知", "不了解", "不清楚", "没听说", "不知道他", "不记得")


def _kb_entries(char: Dict[str, Any]) -> List[str]:
    kb = char.get("knowledge_boundary") or []
    return [str(x) for x in kb if str(x).strip()]


def _deep_secrets(char: Dict[str, Any]) -> List[str]:
    """取角色的深层秘密纯文本（用于检测其他角色泄露）。"""
    out: List[str] = []
    for s in char.get("secrets") or []:
        if isinstance(s, dict):
            deep = s.get("deep") or s.get("detail") or s.get("description") or ""
            if isinstance(deep, str) and len(deep.strip()) >= 8:
                out.append(deep.strip())
        elif isinstance(s, str) and len(s.strip()) >= 8:
            out.append(s.strip())
    return out


class CharacterDesignerAgent(BaseAgent):
    name = "character_designer"
    output_key = "characters"
    skill_names = ["character_designer"]
    max_tokens = 10000

    def validate(self, data: Any, state: Any = None) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []
        chars = fields.get("characters") or []

        if not chars:
            return ["角色列表为空（至少 1 个角色）"]

        seen_ids = set()
        for i, char in enumerate(chars):
            if not isinstance(char, dict):
                errors.append(f"characters[{i}] 不是对象")
                continue
            cid = char.get("id") or char.get("name")
            if not cid:
                errors.append(f"characters[{i}] 缺少 id/name")
                continue
            if cid in seen_ids:
                errors.append(f"角色 id 重复: {cid}")
            seen_ids.add(cid)

            if not char.get("secrets"):
                errors.append(f"角色[{cid}] 缺少 secrets（每人必须有秘密）")
            if not char.get("speaking_style"):
                errors.append(f"角色[{cid}] 缺少 speaking_style（声音指纹必须定义）")
            if not char.get("relationships"):
                errors.append(f"角色[{cid}] 缺少 relationships（关系网不能孤立）")

        # 跨字段校验：知识边界不得泄露真凶身份 / 其他角色秘密
        name_of = {c.get("id"): c.get("name") for c in chars if isinstance(c, dict)}
        case_core = (state or {}).get("case_core") or {}
        murderer_id = case_core.get("murderer_id")
        murderer_name = name_of.get(murderer_id)

        for i, char in enumerate(chars):
            if not isinstance(char, dict):
                continue
            cid = char.get("id")
            name = char.get("name")
            kb = _kb_entries(char)

            if murderer_name and cid != murderer_id and not char.get("is_accomplice"):
                for entry in kb:
                    if murderer_name in entry and any(k in entry for k in _MURDER_KEYWORDS):
                        errors.append(
                            f"角色[{cid}] knowledge_boundary 泄露真凶身份: "
                            f"「{entry}」（{murderer_name} 是凶手，非凶手/非帮凶不得知道）"
                        )

            # AP10：知识边界只写“知道…”，不允许写“不知道…”凑数
            for entry in kb:
                if entry.startswith(_IGNORANCE_PREFIX):
                    errors.append(
                        f"角色[{cid}] knowledge_boundary 写了「{entry}」——"
                        f"不知道的内容不应出现在列表里，应直接删掉"
                    )

            # 检测是否泄露其他角色的深层秘密（长串命中才判违规，避免误伤）
            for j, other in enumerate(chars):
                if not isinstance(other, dict) or other.get("id") == cid:
                    continue
                for secret in _deep_secrets(other):
                    if secret and secret in "；".join(kb):
                        errors.append(
                            f"角色[{cid}] knowledge_boundary 泄露了角色[{other.get('id')}] 的秘密: "
                            f"「{secret}」"
                        )

        if not fields.get("relationship_map"):
            errors.append("缺少 relationship_map（角色关系网图）")
        return errors
