#Clue Designer Agent（Phase 4：线索链设计）
"""Phase 4 ClueDesigner：线索链、推理链冗余、红鲱鱼、分布图（TRD 8.2/8.3）。"""

from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent


class ClueDesignerAgent(BaseAgent):
    name = "clue_designer"
    output_key = "clues"
    skill_names = ["clue_curator"]
    max_tokens = 7000

    def validate(self, data: Any) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []

        total = fields.get("total_count") or 0
        if not isinstance(total, int) or total <= 0:
            errors.append("total_count 必须为正整数")

        key_clues = fields.get("key_clues") or []
        if not key_clues:
            errors.append("缺少 key_clues（必须有指向真凶的关键线索）")
        else:
            for i, clue in enumerate(key_clues):
                if not isinstance(clue, dict):
                    errors.append(f"key_clues[{i}] 不是对象")
                    continue
                for k in ("id", "name", "description", "difficulty", "location"):
                    if not clue.get(k):
                        errors.append(f"key_clues[{i}] 缺少 {k}")
                if clue.get("difficulty") not in ("easy", "medium", "hard"):
                    errors.append(f"key_clues[{i}] difficulty 非法: {clue.get('difficulty')}")

        if not fields.get("clue_distribution_map"):
            errors.append("缺少 clue_distribution_map（场景×幕数分布表）")
        return errors
