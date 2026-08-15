#Character Designer Agent（Phase 3：角色生成）
"""Phase 3 CharacterDesigner：NPC 角色卡（L1-L5）、关系网、声音指纹（TRD 8.2/8.3）。"""

from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent


class CharacterDesignerAgent(BaseAgent):
    name = "character_designer"
    output_key = "characters"
    skill_names = ["character_designer"]
    max_tokens = 10000

    def validate(self, data: Any) -> List[str]:
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

        if not fields.get("relationship_map"):
            errors.append("缺少 relationship_map（角色关系网图）")
        return errors
