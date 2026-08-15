#Skills加载 Prompt构建
"""SkillManager：Skills 加载、验证和 Prompt 构建引擎。

按 TRD 第七章 7.5 实现。相比 TRD 伪代码修正了以下问题：
1. RAG 返回的是 Document 对象而非字符串，参考资料拼接改用 doc.content；
2. 补充了 tone（语气风格）段——character_actor 的 tone 字段原实现未使用；
3. 用户 Skills 目录改为跨平台：Windows 用 %APPDATA%/Mazery/skills，
   其他平台回退到 ~/.config/Mazery/skills；
4. 校验器补充 few_shot / output_format 必填检查。
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class SkillManager:
    """Skills 加载、验证和 Prompt 构建引擎"""

    BUILTIN_SKILLS_DIR = Path(__file__).parent / "skills"

    # Windows: %APPDATA%/Mazery/skills；其他平台: ~/.config/Mazery/skills
    _appdata = os.environ.get("APPDATA") or str(Path.home() / ".config")
    USER_SKILLS_DIR = Path(_appdata) / "Mazery" / "skills"

    REQUIRED_FIELDS = [
        "name", "version", "role", "trigger", "rag_tags", "principles",
        "rules", "output_format", "anti_patterns", "quality_gate", "few_shot",
    ]

    def __init__(self, builtin_dir: Optional[Path] = None,
                 user_dir: Optional[Path] = None):
        self.skills: Dict[str, dict] = {}
        self.builtin_dir = Path(builtin_dir) if builtin_dir else self.BUILTIN_SKILLS_DIR
        self.user_dir = Path(user_dir) if user_dir else self.USER_SKILLS_DIR
        self._load_all()

    # ---------- 加载 ----------

    def _load_all(self):
        """加载顺序：内置 → 用户覆盖"""
        self.skills.clear()

        # 1. 加载内置 Skills
        if self.builtin_dir.exists():
            for yaml_file in sorted(self.builtin_dir.glob("*.yaml")):
                self._load_skill(yaml_file)

        # 2. 加载用户自定义 Skills（覆盖同名内置）
        if self.user_dir.exists():
            for yaml_file in sorted(self.user_dir.glob("*.yaml")):
                self._load_skill(yaml_file, override=True)

    def _load_skill(self, path: Path, override: bool = False):
        with open(path, encoding="utf-8") as f:
            skill = yaml.safe_load(f)
        if not isinstance(skill, dict):
            raise ValueError(f"Skill 文件 {path} 内容不是 YAML 映射")

        name = skill.get("name")
        if not name:
            raise ValueError(f"Skill 文件 {path} 缺少 name 字段")

        if name in self.skills and not override:
            raise ValueError(
                f"Skill '{name}' 重复定义。使用用户版本覆盖请设置 override=True"
            )

        # 版本校验
        self._validate_skill(skill)
        self.skills[name] = skill

    def _validate_skill(self, skill: dict):
        """校验 Skill 必填字段和格式"""
        missing = [f for f in self.REQUIRED_FIELDS if f not in skill]
        if missing:
            raise ValueError(
                f"Skill '{skill.get('name', 'unknown')}' 缺少必填字段: {missing}"
            )

        if not isinstance(skill["rag_tags"], list):
            raise ValueError(f"Skill '{skill['name']}' rag_tags 必须是列表")

        of = skill["output_format"]
        if "schema" not in of or "required_fields" not in of:
            raise ValueError(
                f"Skill '{skill['name']}' output_format 缺少 schema 或 required_fields"
            )

        qg = skill["quality_gate"]
        if "self_checks" not in qg or "pass_threshold" not in qg:
            raise ValueError(
                f"Skill '{skill['name']}' quality_gate 缺少 self_checks 或 pass_threshold"
            )

        fs = skill["few_shot"]
        if not isinstance(fs, dict) or "good_example" not in fs or "bad_example" not in fs:
            raise ValueError(
                f"Skill '{skill['name']}' few_shot 缺少 good_example 或 bad_example"
            )

    # ---------- 查询 ----------

    def get(self, name: str) -> Optional[dict]:
        return self.skills.get(name)

    def names(self) -> List[str]:
        return sorted(self.skills)

    # ---------- Prompt 构建 ----------

    def build_system_prompt(self,
                            skill_names: List[str],
                            rag_manager=None,
                            include_few_shot: bool = True,
                            **context) -> str:
        """
        组合多个 Skill 构建完整 System Prompt。

        Args:
            skill_names: 要组合的 Skill 名称列表，按顺序拼接
            rag_manager: RAG 管理器实例（提供 search_by_tags），用于检索相关知识
            include_few_shot: 是否注入 few_shot 示例。剧本生成时设为 False，
                              避免模型直接复用示例中的具体角色/案件（原创性）。
            **context: 当前上下文（游戏状态、NPC信息等）

        Returns:
            完整的 System Prompt 字符串
        """
        unknown = [n for n in skill_names if n not in self.skills]
        if unknown:
            raise KeyError(f"未加载的 Skill: {unknown}")

        sections = []

        # Part 1: 角色定义
        roles = [self.skills[n]["role"] for n in skill_names]
        sections.append("# 你的身份\n" + "\n\n".join(roles))

        # Part 2: 核心原则
        parts = []
        for name in skill_names:
            items = "\n".join(f"- {p}" for p in self.skills[name]["principles"])
            parts.append(f"## {name}\n{items}")
        sections.append("# 核心原则（不可违反）\n" + "\n\n".join(parts))

        # Part 3: 行为规则
        parts = []
        for name in skill_names:
            items = "\n".join(f"- {r}" for r in self.skills[name]["rules"])
            parts.append(f"## {name}\n{items}")
        sections.append("# 行为规则（必须遵守）\n" + "\n\n".join(parts))

        # Part 4: 禁止模式
        parts = []
        for name in skill_names:
            items = "\n".join(f"- {a}" for a in self.skills[name]["anti_patterns"])
            parts.append(f"## {name}\n{items}")
        sections.append("# 禁止行为（触犯即不合格）\n" + "\n\n".join(parts))

        # Part 5: 语气风格（仅 character_actor 等声明了 tone 的 Skill）
        tones = [self.skills[n]["tone"] for n in skill_names
                 if self.skills[n].get("tone")]
        if tones:
            sections.append("# 语气风格\n" + "\n\n".join(tones))

        # Part 6: 少样本示例（剧本生成时关闭，避免复用示例内容）
        if include_few_shot:
            parts = []
            for name in skill_names:
                fs = self.skills[name].get("few_shot", {})
                if fs.get("good_example"):
                    parts.append(f"## {name} — 好的做法\n{fs['good_example']}")
                if fs.get("bad_example"):
                    parts.append(f"## {name} — 坏的做法（不要这样）\n{fs['bad_example']}")
            if parts:
                sections.append("# 示例参考\n" + "\n\n".join(parts))

        # Part 7: RAG 相关知识
        if rag_manager is not None:
            all_tags = []
            for name in skill_names:
                all_tags.extend(self.skills[name].get("rag_tags", []))
            if all_tags:
                try:
                    rag_docs = rag_manager.search_by_tags(list(set(all_tags)))
                except Exception as e:  # RAG 不可用时降级，不影响 Prompt 构建
                    rag_docs = []
                    print(f"[SkillManager] RAG 检索失败，已降级跳过: {e}")
                if rag_docs:
                    texts = [
                        getattr(doc, "content", doc) if not isinstance(doc, str) else doc
                        for doc in rag_docs
                    ]
                    sections.append("# 参考资料\n" + "\n\n".join(texts))

        # Part 8: 当前上下文
        if context:
            sections.append(
                "# 当前上下文\n" +
                json.dumps(context, ensure_ascii=False, indent=2, default=str)
            )

        # Part 9: 输出格式要求
        parts = []
        for name in skill_names:
            of = self.skills[name]["output_format"]
            parts.append(
                f"## {name}\n"
                f"必须使用 Schema: {of['schema']}\n"
                f"必填字段: {', '.join(of.get('required_fields', []))}"
            )
        sections.append("# 输出格式要求\n" + "\n\n".join(parts))

        # Part 10: 质量自检
        checks = []
        for name in skill_names:
            for check in self.skills[name]["quality_gate"]["self_checks"]:
                checks.append(f"- [{name}] {check}")
        sections.append("# 完成前自检\n" + "\n".join(checks))

        return "\n\n---\n\n".join(sections)


# 全局单例
_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
