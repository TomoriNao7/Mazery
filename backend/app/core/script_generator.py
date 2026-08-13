#剧本生成 Pipeline 注入点（Skill 组合 + LLM 调用）
"""剧本生成阶段注入点（TRD 7.6）。

Skill 组合修正：
- Step 3 角色生成使用 character_designer（TRD 7.6 原文误写为 mystery_writer，
  与 7.2 的 Agent → Skill 映射矛盾）；
- Step 5 分幕编排使用 mystery_writer 的分幕部分（TRD 7.6 原文误写为 clue_curator，
  与 7.2 中 Director → mystery_writer 的映射矛盾）。
"""

from typing import Any, Dict, Optional

from backend.app.core.llm import get_llm_client
from backend.app.core.schemas import SCHEMAS, ReviewResult
from backend.app.core.skill_manager import get_skill_manager


async def generate_script_step(step: int, context: dict,
                               rag_manager=None) -> Any:
    """
    执行剧本生成 Pipeline 的某一步，返回对应 Schema 的结构化结果。

    Args:
        step: 1 世界观 / 2 案件核心 / 3 角色 / 4 线索 / 5 分幕
        context: 该步所需的上下文（前一步输出、用户大纲等）
        rag_manager: RAG 管理器实例，可选；传入时按 Skill rag_tags 注入知识
    """
    sm = get_skill_manager()

    if step == 1:
        skills = ["world_builder"]
    elif step == 2:
        skills = ["mystery_writer", "clue_curator"]  # 品质 + 公平性
    elif step == 3:
        skills = ["character_designer"]
    elif step == 4:
        skills = ["clue_curator"]
    elif step == 5:
        skills = ["mystery_writer"]  # 分幕编排部分
    else:
        raise ValueError(f"未知的剧本生成步骤: {step}（支持 1-5）")

    schema = SCHEMAS.get(step)
    prompt = sm.build_system_prompt(
        skills,
        rag_manager=rag_manager,
        step=step,
        **context,
    )
    return await get_llm_client().call(prompt, schema=schema)


async def review_script(script: dict):
    """Step 6: 独立审查（skeptical_reviewer）。返回 ReviewResult。"""
    sm = get_skill_manager()
    prompt = sm.build_system_prompt(
        ["skeptical_reviewer"],
        script=script,
    )
    return await get_llm_client().call(prompt, schema=ReviewResult)
