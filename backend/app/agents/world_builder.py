#WorldBuilder Agent（Phase 1：世界观构建）
"""Phase 1 WorldBuilder：构建时代背景、场景氛围、物理规则（TRD 8.2/8.3）。"""

from typing import Any, List

from pydantic import BaseModel

from backend.app.agents.base import BaseAgent


class WorldBuilderAgent(BaseAgent):
    name = "world_builder"
    output_key = "world_setting"
    skill_names = ["world_builder"]

    def validate(self, data: Any) -> List[str]:
        fields = data.model_dump() if isinstance(data, BaseModel) else (data or {})
        errors: List[str] = []

        if not fields.get("era_tier"):
            errors.append("缺少 era_tier（时代档位必须明确）")
        if not fields.get("world_rules"):
            errors.append("缺少 world_rules（世界基础规则必须交代）")
        if not fields.get("physical_rules"):
            errors.append("缺少 physical_rules（物理规则必须交代）")

        scenes = fields.get("scenes") or []
        if not scenes:
            errors.append("场景列表为空（至少 1 个场景）")
        else:
            for i, scene in enumerate(scenes):
                if not isinstance(scene, dict) or not any(
                    k in scene for k in ("name", "场景名", "scene")
                ):
                    errors.append(f"scenes[{i}] 缺少场景名")
        return errors
