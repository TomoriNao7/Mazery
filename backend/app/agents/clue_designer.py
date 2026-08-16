#Clue Designer Agent（Phase 4：线索链设计）
"""Phase 4 ClueDesigner：线索链、推理链冗余、红鲱鱼、分布图（TRD 8.2/8.3）。"""

import re
from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent

# 死亡留言 / 录音 / 供认：若关键线索描述中真凶名字出现在直接引语里，视为"一锤定音"式作弊
_QUOTED_RE = re.compile(r"[「“\"]([^」”\"]{2,20})[」”\"]")


class ClueDesignerAgent(BaseAgent):
    name = "clue_designer"
    output_key = "clues"
    skill_names = ["clue_curator"]
    max_tokens = 7000

    def validate(self, data: Any, state: Any = None) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []

        total = fields.get("total_count") or 0
        if not isinstance(total, int) or total <= 0:
            errors.append("total_count 必须为正整数")

        key_clues = fields.get("key_clues") or []
        misleading_clues = fields.get("misleading_clues") or []
        neutral_clues = fields.get("neutral_clues") or []
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

        # ---------- 跨字段校验（依赖前序 case_core / characters） ----------
        case_core = (state or {}).get("case_core") or {}
        murderer_id = case_core.get("murderer_id")
        chars = ((state or {}).get("characters") or {}).get("characters") or []
        name_of = {c.get("id"): c.get("name") for c in chars if isinstance(c, dict)}
        murderer_name = name_of.get(murderer_id)
        non_murderers = [
            c.get("id") for c in chars
            if isinstance(c, dict) and c.get("id") and c.get("id") != murderer_id
        ]

        # 1) 关键线索必须指向真凶；描述不得借死亡留言/录音直接点名真凶
        if murderer_id:
            for i, clue in enumerate(key_clues):
                if not isinstance(clue, dict):
                    continue
                pt = clue.get("points_to")
                if pt != murderer_id:
                    errors.append(
                        f"key_clues[{i}]（{clue.get('id')}）points_to={pt}，"
                        f"关键线索必须指向真凶 {murderer_id}"
                    )
                if murderer_name and clue.get("description"):
                    desc = str(clue.get("description"))
                    if murderer_name in desc:
                        for quote in _QUOTED_RE.findall(desc):
                            if murderer_name in quote:
                                errors.append(
                                    f"key_clues[{i}]（{clue.get('id')}）通过死亡留言/录音直接点名真凶"
                                    f"「{quote}」——一锤定音，应改为需多步推理才能指向的线索"
                                )

        # 2) 每个非凶手角色至少被 1 条误导线索指向（确保每个人都有嫌疑）
        pointed = set()
        for clue in misleading_clues:
            if isinstance(clue, dict) and clue.get("points_to"):
                pointed.add(clue.get("points_to"))
        for cid in non_murderers:
            if cid not in pointed:
                errors.append(f"角色 {cid} 没有任何误导线索指向（红鲱鱼须覆盖每个非凶手）")

        # 3) 难度分级完整：关键线索需覆盖 easy/medium/hard
        difficulties = {c.get("difficulty") for c in key_clues if isinstance(c, dict)}
        for d in ("easy", "medium", "hard"):
            if d not in difficulties:
                errors.append(f"关键线索缺少难度分级 {d}（应 Easy 建立嫌疑 → Medium 缩小范围 → Hard 锁定）")

        # 4) 比例软约束（从宽，避免误伤）：关键 25-45% / 误导 35-55% / 中性 5-25%
        n_key, n_mis, n_neu = len(key_clues), len(misleading_clues), len(neutral_clues)
        n_total = n_key + n_mis + n_neu
        if n_total > 0:
            key_ratio = n_key / n_total
            mis_ratio = n_mis / n_total
            neu_ratio = n_neu / n_total
            if not (0.25 <= key_ratio <= 0.45):
                errors.append(
                    f"关键线索占比 {key_ratio:.0%} 超出范围（建议 30-40%，误导略多于关键 4:6）"
                )
            if not (0.35 <= mis_ratio <= 0.55):
                errors.append(f"误导线索占比 {mis_ratio:.0%} 超出范围（建议 40-50%）")
            if neu_ratio > 0.25:
                errors.append(f"中性线索占比 {neu_ratio:.0%} 过多（建议 10-20%）")

        if not fields.get("clue_distribution_map"):
            errors.append("缺少 clue_distribution_map（场景×幕数分布表）")
        return errors
