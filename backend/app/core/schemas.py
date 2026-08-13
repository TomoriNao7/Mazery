#LLM 结构化输出 Schema
"""所有 Skill 的 output_format 引用的结构化输出 Schema（Pydantic v2）。

命名约定：类名使用 Skill 名首字母大写，schema 名（字符串）与 TRD 7.4 中
output_format.schema 字段保持一致，便于 SkillManager / 外部调用方按名字引用。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==================== 剧本生成 ====================

class WorldSetting(BaseModel):
    """world_builder 输出 — 世界观设定（world_setting_schema）"""

    genre: str = Field(description="剧本类型/题材")
    era_tier: str = Field(description="时代档位：写实历史/架空世界/戏说历史")
    world_rules: List[str] = Field(description="世界基础规则：交通/通讯/科技/魔法边界")
    physical_rules: List[str] = Field(description="物理规则：哪些可行、哪些禁止")
    scenes: List[Dict[str, Any]] = Field(description="场景清单：场景名/所属幕数/可搜证区域/常驻NPC")
    forbidden_elements: List[str] = Field(description="本世界禁止出现的元素（硬伤清单）")


class ScriptCaseCore(BaseModel):
    """mystery_writer 输出 — 案件核心（script_case_core_schema）"""

    murderer_id: str
    murder_method: str
    murder_motive: str
    murder_time: str
    murder_location: str
    timeline: List[Dict[str, Any]] = Field(description="时间线事件，含见证人/物证")
    key_clue_chain: List[Dict[str, Any]] = Field(description="关键推理链，每步对应线索")
    red_herrings: List[Dict[str, Any]] = Field(description="误导线索，含独立价值说明")


class CharacterCard(BaseModel):
    """角色卡（L1-L5 信息分层）"""

    id: str
    name: str
    public: Dict[str, Any] = Field(description="L1 公共层：身份/外貌/公开性格/公开背景")
    relationships: List[Dict[str, Any]] = Field(description="L2 关系层")
    secrets: List[Dict[str, Any]] = Field(description="L3 秘密层：表层+深层")
    motive: Optional[Dict[str, Any]] = Field(default=None, description="L4 动机层")
    truth: Optional[Dict[str, Any]] = Field(default=None, description="L5 核心真相层")
    speaking_style: Dict[str, Any] = Field(description="声音指纹：词汇/句式/语气/标点")
    knowledge_boundary: List[str] = Field(description="该 NPC 知道/不知道的信息边界")


class CharacterSet(BaseModel):
    """character_designer 输出 — 角色集合（character_set_schema）"""

    characters: List[CharacterCard]
    relationship_map: Dict[str, Any] = Field(description="角色关系网图")
    balance_check: Dict[str, Any] = Field(description="嫌疑度均衡检查结果")


class Clue(BaseModel):
    """单条线索"""

    id: str
    name: str
    description: str = Field(description="具体可观察的描述")
    difficulty: str = Field(description="easy / medium / hard")
    act: int = Field(description="所属幕数")
    location: str = Field(description="发现位置")
    points_to: Optional[str] = Field(default=None, description="指向的角色ID或结论")
    is_risk_point: bool = Field(default=False, description="是否为推理链关键备份节点")
    independent_value: Optional[str] = Field(default=None, description="误导线索的独立价值")


class ClueSet(BaseModel):
    """clue_curator 输出 — 线索集合（clue_set_schema）"""

    total_count: int
    key_clues: List[Clue]
    misleading_clues: List[Clue]
    neutral_clues: List[Clue]
    clue_distribution_map: Dict[str, Any] = Field(description="场景×幕数二维分布表")


class FiveActStructure(BaseModel):
    """mystery_writer（分幕部分）输出 — 五幕结构（five_act_structure_schema）"""

    acts: List[Dict[str, Any]] = Field(description="每幕：名称/目标/硬约束/场景分配")
    act_switch_triggers: List[Dict[str, Any]] = Field(description="幕间推进触发条件")
    clue_release_plan: Dict[str, Any] = Field(description="各幕线索释放计划")


# ==================== 游戏进行 ====================

class GameMasterResponse(BaseModel):
    """game_master 输出 — 主持人响应（game_master_response_schema）"""

    action_type: str = Field(description="narration / clue_reveal / npc_action / advance_act")
    content: str
    visible_npc_actions: List[Dict[str, Any]] = Field(description="玩家可见的NPC动向")
    scene_update: Dict[str, Any] = Field(description="场景状态变化")


class NpcResponse(BaseModel):
    """character_actor 输出 — NPC 响应（npc_response_schema）"""

    npc_id: str
    content: str
    micro_expression: Optional[str] = Field(default=None, description="微表情/小动作（用于播报）")
    is_lying: bool = Field(description="此句话是否为谎言（主持人视角）")
    emotion_shift: Dict[str, float] = Field(description="情绪变化量，如 {stress: 0.1}")


# ==================== 审查与揭晓 ====================

class ReviewResult(BaseModel):
    """skeptical_reviewer 输出 — 审查结果（review_result_schema）"""

    verdict: str = Field(description="PASS / FAIL / PASS_WITH_WEAKNESSES")
    critical_issues: List[Dict[str, Any]] = Field(description="硬伤：location/description/blocks_reasoning")
    weaknesses: List[Dict[str, Any]] = Field(description="弱项：location/description/impact")
    fix_suggestions: List[Dict[str, Any]] = Field(description="修复建议：target/suggestion")


class CaseReveal(BaseModel):
    """case_analyst 输出 — 真相揭晓（case_reveal_schema）"""

    verdict: str = Field(description="player_correct / player_wrong")
    truth_summary: str
    clue_chain_retrospective: List[Dict[str, Any]] = Field(
        description="回溯：clue_id/clue_name/how_it_was_found/what_it_revealed"
    )
    missed_details: List[Dict[str, Any]] = Field(description="忽略细节：detail/when_it_appeared/why_it_mattered")
    npc_outcomes: List[Dict[str, Any]] = Field(description="NPC结局：npc_id/goal/achieved")
    player_score: Dict[str, Any] = Field(description="评分：total/breakdown")
    grade: str = Field(description="S/A/B/C/F")


# ==================== 按 Step 的 Schema 映射（供 script_generator 使用） ====================

SCHEMAS: Dict[int, type[BaseModel]] = {
    1: WorldSetting,        # 世界观构建
    2: ScriptCaseCore,      # 案件核心
    3: CharacterSet,        # 角色生成
    4: ClueSet,             # 线索链
    5: FiveActStructure,    # 分幕编排
}

# Skill 名 → Schema 类（按 output_format.schema 名也可查）
SCHEMA_BY_SKILL: Dict[str, type[BaseModel]] = {
    "world_builder": WorldSetting,
    "mystery_writer": ScriptCaseCore,
    "character_designer": CharacterSet,
    "clue_curator": ClueSet,
    "game_master": GameMasterResponse,
    "character_actor": NpcResponse,
    "skeptical_reviewer": ReviewResult,
    "case_analyst": CaseReveal,
}

# schema 名 → 类（与 TRD 7.4 output_format.schema 字符串一一对应）
SCHEMA_BY_NAME: Dict[str, type[BaseModel]] = {
    "world_setting_schema": WorldSetting,
    "script_case_core_schema": ScriptCaseCore,
    "character_set_schema": CharacterSet,
    "clue_set_schema": ClueSet,
    "five_act_structure_schema": FiveActStructure,
    "game_master_response_schema": GameMasterResponse,
    "npc_response_schema": NpcResponse,
    "review_result_schema": ReviewResult,
    "case_reveal_schema": CaseReveal,
}
