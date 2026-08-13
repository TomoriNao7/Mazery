---
name: murder-mystery-script-design
description: 剧本杀（murder mystery）剧本创作的专业知识与约束规范。供 Mazery 项目的创作 Agent（architect、character_designer、clue_designer、world_builder、director、reviewer）在生成或评审剧本时使用。涉及剧本结构、公平性、线索、角色、分幕、NPC 扮演或特定风格（古风/日式/校园/欧式/民国谍战/科幻）创作时加载。
---

# 剧本杀创作技能（Mazery）

本目录是 Mazery 剧本杀创作 Agent 的知识入口。约束文件位于 core/ 与 playstyle/ 下，按需加载，不要一次性全部读入。

## 使用方式

1. 先判断任务环节，只加载路由表中对应的文件。
2. core/ 中标为 CRITICAL 的文件（01、04）是硬底线，任何剧本生成或评审都必须先遵守。
3. 风格创作任务：先读对应 playstyle 文件，再结合 core 约束。
4. 每个文件自带 frontmatter（type / priority / tags），加载器可据此过滤和排序。

## 路由表

| 任务 | 加载文件 | 优先级 |
| --- | --- | --- |
| 整体设计法则 / 公平性底线 | core/01_剧本杀核心设计法则.md | CRITICAL |
| 线索设计 | core/02_线索设计原则.md | HIGH |
| 角色设计 | core/03_角色设计方法论.md | HIGH |
| 五幕结构 / 分幕流程 | core/04_五幕结构标准模板.md | CRITICAL |
| GM 主持 / 控场 | core/05_主持人(DM)技巧.md | HIGH |
| NPC 扮演 | core/06_AI扮演NPC技巧.md | HIGH |
| 古风悬疑 | playstyle/ps_古风悬疑.md | HIGH |
| 日式推理 | playstyle/ps_日式推理.md | HIGH |
| 校园 | playstyle/ps_校园.md | HIGH |
| 欧式推理 | playstyle/ps_欧式推理.md | HIGH |
| 民国谍战 | playstyle/ps_民国谍战.md | HIGH |
| 科幻 | playstyle/ps_科幻.md | HIGH |

## 硬约束

- 01 与 04 标为 CRITICAL，违反即失败；生成和评审都必须先过这两条底线。
- playstyle 文件是风格专属约束，与 core 冲突时以 core 的 CRITICAL 为准。
