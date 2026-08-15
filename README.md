# Mazery · 迷城

AI 驱动的推理剧本杀桌面应用（FastAPI 后端 + Vue 3 前端）。从剧本库选择或创建剧本，扮演其中一名角色，由 AI 担任主持人（GM）与其余全部角色，在五幕流程中搜证、交换信息、私聊、投票指认凶手，最终由 GM 复盘真相。单人即可体验完整剧本杀。

## 功能

- 剧本库：本地剧本库 / 历史游玩剧本库（书架式，7 天自动清除）/ 创建剧本
- 创建剧本：填写类型、背景、人数等设定，AI 生成完整剧本（角色 / 线索 / 真相 / 分幕）
- 人物选择：浏览全部角色公开信息，选择其一扮演
- 五幕游戏：介绍 → 抽卡搜证 → 交换信息 + 私聊 → 抽卡搜证 → 交换 + 公聊 + 全角色投票 → GM 复盘
- LLM 配置：支持本地 Ollama 或云端 OpenAI 兼容 API

## 技术栈

- **后端**：FastAPI + SQLAlchemy(SQLite) + LangGraph + FAISS/RAG + Ollama/OpenAI 兼容 API
- **前端**：Vue 3 + TypeScript + Vite（可选 Electron 壳）

## 快速开始

### 1. 后端

需要 Python 3.11+。

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

启动（在项目根目录）：

```bash
# 从项目根目录运行，保证 backend 包可导入
python -m uvicorn backend.main:app --host 127.0.0.1 --port 18920
```

首次启动会自动：创建 SQLite 数据库（默认 `%APPDATA%/Mazery/mazery.db`）、下载 RAG 嵌入/重排模型（约 400MB，一次性）。若下载失败会自动降级为仅关键词检索，不影响使用。

### 2. 前端

需要 Node.js 18+。

```bash
cd frontend
npm install
npm run build     # 构建（默认不打包 Electron）
npm run dev       # 开发模式（Electron 窗口）
```

前端默认连接 `http://localhost:18920`，可通过 `frontend/.env` 的 `VITE_API_BASE` 修改。

### 3. 配置 LLM

两种方式：

- **设置页**：打开应用 → 设置 → 选择预设或填写 Base URL / 模型 / API Key → 保存（重启后端后仍生效）
- **环境变量**（启动后端时）：

```bash
LLM_MODEL=qwen3.7-plus \
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
LLM_API_KEY=你的key \
python -m uvicorn backend.main:app --port 18920
```

- 本地 Ollama：`LLM_BASE_URL=http://localhost:11434/v1`，模型如 `qwen3.5:4b`，无需 API Key。

> 你的 API Key 只保存在你本机的数据库（加密）或环境变量里，不会写入仓库。

## 目录结构

```
backend/
  app/
    api/        # 路由：script / game / library / settings / knowledge
    agents/     # 剧本生成 Pipeline（6 个 Agent + LangGraph 编排）
    core/       # 状态机、NPC 模拟器、RAG、Skill 引擎、LLM 客户端
    db/         # SQLAlchemy 模型 + 仓储（10+ 张表，自动建表/迁移）
  requirements.txt
frontend/
  src/
    views/      # 页面（主界面/剧本库/创建/选角/游戏/设置）
    components/ # 组件（书架/模态/抽卡/私聊/投票/复盘…）
    api/        # Axios 客户端 + SSE
    stores/     # Pinia（game / script / settings）
```

## 说明

- 历史游玩剧本库记录保留 7 天，自动清理；可手动加回本地剧本库。
- 私聊上限：每对 8 轮 × 双方各 2 次 = 32 条，达上限强制结束。
- 剧本生成信息分层：真凶 / 手法 / 动机等 L3 信息永不对玩家展示。
