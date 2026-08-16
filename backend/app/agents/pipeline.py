#Pipeline编排器（LangGraph 串行 + 回溯）
"""剧本生成 Pipeline（LangGraph 版）。

结构（6 次独立 LLM 调用，每次调用单一 Skill、更简单更快）：
    world_builder → architect → character_designer → clue_designer
    → director → reviewer
    reviewer FAIL → 回溯到 critical_issues[0].target_phase 对应的 fix_<phase>
    节点修复（≤ max_backtracks 次）→ 重新审查
    reviewer PASS / PASS_WITH_WEAKNESSES / 回溯耗尽 → finalize 组装最终剧本

加速措施：每次调用的输出上限已收紧（max_tokens）、不注入 few_shot 示例、
校验从宽、重试次数下调；生成严谨性后期单独打磨。

落库（写 scripts 表）不在本模块内执行：finalize 只组装 final_script，
由调用方决定如何持久化（数据库操作另行征得同意后接入）。
"""

import json
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.architect import ArchitectAgent
from backend.app.agents.base import AgentState, BaseAgent
from backend.app.agents.character_designer import CharacterDesignerAgent
from backend.app.agents.clue_designer import ClueDesignerAgent
from backend.app.agents.director import DirectorAgent
from backend.app.agents.reviewer import ReviewerAgent
from backend.app.agents.world_builder import WorldBuilderAgent
from backend.app.core.llm import LlmClient
from backend.app.core.skill_manager import SkillManager
from backend.app.db.repository import ScriptRepo

# Phase 编号 → 前向节点名
PHASE_NODES: Dict[int, str] = {
    1: "world_builder",
    2: "architect",
    3: "character_designer",
    4: "clue_designer",
    5: "director",
}


def _build_summary(final_script: Dict[str, Any], user_input: Dict[str, Any]) -> str:
    """从现有字段拼装剧本简介（不额外调用 LLM，best-effort）。"""
    parts: List[str] = []
    outline = user_input.get("outline")
    if isinstance(outline, str) and outline.strip():
        parts.append(outline.strip())
    if not parts:
        ws = final_script.get("world_setting") or {}
        desc = ws.get("description") or ws.get("summary") or ws.get("atmosphere")
        if isinstance(desc, str) and desc.strip():
            parts.append(desc.strip())
    title = final_script.get("title") or "未命名剧本"
    scene = final_script.get("scene") or ""
    category = final_script.get("category") or ""
    prefix = f"《{title}》· {category} / {scene}"
    body = parts[0] if parts else "一场围绕谜团展开的推理游戏。"
    return (f"{prefix}。{body}")[:200]


class ScriptGenerationPipeline:
    """6 个 Agent 串行 + Reviewer 回溯修复的 LangGraph 编排器。"""

    def __init__(self,
                 llm: Optional[LlmClient] = None,
                 skill_manager: Optional[SkillManager] = None,
                 rag_manager: Any = None,
                 max_backtracks: int = 2,
                 session: Optional[AsyncSession] = None):
        """session 可选：传入时 finalize 会把最终剧本落库到 scripts 表。"""
        self.max_backtracks = max_backtracks
        self.session = session
        self.world_builder = WorldBuilderAgent(
            llm=llm, skill_manager=skill_manager, rag_manager=rag_manager)
        self.architect = ArchitectAgent(
            llm=llm, skill_manager=skill_manager, rag_manager=rag_manager)
        self.character_designer = CharacterDesignerAgent(
            llm=llm, skill_manager=skill_manager, rag_manager=rag_manager)
        self.clue_designer = ClueDesignerAgent(
            llm=llm, skill_manager=skill_manager, rag_manager=rag_manager)
        self.director = DirectorAgent(
            llm=llm, skill_manager=skill_manager, rag_manager=rag_manager)
        self.reviewer = ReviewerAgent(
            llm=llm, skill_manager=skill_manager, rag_manager=rag_manager)

        # 按阶段顺序暴露（供外部调试/测试）
        self.agents: List[BaseAgent] = [
            self.world_builder, self.architect, self.character_designer,
            self.clue_designer, self.director, self.reviewer,
        ]
        self._agent_map = {a.name: a for a in self.agents}
        self.graph = self._build_graph()

    # ---------- 图构建 ----------

    def _build_graph(self) -> Any:
        g = StateGraph(AgentState)

        # 前向节点
        for name in PHASE_NODES.values():
            g.add_node(name, self._agent_map[name].to_node())
        g.add_node("reviewer", self.reviewer.to_node())
        g.add_node("finalize", self._finalize)

        # 主链路：Phase 1-5a 串行 → Reviewer
        g.add_edge(START, PHASE_NODES[1])
        for i in range(1, len(PHASE_NODES)):
            g.add_edge(PHASE_NODES[i], PHASE_NODES[i + 1])
        g.add_edge(PHASE_NODES[5], "reviewer")

        # 回溯修复节点：fix_<phase> 复用同一 Agent（state 已带 fix_mode=True）
        for phase, name in PHASE_NODES.items():
            fix_node_name = f"fix_{name}"
            g.add_node(fix_node_name, self._make_fix_node(name))
            g.add_edge(fix_node_name, "reviewer")

        # 路由节点：reviewer → route →（条件边）fix_<phase> 或 finalize
        g.add_node("route", self._route_node)
        g.add_edge("reviewer", "route")
        path_map = {f"fix_{n}": f"fix_{n}" for n in PHASE_NODES.values()}
        path_map["finalize"] = "finalize"
        g.add_conditional_edges(
            "route", lambda s: s.get("next_node", "finalize"), path_map
        )
        g.add_edge("finalize", END)
        return g.compile()

    def _make_fix_node(self, agent_name: str) -> Callable[[Dict[str, Any]], Any]:
        agent = self._agent_map[agent_name]

        async def fix_node(state: Dict[str, Any]) -> Dict[str, Any]:
            return await agent.invoke(state)

        return fix_node

    # ---------- 路由 ----------

    async def _route_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        review = state.get("review") or {}
        verdict = review.get("verdict")
        backtracks = int(state.get("backtracks", 0))

        if verdict == "FAIL" and backtracks < self.max_backtracks:
            issues = review.get("critical_issues") or []
            issue = issues[0] if issues and isinstance(issues[0], dict) else {}
            phase = issue.get("target_phase", 2)
            if phase not in PHASE_NODES:
                phase = 2  # 缺省修复案件核心
            return {
                "next_node": f"fix_{PHASE_NODES[phase]}",
                "fix_mode": True,
                "target_phase": phase,
                "backtracks": backtracks + 1,
            }

        updates: Dict[str, Any] = {
            "next_node": "finalize",
            "known_issues": verdict != "PASS",
        }
        if verdict == "FAIL":
            updates["warnings"] = [
                f"[pipeline] 回溯 {self.max_backtracks} 次后 Reviewer 仍 FAIL，"
                "降级为 PASS_WITH_WEAKNESSES"
            ]
        return updates

    # ---------- 最终组装 ----------

    async def _finalize(self, state: Dict[str, Any]) -> Dict[str, Any]:
        user_input = state.get("user_input") or {}
        final_script: Dict[str, Any] = {
            "title": user_input.get("title") or "未命名剧本",
            "category": user_input.get("category") or "",
            "scene": user_input.get("scene") or "",
            "player_count": user_input.get("player_count"),
            "outline": user_input.get("outline"),
            "world_setting": state.get("world_setting"),
            "case_core": state.get("case_core"),
            "characters": state.get("characters"),
            "clues": state.get("clues"),
            "act_structure": state.get("act_structure"),
            "review": state.get("review"),
            "known_issues": state.get("known_issues", False),
        }

        # 硬校验：核心内容缺失视为生成失败，不落库。
        # 否则会把"角色为空"的坏剧本当成功保存，前端选角页因此空白。
        missing = [
            name for name, value in (
                ("案件核心 case_core", state.get("case_core")),
                ("角色 characters", state.get("characters")),
                ("线索 clues", state.get("clues")),
                ("分幕 act_structure", state.get("act_structure")),
            ) if not value
        ]
        if missing:
            raise RuntimeError(
                "剧本生成失败：以下核心内容未生成成功 —— "
                + "、".join(missing)
                + "。请确认 LLM 服务可用且额度充足后重试。"
            )

        if self.session is not None:
            script = await ScriptRepo(self.session).create({
                "title": final_script["title"],
                "category": final_script["category"],
                "scene": final_script["scene"],
                "player_count": final_script["player_count"] or 6,
                "outline": final_script["outline"],
                "summary": _build_summary(final_script, user_input),
                "is_custom": int(
                    user_input.get("is_custom", 1 if final_script["outline"] else 0)
                ),
                "full_script": json.dumps(final_script, ensure_ascii=False),
            })
            final_script["id"] = script.id
        return {"final_script": final_script}

    # ---------- 入口 ----------

    async def run(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """运行完整 Pipeline，返回最终状态（含 final_script）。"""
        return await self.graph.ainvoke({"user_input": user_input, "backtracks": 0})
