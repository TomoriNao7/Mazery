#RAG混合检索

import asyncio
import copy
import hashlib
import json
import math
import os
import time
from typing import List, Dict, Any, Optional, Tuple, Set, Callable
from pathlib import Path
from dataclasses import dataclass, field

# 模型默认走本地缓存（HF_HUB_OFFLINE=1），避免每次加载时联网检查更新；
# 若用户显式设置了环境变量则以用户为准（setdefault 不覆盖）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 第三方库
import numpy as np
import jieba
from rank_bm25 import BM25Okapi
import faiss
from sentence_transformers import SentenceTransformer, CrossEncoder
from openai import AsyncOpenAI

# 本地模块
from backend.app.config import RAG_CONFIG, LLM_CONFIG, DB_DIR
from backend.app.data.loader import KnowledgeLoader, Document


# ==================== 配置与常量 ====================

# 配置集中到 backend/app/config.py 的 RAG_CONFIG / LLM_CONFIG，支持环境变量覆盖
DEFAULT_EMBEDDING_MODEL = RAG_CONFIG["embedding_model"]
DEFAULT_RERANKER_MODEL = RAG_CONFIG["reranker_model"]
DEFAULT_LLM_BASE_URL = LLM_CONFIG["base_url"]
DEFAULT_LLM_MODEL = LLM_CONFIG["model"]

# RRF 融合常数
RRF_K = RAG_CONFIG["rrf_k"]

# 缓存过期时间（秒）
CACHE_TTL = RAG_CONFIG["cache_ttl"]

# 邻域扩展 Token 估算：每 Token 折算字符数（中英混合，宁高勿低）
CHARS_PER_TOKEN = RAG_CONFIG["chars_per_token"]

# Reranker 最大输入长度（token）：块长 600 字≈400 token，1024 给 query 留足余量
RERANKER_MAX_LENGTH = RAG_CONFIG["reranker_max_length"]

# Query 改写最多额外生成的查询数（总查询数 = 1 原查询 + 该值，控制召回成本）
MAX_REWRITE_QUERIES = RAG_CONFIG["max_rewrite_queries"]

# Query 改写超时（秒）：LLM 不可用时快速降级，避免阻塞整次检索
REWRITE_TIMEOUT = RAG_CONFIG["rewrite_timeout"]

# 领域词典路径（jieba 自定义词典，提升剧本杀术语分词质量）
USER_DICT_PATH = Path(RAG_CONFIG["user_dict_path"])

# 子集索引缓存上限（超出后整体清空重建；缓存很小、重建成本低）
SUBSET_CACHE_MAX = 16

# FAISS 索引落盘缓存：避免每次启动重复嵌入知识库
INDEX_CACHE_DIR = DB_DIR / "rag_index"
INDEX_CACHE_FILES = ("faiss.index", "embeddings.npy", "meta.json")

# 中文停用词（BM25 词频统计时过滤，避免停用词稀释关键词权重）
STOPWORDS = frozenset({
    "的", "了", "和", "是", "在", "与", "及", "或", "这", "那", "之", "而",
    "且", "但", "也", "都", "很", "又", "就", "还", "已", "将", "从", "到",
    "对", "于", "为", "以", "被", "把", "让", "给", "向", "要", "有", "会",
    "能", "可以", "应该", "因为", "所以", "如果", "然后", "我们", "你们", "他们",
    "她们", "它们", "我", "你", "他", "她", "它",
    "一个", "什么", "怎么", "为什么", "如何", "这个", "那个", "这些", "那些",
    "没有", "不是", "不会", "以及", "呢", "吗", "吧", "啊", "呀", "哦", "嗯",
    "自己", "时候", "可能", "起来", "出来", "这里", "那里", "的话",
})


@dataclass
class SearchHit:
    """检索命中结果"""
    doc: Document
    score: float          # 重排后的最终分数
    base_score: float     # 原始 RRF/BM25 分数
    is_reference: bool = False  # 是否为低置信参考结果
    is_virtual: bool = False    # 是否为虚拟的结构地图文档


# ==================== 混合检索器 ====================

class HybridRetriever:
    """
    混合检索器：
    - BM25（关键词）+ FAISS（语义）双路召回
    - RRF 融合
    - BGE Reranker 精排
    - LLM Query Rewriting（创作模式）
    - 邻域扩展（expand_window）
    - 结构地图注入（context_mode="structural"）
    """

    def __init__(
        self,
        loader: Optional[KnowledgeLoader] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        reranker_model: str = DEFAULT_RERANKER_MODEL,
        llm_base_url: str = DEFAULT_LLM_BASE_URL,
        llm_model: str = DEFAULT_LLM_MODEL,
        use_reranker: bool = True,
        cache_enabled: bool = True,
    ):
        # 1. 加载文档
        self.loader = loader or KnowledgeLoader()
        self.documents = self.loader.documents

        # 2. 构建文件映射（file_id -> List[Document] 按 chunk_index 排序）
        self.file_map: Dict[str, List[Document]] = {}
        for doc in self.documents:
            self.file_map.setdefault(doc.file_id, []).append(doc)
        for fid in self.file_map:
            self.file_map[fid].sort(key=lambda d: d.chunk_index)

        # 3. 构建索引（优先加载落盘缓存，避免每次启动重复嵌入知识库）
        self._build_bm25_index()
        if not self._try_load_index_cache(embedding_model):
            try:
                self._build_faiss_index(embedding_model)
                self._save_index_cache()
            except Exception as e:
                # TRD 10.6：Embedding/FAISS 不可用时降级为仅 BM25 + 标签检索
                print(f"[RAG] Embedding/FAISS 构建失败，降级为仅 BM25: {e}")
                self.faiss_available = False
                self.embedder = None
                self.faiss_index = None
                self.faiss_id_map = {}
                self._embeddings = None
                self._emb_dim = 0
                self._doc_row = {}

        # 4. 加载 Reranker（可选）
        self.use_reranker = use_reranker
        self.reranker = None
        if use_reranker:
            try:
                self.reranker = CrossEncoder(reranker_model, max_length=RERANKER_MAX_LENGTH)
            except Exception as e:
                print(f"[RAG] Reranker 加载失败，将跳过精排: {e}")
                self.use_reranker = False

        # 5. LLM 客户端（用于 Query Rewriting）
        self.llm_client = AsyncOpenAI(
            base_url=llm_base_url,
            api_key="not-needed",  # Ollama 不需要
            timeout=10.0,
        )
        self.llm_model = llm_model

        # 6. 缓存
        self.cache_enabled = cache_enabled
        self.cache: Dict[str, Tuple[float, List[SearchHit]]] = {}
        self._subset_cache: Dict[frozenset, tuple] = {}  # tags → 子集索引缓存

        print(f"[RAG] 初始化完成，共加载 {len(self.documents)} 个文档块")

    # ---------- 索引构建 ----------

    def _load_jieba_dict(self):
        """加载领域词典（缺失/失败时静默降级为默认分词）。"""
        try:
            jieba.load_userdict(str(USER_DICT_PATH))
        except Exception as e:
            print(f"[RAG] 领域词典加载失败（继续用默认分词）: {e}")

    def _tokenize(self, text: str) -> List[str]:
        """中文分词（用于 BM25）：领域词典 + 停用词过滤"""
        words = jieba.lcut(text)
        return [w for w in words if w.strip() and w not in STOPWORDS]

    # ---------- 索引落盘缓存 ----------

    def _try_load_index_cache(self, model_name: str) -> bool:
        """尝试从磁盘加载 FAISS 索引与向量矩阵。

        校验：模型名一致 + 文档 id 顺序一致 + 知识库指纹一致。
        加载成功仍会加载 Embedding 模型（查询编码需要），但跳过 1370 块文档的批量编码。
        """
        index_file = INDEX_CACHE_DIR / "faiss.index"
        emb_file = INDEX_CACHE_DIR / "embeddings.npy"
        meta_file = INDEX_CACHE_DIR / "meta.json"
        if not all(p.exists() for p in (index_file, emb_file, meta_file)):
            return False
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if meta.get("model") != model_name:
                return False
            if meta.get("doc_ids") != [d.id for d in self.documents]:
                return False
            if meta.get("fingerprint") != self.loader.knowledge_fingerprint():
                return False

            self.embedder = SentenceTransformer(model_name, device="cpu")
            self.embedder_model = model_name
            self.faiss_index = faiss.read_index(str(index_file))
            self._embeddings = np.load(emb_file)
            self._emb_dim = int(self._embeddings.shape[1])
            doc_ids = meta["doc_ids"]
            self.faiss_id_map = {i: self.documents[i] for i in range(len(doc_ids))}
            self._doc_row = {doc_id: i for i, doc_id in enumerate(doc_ids)}
            self.faiss_available = True
            print(f"[RAG] 从缓存加载 FAISS 索引（{self.faiss_index.ntotal} 个向量）")
            return True
        except Exception as e:
            print(f"[RAG] 索引缓存加载失败，将重新构建: {e}")
            return False

    def _save_index_cache(self) -> None:
        """把 FAISS 索引、向量矩阵与元数据写入磁盘。"""
        try:
            INDEX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self.faiss_index, str(INDEX_CACHE_DIR / "faiss.index"))
            np.save(INDEX_CACHE_DIR / "embeddings.npy", self._embeddings)
            (INDEX_CACHE_DIR / "meta.json").write_text(
                json.dumps({
                    "model": self.embedder_model,
                    "doc_ids": [d.id for d in self.documents],
                    "fingerprint": self.loader.knowledge_fingerprint(),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[RAG] FAISS 索引已缓存到 {INDEX_CACHE_DIR}")
        except Exception as e:
            print(f"[RAG] 索引缓存写入失败（不影响本次运行）: {e}")

    def _build_bm25_index(self):
        """构建 BM25 索引"""
        self._load_jieba_dict()
        self.bm25_docs = self.documents
        tokenized_corpus = [self._tokenize(d.content) for d in self.documents]
        self.bm25_index = BM25Okapi(tokenized_corpus)
        print(f"[RAG] BM25 索引构建完成，{len(self.bm25_docs)} 个文档")

    def _build_faiss_index(self, model_name: str):
        """构建 FAISS 向量索引"""
        print(f"[RAG] 加载 Embedding 模型: {model_name}")
        self.embedder_model = model_name  # 保存模型名，供 reload() 重建索引使用
        self.embedder = SentenceTransformer(model_name, device="cpu")
        dim = self.embedder.get_sentence_embedding_dimension()

        # 使用内积索引（余弦相似度需归一化）
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_id_map: Dict[int, Document] = {}  # FAISS 内部 ID -> Document

        # 批量编码
        contents = [d.content for d in self.documents]
        print(f"[RAG] 正在编码 {len(contents)} 个文档块...")
        embeddings = self.embedder.encode(
            contents,
            normalize_embeddings=True,  # 归一化后内积 = 余弦相似度
            show_progress_bar=True,
            batch_size=32
        )

        # 添加索引
        vectors = np.array(embeddings).astype('float32')
        self.faiss_index.add(vectors)

        # 记录向量矩阵与 doc.id→行号映射，供标签子集检索复用（免重复编码）
        self._embeddings = vectors
        self._emb_dim = dim
        self._doc_row = {doc.id: idx for idx, doc in enumerate(self.documents)}

        # 建立 ID 映射
        for idx, doc in enumerate(self.documents):
            self.faiss_id_map[idx] = doc

        print(f"[RAG] FAISS 索引构建完成，维度 {dim}，{self.faiss_index.ntotal} 个向量")
        self.faiss_available = True

    # ---------- Query Rewriting ----------

    async def _rewrite_query(self, query: str, mode: str) -> List[str]:
        """
        改写查询。
        - precise: 仅返回原查询
        - expansive: 调用 LLM 生成改写，去重后最多额外 MAX_REWRITE_QUERIES 条
                     （总查询数 = 1 原查询 + 改写，控制在 3 条内，避免召回成本 ~4x）
        """
        if mode == "precise":
            return [query]

        # expansive 模式
        prompt = f"""你是一个剧本杀知识检索助手。请将以下查询扩展为 {MAX_REWRITE_QUERIES} 个不同的相关搜索查询，覆盖同义词和相关概念。
要求：
1. 每个查询用中文
2. 用换行分隔，不要有序号
3. 保持简洁
4. 不要与原查询重复

原查询：{query}

扩展查询："""

        try:
            # wait_for 限制总时长：Ollama 未启动/慢时快速降级为原查询，
            # 避免整个 creative 检索被阻塞 REWRITE_TIMEOUT 秒。
            response = await asyncio.wait_for(
                self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=150,
                ),
                timeout=REWRITE_TIMEOUT,
            )
            text = response.choices[0].message.content.strip()
            queries = [q.strip() for q in text.split("\n") if q.strip()]

            # 去重（空 / 与原查询重复 / 互相重复），最多保留 MAX_REWRITE_QUERIES 条
            seen = {query}
            expanded = []
            for q in queries:
                if not q or q in seen:
                    continue
                seen.add(q)
                expanded.append(q)
                if len(expanded) >= MAX_REWRITE_QUERIES:
                    break
            if expanded:
                return [query] + expanded
        except Exception as e:
            print(f"[RAG] Query Rewriting 失败: {e}")

        return [query]

    # ---------- 多路召回 ----------

    def _bm25_search(
        self,
        query: str,
        recall_k: int,
        *,
        index: Optional[Any] = None,
        docs: Optional[List[Document]] = None,
    ) -> List[Tuple[Document, float]]:
        """BM25 召回。index/docs 缺省时用全量索引（标签子集检索时传入临时索引）。"""
        tokens = self._tokenize(query)
        bm25 = index or self.bm25_index
        doc_list = docs if docs is not None else self.bm25_docs
        scores = bm25.get_scores(tokens)
        # 获取 top-k
        top_indices = np.argsort(scores)[::-1][:recall_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((doc_list[idx], scores[idx]))
        return results

    def _faiss_search(
        self,
        query: str,
        recall_k: int,
        *,
        index: Optional[Any] = None,
        id_map: Optional[Dict[int, Document]] = None,
    ) -> List[Tuple[Document, float]]:
        """FAISS 向量召回。index/id_map 缺省时用全量索引（标签子集检索时传入临时索引）。"""
        if not getattr(self, "faiss_available", False):
            return []
        vec = self.embedder.encode([query], normalize_embeddings=True)
        vec = np.array(vec).astype('float32')
        idx = index or self.faiss_index
        if idx is None:
            return []
        imap = id_map if id_map is not None else self.faiss_id_map

        scores, indices = idx.search(vec, recall_k)
        results = []
        for score, i in zip(scores[0], indices[0]):
            if i >= 0 and i < len(imap):
                doc = imap[i]
                results.append((doc, float(score)))
        return results

    def _build_subset_index(self, docs: List[Document]):
        """
        为标签过滤后的子集构建临时检索索引（子集内检索）。

        召回只在子集内进行，而非全量召回再过滤——否则子集过小时
        top_k 候选会被无关文档稀释，子集内相关的文档反而进不了召回池。
        BM25 临时构建；FAISS 复用已编码向量（self._embeddings），
        只做索引添加，不重复调用 Embedding 模型。
        """
        tokenized = [self._tokenize(d.content) for d in docs]
        bm25_index = BM25Okapi(tokenized)
        id_map = {i: doc for i, doc in enumerate(docs)}

        # FAISS 不可用时只返回 BM25 子集索引
        if not getattr(self, "faiss_available", False):
            return bm25_index, None, id_map

        rows = [self._doc_row[d.id] for d in docs]
        vectors = self._embeddings[rows]
        faiss_index = faiss.IndexFlatIP(self._emb_dim)
        faiss_index.add(vectors)

        return bm25_index, faiss_index, id_map

    def _get_subset_index(self, docs: List[Document], tags_filter: List[str]):
        """取标签子集索引（带缓存，避免重复重建 BM25/FAISS）。"""
        key = frozenset(tags_filter)
        if key in self._subset_cache:
            return self._subset_cache[key]
        idx = self._build_subset_index(docs)
        if len(self._subset_cache) >= SUBSET_CACHE_MAX:
            self._subset_cache.clear()
        self._subset_cache[key] = idx
        return idx

    # ---------- RRF 融合 ----------

    def _rrf_fusion(
        self,
        result_lists: List[List[Tuple[Document, float]]],
        k: int = RRF_K
    ) -> List[Tuple[Document, float]]:
        """
        RRF（Reciprocal Rank Fusion）融合多个排序列表。
        返回按 RRF 分数排序的文档列表。
        """
        doc_scores: Dict[str, float] = {}
        doc_map: Dict[str, Document] = {}

        for rank_list in result_lists:
            for rank, (doc, _) in enumerate(rank_list, start=1):
                doc_id = doc.id
                if doc_id not in doc_map:
                    doc_map[doc_id] = doc
                doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + 1.0 / (k + rank)

        sorted_docs = sorted(
            [(doc_map[doc_id], score) for doc_id, score in doc_scores.items()],
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_docs

    # ---------- Reranker 精排 ----------

    def _rerank(
        self,
        candidates: List[Tuple[Document, float]],
        query: str,
        min_score: float
    ) -> List[SearchHit]:
        """使用 Cross-Encoder 精排"""
        if not candidates:
            return []

        if not self.use_reranker or not self.reranker:
            # 降级：Reranker 不可用，没有真实置信度分数。
            # RRF 原始分数（约 0.001~0.05）与阈值（0.6~0.8）量纲不符，
            # 不能直接套用。这里以融合排名作为相关度代理，把分数映射到
            # [1/n, 1]（rank 1 → 1.0，末位 → 1/n），使 min_score 退化为
            # "保留候选集头部比例"：游戏=高阈值只留前排，创作=低阈值多保留。
            # 候选来自 _rrf_fusion，已按 RRF 分数降序。
            n = len(candidates)
            results = []
            for rank, (doc, base) in enumerate(candidates, start=1):
                norm = 1.0 - (rank - 1) / n
                if norm >= min_score:
                    results.append(SearchHit(doc=doc, score=norm, base_score=base))
                elif norm >= min_score * 0.5:
                    results.append(SearchHit(
                        doc=doc, score=norm, base_score=base, is_reference=True
                    ))
            results.sort(key=lambda x: x.score, reverse=True)
            return results

        # 构造 (query, passage) 对。块长接近/超过 reranker max_length 时会被
        # 截断丢尾（大表格尤甚），这里对超长块做滑窗切片（重叠），
        # 每个候选取各窗口精排分的最大值，避免截断失真。
        window_chars = max(256, int(RERANKER_MAX_LENGTH * 0.8))
        pairs = []
        pair_cands = []  # 与 pairs 对齐：对应的候选下标
        for ci, (doc, _) in enumerate(candidates):
            content = doc.content
            if len(content) <= window_chars:
                pairs.append((query, content))
                pair_cands.append(ci)
            else:
                step = max(window_chars // 2, 1)
                for start in range(0, len(content), step):
                    pairs.append((query, content[start:start + window_chars]))
                    pair_cands.append(ci)

        scores = self.reranker.predict(pairs, batch_size=16)

        # 校准：bge-reranker 输出的是原始 logits（可为负、无上界），
        # 直接套用 0.6~0.8 的固定阈值会失去意义。经 sigmoid 归一化到 (0,1) 后，
        # 阈值才与“置信度”语义一致（0.8≈强相关，0.6≈弱相关）。
        best_scores: Dict[int, float] = {}
        for ci, s in zip(pair_cands, scores):
            sig = 1.0 / (1.0 + np.exp(-float(s)))
            best_scores[ci] = max(best_scores.get(ci, 0.0), sig)

        results = []
        for ci, (doc, base_score) in enumerate(candidates):
            rerank_score = best_scores.get(ci, 0.0)
            # rerank_score 为 sigmoid 归一化后的置信度，范围 (0,1)
            if rerank_score >= min_score:
                results.append(SearchHit(
                    doc=doc,
                    score=float(rerank_score),
                    base_score=base_score,
                    is_reference=False
                ))
            elif rerank_score >= min_score * 0.5:
                # 低置信结果，标记为参考
                results.append(SearchHit(
                    doc=doc,
                    score=float(rerank_score),
                    base_score=base_score,
                    is_reference=True
                ))
            # 低于 0.5*min_score 的直接丢弃

        # 按精排分数降序
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    # ---------- 邻域扩展 ----------

    def _expand_neighbors(
        self,
        hits: List[SearchHit],
        window: int
    ) -> List[SearchHit]:
        """基于 chunk_index 扩展相邻块"""
        if window <= 0 or not hits:
            return hits

        expanded = []
        seen_ids: Set[str] = set()

        for hit in hits:
            if hit.is_virtual:
                continue
            file_chunks = self.file_map.get(hit.doc.file_id, [])
            if not file_chunks:
                continue

            idx = hit.doc.chunk_index
            start = max(0, idx - window)
            end = min(len(file_chunks), idx + window + 1)

            for neighbor in file_chunks[start:end]:
                if neighbor.id not in seen_ids:
                    seen_ids.add(neighbor.id)
                    # 邻居块分数衰减（相邻越远衰减越多）
                    distance = abs(neighbor.chunk_index - idx)
                    decay = 0.9 ** distance
                    expanded.append(SearchHit(
                        doc=neighbor,
                        score=hit.score * decay,
                        base_score=hit.base_score * decay,
                        is_reference=hit.is_reference
                    ))

        # 去重后按分数排序
        expanded.sort(key=lambda x: x.score, reverse=True)
        return expanded

    def _expand_neighbors_budget(
        self,
        hits: List[SearchHit],
        budget: int,
        measure: Optional[Callable[[str], int]] = None,
    ) -> List[SearchHit]:
        """
        按总预算扩展相邻块（整块纳入，绝不截断任何块）。

        measure 决定预算单位：默认按字符数（len 字符计数），传入
        self._estimate_tokens 即为 Token 预算（见 _expand_neighbors_tokens）。
        每个命中块本身永远完整保留（含大表格）；随后按距离近→远逐层纳入
        邻居块，累计达到预算即停。相比固定窗口，预算把上下文消耗钉死在
        可控范围内，与块大小解耦。
        """
        if budget <= 0 or not hits:
            return hits

        _measure = measure or (lambda t: len(t))
        expanded = []
        seen_ids: Set[str] = set()

        for hit in hits:
            if hit.is_virtual:
                continue
            file_chunks = self.file_map.get(hit.doc.file_id, [])
            if not file_chunks:
                continue
            idx = hit.doc.chunk_index

            # 命中块 + 预算内邻居（按距离逐层向外，先近后远）
            block_ids = [hit.doc.id]
            total = _measure(hit.doc.content)
            dist = 1
            while total < budget:
                added = False
                for ni in (idx - dist, idx + dist):
                    if 0 <= ni < len(file_chunks):
                        nb = file_chunks[ni]
                        if nb.id not in block_ids and nb.id not in seen_ids:
                            block_ids.append(nb.id)
                            total += _measure(nb.content)
                            added = True
                if not added:
                    break
                dist += 1

            # 构造扩展结果（分数按距离衰减，与窗口版一致）
            id_to_doc = {b.id: b for b in file_chunks}
            for block_id in block_ids:
                if block_id in seen_ids:
                    continue
                seen_ids.add(block_id)
                nb = id_to_doc[block_id]
                distance = abs(nb.chunk_index - idx)
                decay = 0.9 ** distance
                expanded.append(SearchHit(
                    doc=nb,
                    score=hit.score * decay,
                    base_score=hit.base_score * decay,
                    is_reference=hit.is_reference
                ))

        expanded.sort(key=lambda x: x.score, reverse=True)
        return expanded

    def _estimate_tokens(self, text: str) -> int:
        """估算文本 Token 数（近似，不做真实分词）。

        中英混合按 CHARS_PER_TOKEN 字符/Token 折算；纯中文接近 1 字符/Token。
        取 1.5 偏保守，宁高勿低，确保贴近 LLM 硬上限时不越界。
        """
        return int(math.ceil(len(text) / CHARS_PER_TOKEN))

    def _expand_neighbors_tokens(
        self,
        hits: List[SearchHit],
        max_tokens: int,
    ) -> List[SearchHit]:
        """按 Token 上限扩展邻域（复用预算逻辑，measure 为 Token 估算）。"""
        return self._expand_neighbors_budget(hits, max_tokens, measure=self._estimate_tokens)

    # ---------- 结构地图注入 ----------

    def _add_structure_context(
        self,
        hits: List[SearchHit],
        max_outline_items: int = 20,
        max_structure_files: int = 3,
        total_outline_items: int = 30,
    ) -> List[SearchHit]:
        """
        在结果最前面插入命中文档的结构地图（多文档版）。

        收集 hits 涉及的每个文档（按最佳命中分降序，最多 max_structure_files 个），
        各自注入一份目录树，避免跨文档查询时其他文档的块失去章节锚点。
        多份地图的条目数共享 total_outline_items 总预算，防止 Token 成本失控。
        """
        if not hits:
            return hits

        # 1. 收集 hits 涉及的文档，按最佳命中分降序
        file_best: Dict[str, float] = {}
        for hit in hits:
            if hit.is_virtual:
                continue
            fid = hit.doc.file_id
            file_best[fid] = max(file_best.get(fid, 0.0), hit.score)
        ordered_files = sorted(file_best.items(), key=lambda x: x[1], reverse=True)

        # 2. 为每个文档生成结构地图（共享条目预算）
        virtual_hits: List[SearchHit] = []
        remaining_items = total_outline_items
        for fid, _ in ordered_files[:max_structure_files]:
            structure = self.loader.get_structure(fid)
            if not structure:
                continue
            per_file = max(1, min(max_outline_items, remaining_items))
            remaining_items -= per_file
            outline_text = self._format_outline(structure, per_file)

            virtual_doc = Document(
                id=f"{fid}_outline",
                content=outline_text,
                title=f"📖 {structure.title} 结构概览",
                source_file=structure.file_path,
                file_id=fid,
                chunk_index=-1,  # 特殊标记
                total_chunks=1,
                metadata={"tags": ["_outline"], "is_virtual": True}
            )
            virtual_hits.append(SearchHit(
                doc=virtual_doc,
                score=1.0,  # 虚拟地图最高优先级
                base_score=1.0,
                is_reference=False,
                is_virtual=True
            ))

        if not virtual_hits:
            return hits

        return virtual_hits + hits

    def _format_outline(self, structure, max_items: int) -> str:
        """将文档结构渲染为文本（供结构地图使用）"""
        outline_text = f"📖 **文档全貌：{structure.title}**\n\n"
        outline_text += f"📌 **摘要**：{structure.summary}\n\n" if structure.summary else ""
        outline_text += "**目录结构**：\n"
        for item in structure.outline[:max_items]:
            indent = "  " * (item["level"] - 1)
            outline_text += f"{indent}- {item['title']}\n"
        if len(structure.outline) > max_items:
            outline_text += f"...（共 {len(structure.outline)} 个章节）\n"
        return outline_text

    # ---------- 主搜索接口 ----------

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.7,
        mode: str = "precise",        # "precise" | "expansive"
        expand_window: int = 0,       # 邻域扩展窗口大小（旧方式，按块数）
        max_expand_chars: int = 0,    # 邻域扩展总字符预算（按长度）
        max_expand_tokens: int = 0,   # 邻域扩展 Token 上限（按估算，优先于字符预算）
        context_mode: str = "expanded", # "expanded" | "structural"
        recall_k: int = 30,           # 每路召回的候选数
        tags_filter: Optional[List[str]] = None,  # 标签过滤
    ) -> List[SearchHit]:
        """
        混合检索主入口。

        Args:
            query: 查询文本
            top_k: 最终返回结果数量
            min_score: 精排分数阈值（0~1）
            mode: "precise"（精准，不改写）或 "expansive"（改写扩展）
            expand_window: 邻域扩展窗口（按块数；有 Token/字符预算时忽略）
            max_expand_chars: 邻域扩展总字符预算（按长度；命中块整块保留，
                              按距离近→远纳入邻居，累计达预算即停）
            max_expand_tokens: 邻域扩展 Token 上限（按 CHARS_PER_TOKEN 折算估算，
                               优先于字符预算；创作阶段≈3000，游戏阶段=0）
            context_mode: "expanded"（仅返回块）或 "structural"（插入结构地图）
            recall_k: 每路召回的候选数量
            tags_filter: 元数据标签过滤

        Returns:
            List[SearchHit]
        """
        # 1. 缓存检查
        cache_key = hashlib.md5(
            f"{query}_{top_k}_{min_score}_{mode}_{expand_window}_{max_expand_chars}_{max_expand_tokens}_{context_mode}_{recall_k}_{tags_filter}".encode()
        ).hexdigest()

        if self.cache_enabled and cache_key in self.cache:
            cached_time, cached_result = self.cache[cache_key]
            if time.time() - cached_time < CACHE_TTL:
                # 深拷贝返回，避免调用方改动污染缓存
                return copy.deepcopy(cached_result)

        # 2. 过滤文档（按标签 → 子集内检索）
        filtered_docs = self.documents
        subset_index = None  # 非 None 时，召回只在子集索引内进行
        if tags_filter:
            filtered_ids = set()
            for doc in self.documents:
                doc_tags = doc.metadata.get("tags", [])
                if any(tag in doc_tags for tag in tags_filter):
                    filtered_ids.add(doc.id)
            filtered_docs = [d for d in self.documents if d.id in filtered_ids]

            # 匹配数=0：标签无效/拼写错误，返回空（而非静默回退全量）
            if len(filtered_docs) == 0:
                print(f"[RAG] 标签过滤 {tags_filter} 匹配 0 个文档，返回空")
                return []
            # 匹配太少：放宽为全量，避免召回过空
            if len(filtered_docs) < 5:
                print(f"[RAG] 标签过滤 {tags_filter} 后文档过少（{len(filtered_docs)}），放宽回退全部")
                filtered_docs = self.documents
            else:
                # 子集内检索：为子集构建临时索引（带缓存），召回不越界、不被无关文档稀释
                subset_index = self._get_subset_index(filtered_docs, tags_filter)

        # 如果过滤后为空，返回空
        if not filtered_docs:
            return []

        # 3. Query Rewriting
        rewritten_queries = await self._rewrite_query(query, mode)

        # 4. 多路召回（子集内检索：有 subset_index 时仅在此子集索引中召回）
        all_results: List[List[Tuple[Document, float]]] = []

        for i, q in enumerate(rewritten_queries):
            # 原查询（首条）用完整 recall_k；改写查询是补充召回，降低深度控成本
            q_recall = recall_k if i == 0 else max(5, recall_k // 2)
            if subset_index is not None:
                bm25_idx, faiss_idx, id_map = subset_index
                bm25_results = self._bm25_search(q, q_recall, index=bm25_idx, docs=filtered_docs)
                faiss_results = self._faiss_search(q, q_recall, index=faiss_idx, id_map=id_map)
            else:
                # 全量：同时执行 BM25 和 FAISS
                bm25_results = self._bm25_search(q, q_recall)
                faiss_results = self._faiss_search(q, q_recall)

            all_results.append(bm25_results)
            all_results.append(faiss_results)

        # 如果没有任何结果，返回空
        if not all_results or not any(all_results):
            return []

        # 5. RRF 融合
        fused = self._rrf_fusion(all_results, k=RRF_K)

        # 6. 精排
        reranked = self._rerank(fused, query, min_score)

        # 7. 邻域扩展（Token 预算优先 → 字符预算 → 窗口，逐级兜底）
        if max_expand_tokens > 0:
            reranked = self._expand_neighbors_tokens(reranked, max_expand_tokens)
        elif max_expand_chars > 0:
            reranked = self._expand_neighbors_budget(reranked, max_expand_chars)
        elif expand_window > 0:
            reranked = self._expand_neighbors(reranked, expand_window)

        # 8. 结构地图注入（仅当有结果且 context_mode="structural"）
        if context_mode == "structural" and reranked:
            reranked = self._add_structure_context(reranked)

        # 9. 截断（虚拟结构地图不占 top_k 名额，避免挤掉真实命中块）
        virtual_hits = [h for h in reranked if h.is_virtual]
        real_hits = [h for h in reranked if not h.is_virtual][:top_k]
        final_results = virtual_hits + real_hits

        # 10. 缓存（存原列表；返回时深拷贝，避免调用方改动污染缓存）
        if self.cache_enabled:
            self.cache[cache_key] = (time.time(), final_results)
            return copy.deepcopy(final_results)

        return final_results

    # ---------- 按标签直接检索 ----------

    def search_by_tags(
        self,
        tags: List[str],
        top_k: int = 5
    ) -> List[Document]:
        """直接按标签获取文档（不经过向量检索）。

        按匹配到的标签数降序、chunk_index 升序排序，结果确定且更相关者在前。
        """
        tag_set = set(tags)
        scored = []
        for doc in self.documents:
            doc_tags = set(doc.metadata.get("tags", []))
            matched = len(tag_set & doc_tags)
            if matched:
                scored.append((matched, doc))
        scored.sort(key=lambda x: (-x[0], x[1].chunk_index))
        return [doc for _, doc in scored[:top_k]]

    # ---------- 热更新 ----------

    def reload(self):
        """重新加载所有文档并重建索引"""
        self.loader.reload()
        self.documents = self.loader.documents

        # 重建文件映射
        self.file_map.clear()
        for doc in self.documents:
            self.file_map.setdefault(doc.file_id, []).append(doc)
        for fid in self.file_map:
            self.file_map[fid].sort(key=lambda d: d.chunk_index)

        # 重建索引（FAISS 用保存的模型名，避免依赖 sentence-transformers 内部结构）
        self._build_bm25_index()
        try:
            self._build_faiss_index(self.embedder_model)
        except Exception as e:
            print(f"[RAG] FAISS 重建失败，降级为仅 BM25: {e}")
            self.faiss_available = False
            self.embedder = None
            self.faiss_index = None
            self.faiss_id_map = {}
            self._embeddings = None
            self._emb_dim = 0
            self._doc_row = {}

        # 清空缓存
        self.cache.clear()
        self._subset_cache.clear()
        print("[RAG] 热更新完成")


# ==================== 工厂函数 ====================

_global_retriever: Optional[HybridRetriever] = None

def get_retriever() -> HybridRetriever:
    """获取全局单例 Retriever"""
    global _global_retriever
    if _global_retriever is None:
        _global_retriever = HybridRetriever()
    return _global_retriever
