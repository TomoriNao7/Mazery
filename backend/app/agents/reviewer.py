#Reviewer Agent（Phase 5b：逻辑审查）
"""Phase 5b Reviewer：逻辑审查——PASS / FAIL / PASS_WITH_WEAKNESSES（TRD 8.2/8.3）。

注意：verdict=FAIL 是合法输出，不是校验失败。validate 只检查审查报告本身
是否结构完整；是否回溯由 Pipeline 根据 verdict 路由。
"""

from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent

VALID_VERDICTS = {"PASS", "FAIL", "PASS_WITH_WEAKNESSES"}


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    output_key = "review"
    skill_names = ["skeptical_reviewer"]
    max_tokens = 5000

    def validate(self, data: Any) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []
        verdict = fields.get("verdict")
        if verdict not in VALID_VERDICTS:
            errors.append(f"verdict 非法: {verdict}（应为 PASS / FAIL / PASS_WITH_WEAKNESSES）")
        for k in ("critical_issues", "weaknesses", "fix_suggestions"):
            if not isinstance(fields.get(k), list):
                errors.append(f"{k} 必须是列表")
        return errors
