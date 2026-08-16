#Architect Agent（Phase 2：案件核心）
"""Phase 2 Architect：案件核心设计——真凶/手法/动机/时间线/诡计（TRD 8.2/8.3）。"""

from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent

# 偷懒动机黑名单（TRD 8.3：动机不走偏锋）
LAZY_MOTIVE_KEYWORDS = ("精神病", "梦游", "一时冲动", "就是想杀", "他是个疯子")


class ArchitectAgent(BaseAgent):
    name = "architect"
    output_key = "case_core"
    skill_names = ["mystery_writer"]
    max_tokens = 5000

    def validate(self, data: Any, state: Any = None) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []

        if not fields.get("murderer_id"):
            errors.append("缺少 murderer_id（凶手必须唯一指定）")
        if not fields.get("murder_method"):
            errors.append("缺少 murder_method（作案手法必须明确）")
        elif len(fields["murder_method"]) > 200:
            errors.append("murder_method 超过 200 字，手法过于复杂")

        motive = fields.get("murder_motive") or ""
        if not motive:
            errors.append("缺少 murder_motive")
        elif any(k in motive for k in LAZY_MOTIVE_KEYWORDS):
            errors.append(f"动机过于敷衍（命中黑名单词: {motive}）")

        timeline = fields.get("timeline") or []
        if not timeline:
            errors.append("时间线为空")
        else:
            for i, evt in enumerate(timeline):
                # 内层为无类型 dict：见证人/物证字段名模型间不固定，仅要求非空
                if not isinstance(evt, dict) or not evt:
                    errors.append(f"timeline[{i}] 为空或不是对象")

        if not fields.get("key_clue_chain"):
            errors.append("缺少 key_clue_chain（推理链必须存在）")
        return errors
