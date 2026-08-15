#Agent基类（LangGraph 节点：LLM调用+重试+校验）
"""Agent 基类（LangGraph 版）。

按 TRD 第八章 8.1-8.4 实现：每个 Agent 是一个 LangGraph 节点，输入共享的
AgentState，输出部分状态更新（{output_key: data, ...}）。节点内部按
TRD 8.4 执行"生成 → 校验 → 重试（≤ max_retries）→ 降级并记录 warning"。

相比 TRD 8.1 伪代码的差异：TRD 用 result 对象（.failed/.data），本项目按
LangGraph 约定改为"节点返回状态增量"，Pipeline 通过 StateGraph 编排。
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Type, TypedDict, Annotated

import operator
from pydantic import BaseModel

from backend.app.core.llm import LlmClient, get_llm_client
from backend.app.core.schemas import SCHEMA_BY_NAME, SCHEMA_BY_SKILL
from backend.app.core.skill_manager import SkillManager, get_skill_manager

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    """剧本生成 Pipeline 的共享状态（LangGraph State）。

    各阶段输出由对应 Agent 的 output_key 写入；warnings 使用 reducer
    累加，跨节点累积降级/回溯警告。
    """

    user_input: Dict[str, Any]          # 用户请求（分类/场景/大纲/自定义角色等）
    world_setting: Dict[str, Any]       # Phase 1 WorldBuilder 输出
    case_core: Dict[str, Any]           # Phase 2 Architect 输出
    characters: Dict[str, Any]          # Phase 3 CharacterDesigner 输出
    clues: Dict[str, Any]               # Phase 4 ClueDesigner 输出
    act_structure: Dict[str, Any]       # Phase 5a Director 输出
    review: Dict[str, Any]              # Phase 5b Reviewer 输出
    final_script: Dict[str, Any]        # Pipeline 最终组装结果（finalize 节点输出）
    known_issues: bool                  # 降级标记：has_known_issues
    backtracks: int                     # Reviewer 回溯修复次数（pipeline 路由用）
    fix_mode: bool                      # 是否为回溯修复模式
    target_phase: int                   # 本次回溯要修复的目标 Phase（1-5）
    next_node: str                      # Pipeline 路由节点的下一跳（内部用）
    warnings: Annotated[List[str], operator.add]  # 跨节点累加


class BaseAgent:
    """所有剧本生成 Agent 的基类。

    子类需定义：
        name        节点名（LangGraph add_node 使用）
        output_key  AgentState 中的输出键
        skill_names 注入的 Skill 名称列表
    可选覆盖：
        schema      输出 Pydantic 模型；缺省按 skill_names[0] 从 SCHEMA_BY_SKILL 解析
        validate()  输出校验，返回错误列表；空列表 = 通过
    """

    name: str = "base_agent"
    output_key: str = "output"
    skill_names: List[str] = []
    schema: Optional[Type[BaseModel]] = None
    max_retries: int = 3
    # 生成阶段的输出长度上限（结构化 JSON，无需 16k 默认值；限制可显著缩短生成时间）
    max_tokens: int = 8000

    # 原创性硬约束：禁止复用示例/资料中的具体内容
    ORIGINALITY_DIRECTIVE = (
        "\n\n【原创性要求】你必须创作全新的原创内容。"
        "严禁直接复用、改写或抄袭示例与参考资料中的任何具体角色、姓名、案件、手法、线索、场景、台词、地点。"
        "示例与资料仅用于理解格式与规则，绝不能照搬其中的人物或情节。"
        "所有角色、案件、线索、分幕、真相都必须以用户提供的设定为唯一出发点，完全原创。"
    )

    def __init__(self,
                 llm: Optional[LlmClient] = None,
                 skill_manager: Optional[SkillManager] = None,
                 rag_manager: Any = None):
        self.llm = llm or get_llm_client()
        self.skill_manager = skill_manager or get_skill_manager()
        self.rag_manager = rag_manager

    # ---------- 元信息 ----------

    @property
    def output_schema(self) -> Optional[Type[BaseModel]]:
        """输出 Schema：显式指定 > schema 名 > 按 Skill 名解析。"""
        if self.schema is not None:
            return self.schema
        if self.skill_names:
            return SCHEMA_BY_SKILL.get(self.skill_names[0])
        return None

    # ---------- Prompt 构建 ----------

    def _context_from_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从共享状态提取本 Agent 可用的上下文（排除控制字段与空值）。"""
        skip = {"warnings", "known_issues", "review"}
        return {
            k: v for k, v in state.items()
            if k not in skip and v is not None
        }

    def build_prompt(self, state: Dict[str, Any],
                     fix_mode: bool = False,
                     extra_context: Optional[Dict[str, Any]] = None) -> str:
        """构建 System Prompt（Skill 组合 + 上下文 + 可选的修复指令）。"""
        context = self._context_from_state(state)
        if extra_context:
            context.update(extra_context)
        if fix_mode:
            context["fix_mode"] = True
            context["fix_instructions"] = state.get("review", {}).get("critical_issues", [])
        prompt = self.skill_manager.build_system_prompt(
            self.skill_names,
            rag_manager=self.rag_manager,
            **context,
        )
        # 附加原创性硬约束：few_shot 与资料仅供理解格式，严禁照搬其中具体内容
        return prompt + self.ORIGINALITY_DIRECTIVE

    # ---------- 生成与校验 ----------

    async def generate(self, prompt: str) -> Any:
        """调用 LLM 并解析为输出 Schema（失败时返回原始文本）。"""
        return await self.llm.call(prompt, schema=self.output_schema,
                                   max_tokens=self.max_tokens)

    def validate(self, data: Any) -> List[str]:
        """校验输出，返回错误列表。子类可覆盖；默认视为通过。"""
        return []

    # ---------- LangGraph 节点 ----------

    async def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph 节点函数：生成 → 校验 → 重试 → 降级。"""
        warnings: List[str] = []
        prompt = self.build_prompt(state, fix_mode=bool(state.get("fix_mode")))
        data = None

        for attempt in range(1, self.max_retries + 1):
            try:
                data = await self.generate(prompt)
            except Exception as e:
                logger.warning("[%s] 第 %d 次 LLM 调用失败: %s", self.name, attempt, e)
                data = None

            errors = self.validate(data) if data is not None else [
                "LLM 调用失败或返回为空"
            ]
            if not errors:
                return {self.output_key: self._to_plain(data), "warnings": warnings}

            logger.warning("[%s] 第 %d 次校验失败: %s", self.name, attempt, errors)
            if attempt < self.max_retries:
                # TRD 8.4：重试时把错误原因追加进 prompt
                prompt = self.build_prompt(
                    state,
                    extra_context={"last_errors": errors, "retry_attempt": attempt},
                )
            else:
                # TRD 8.4：重试耗尽 → 降级通过，记录 warning
                warnings.append(
                    f"[{self.name}] 重试 {self.max_retries} 次后校验仍未通过，"
                    f"降级采用最后输出: {errors}"
                )

        return {self.output_key: self._to_plain(data), "warnings": warnings}

    @staticmethod
    def _to_plain(data: Any) -> Any:
        """把 Pydantic 模型转为 dict，保证 LangGraph 状态可 JSON 序列化。"""
        if isinstance(data, BaseModel):
            return data.model_dump()
        return data

    def to_node(self) -> Callable[[Dict[str, Any]], Any]:
        """返回可直接传给 graph.add_node 的节点函数。"""
        return self.invoke

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} output_key={self.output_key}>"
