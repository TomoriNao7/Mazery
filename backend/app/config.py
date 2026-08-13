import os
from pathlib import Path

# ---------- 端口 ----------
PORT = 18920

# ---------- 数据库路径 ----------
# 获取 APPDATA 环境变量（Windows），若不存在则回退到用户主目录
db_dir = Path('E:/DATABASE/mazery')
db_dir.mkdir(parents=True, exist_ok=True)          # 自动创建目录

# SQLite 连接字符串（支持相对路径和绝对路径）
DATABASE_URL = f"sqlite+aiosqlite:///{db_dir / 'mazery.db'}"

# ---------- 默认 LLM 配置 ----------
# 可从环境变量覆盖，方便不同环境下切换
LLM_CONFIG = {
    # 模型名称（请替换为你本地已下载的模型，例如 "llama3.1", "qwen2.5", "mistral" 等）
    "model": os.getenv("LLM_MODEL", "qwen3.5:4b"),
    # Ollama 不需要 API Key，可留空或填任意占位符
    "api_key": os.getenv("LLM_API_KEY", "ollama"),
    # Ollama 默认监听的 OpenAI 兼容端点（请确保 Ollama 已启动）
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "16384")),
}

# ---------- RAG 检索配置 ----------
# 从环境变量覆盖，方便换模型/换库时不用改代码
RAG_CONFIG = {
    # Embedding / Reranker 模型
    "embedding_model": os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
    "reranker_model": os.getenv("RAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
    # Reranker 最大输入长度（token）
    "reranker_max_length": int(os.getenv("RAG_RERANKER_MAX_LENGTH", "1024")),
    # RRF 融合常数
    "rrf_k": int(os.getenv("RAG_RRF_K", "60")),
    # 检索缓存过期时间（秒）
    "cache_ttl": int(os.getenv("RAG_CACHE_TTL", "3600")),
    # 邻域扩展 Token 估算：每 Token 折算字符数（中英混合，宁高勿低）
    "chars_per_token": float(os.getenv("RAG_CHARS_PER_TOKEN", "1.5")),
    # Query 改写最多额外生成的查询数
    "max_rewrite_queries": int(os.getenv("RAG_MAX_REWRITE_QUERIES", "2")),
    # Query 改写超时（秒）：LLM 不可用时快速降级，避免阻塞整次检索
    "rewrite_timeout": float(os.getenv("RAG_REWRITE_TIMEOUT", "3.0")),
    # 领域词典路径（jieba 自定义词典）
    "user_dict_path": str(Path(__file__).parent / "data" / "dicts" / "jbs_dict.txt"),
}
