#Director Agent（Phase 5a：分幕编排）
"""Phase 5a Director：五幕结构、每幕线索分配、节奏控制（TRD 8.2/8.3）。"""

from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent
from backend.app.core.schemas import FiveActStructure


class DirectorAgent(BaseAgent):
    name = "director"
    output_key = "act_structure"
    skill_names = ["mystery_writer"]
    schema = FiveActStructure  # mystery_writer 默认映射案件核心，分幕需显式指定
    max_tokens = 5000

    def validate(self, data: Any) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []
        acts = fields.get("acts") or []

        if not acts:
            return ["缺少 acts（五幕结构必须存在）"]

        for i, act in enumerate(acts):
            if not isinstance(act, dict):
                errors.append(f"acts[{i}] 不是对象")
                continue
            if not act.get("name") and not act.get("act"):
                errors.append(f"acts[{i}] 缺少幕名")

        if not fields.get("clue_release_plan"):
            errors.append("缺少 clue_release_plan（各幕线索释放计划）")
        return errors
