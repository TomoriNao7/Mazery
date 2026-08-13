#文档加载
import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


# ==================== 数据类 ====================

@dataclass
class Document:
    """RAG 检索的基本文档单元（块）"""
    id: str  # 唯一标识，如 "古风悬疑_01"
    content: str  # 块文本内容（不含标题）
    title: str  # 块标题（继承父级标题）
    source_file: str  # 来源文件相对路径
    file_id: str = ""  # 所属文件的唯一标识（如 "古风悬疑"）
    chunk_index: int = 0  # 在该文件中的块序号（从0开始）
    total_chunks: int = 0  # 该文件总块数
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 常用元数据: tags, version, source, verified, section_title


@dataclass
class DocumentStructure:
    """文档结构摘要（轻量级目录树）"""
    file_id: str
    file_path: str
    title: str  # 文档主标题（第一个 #）
    outline: List[Dict[str, Any]]  # [{"level": 1, "title": "...", "line": 0}, ...]
    summary: str = ""  # 首段摘要（前200字）


# ==================== 加载器 ====================

class KnowledgeLoader:
    """加载 RAG 知识文档，生成块列表和结构索引"""

    # 知识库根目录（相对于项目根）
    RAG_ROOT = Path(__file__).parent.parent / "data" / "knowledge" / "rag"

    # 切块参数
    MAX_CHARS = 600  # 单块最大字符数（约300~400 token，细粒度利于召回与精排）
    # 表格行：以 | 开头且至少含两个 | 的行（表头/数据行），允许中文内容
    # 分隔行（| --- | --- |）也含多个 |，会被一并覆盖
    TABLE_ROW_PATTERN = re.compile(r'^\s*\|.*\|.*$')

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = Path(root_dir) if root_dir else self.RAG_ROOT
        if not self.root_dir.exists():
            raise FileNotFoundError(f"Knowledge directory not found: {self.root_dir}")

        self.documents: List[Document] = []
        self.structures: Dict[str, DocumentStructure] = {}
        self._raw_text_cache: Dict[str, str] = {}

        self._load_all()

    # ---------- 主加载流程 ----------

    def _load_all(self):
        """遍历所有 .md 文件并加载"""
        for md_file in self.root_dir.glob("**/*.md"):
            docs, structure, raw_text = self._load_single_file(md_file)
            self.documents.extend(docs)
            if structure:
                self.structures[structure.file_id] = structure
            self._raw_text_cache[structure.file_id] = raw_text

    def _load_single_file(self, file_path: Path) -> Tuple[List[Document], Optional[DocumentStructure], str]:
        """加载单个 Markdown 文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()

        # 1. 解析 frontmatter
        frontmatter, body = self._parse_frontmatter(raw)
        metadata = frontmatter or {}

        # 2. 推断文件ID和标签
        rel_path = str(file_path.relative_to(self.root_dir))
        parent_folder = file_path.parent.name
        # file_id 直接用相对路径规范化，保证跨目录唯一：
        # background/bg_仙侠.md → background_bg_仙侠；core/01_诡计分类大全.md → core_01_诡计分类大全
        file_id = rel_path[:-3] if rel_path.endswith(".md") else rel_path
        file_id = file_id.replace("\\", "_").replace("/", "_")

        inferred_tags = [parent_folder, file_id]
        if "tags" in metadata:
            existing = metadata["tags"] if isinstance(metadata["tags"], list) else [metadata["tags"]]
            metadata["tags"] = list(set(existing + inferred_tags))
        else:
            metadata["tags"] = inferred_tags

        # 3. 提取引用块（> 开头）作为上下文，保留在正文中
        #    但不用它单独成块，而是随所属章节一起

        # 4. 按 ## 初步分块
        raw_blocks = self._split_by_heading(body, level=2)

        # 5. 对每个块进行递归切分（含表格保护）
        final_blocks = []
        for title, content in raw_blocks:
            final_blocks.extend(self._split_oversized_block(
                title, content,
                max_chars=self.MAX_CHARS,
                level=3  # 从三级标题开始递归
            ))

        # 6. 如果没有分到任何块，整个正文作为一个块
        if not final_blocks and body.strip():
            final_blocks = [("", body.strip())]

        # 7. 构建 Document 对象
        docs = []
        total = len(final_blocks)
        for idx, (title, content) in enumerate(final_blocks):
            doc_id = f"{file_id}_{idx + 1:02d}"
            meta = metadata.copy()
            meta["section_title"] = title
            docs.append(Document(
                id=doc_id,
                content=content.strip(),
                title=title,
                source_file=rel_path,
                file_id=file_id,
                chunk_index=idx,
                total_chunks=total,
                metadata=meta
            ))

        # 8. 构建结构树
        structure = self._build_structure(body, file_id, rel_path)

        return docs, structure, raw

    # ---------- 切块核心方法 ----------

    def _split_oversized_block(self, title: str, content: str,
                               max_chars: int = 1200,
                               level: int = 3,
                               _depth: int = 0) -> List[Tuple[str, str]]:
        """
        递归切分超大块。
        优先级：下一级标题 > 表格保护 > 段落切分 > 句子切分（兜底）
        """
        # 深度保护，防止无限递归
        if _depth > 10:
            # 极端情况：截断并返回
            return [(title, content[:max_chars] + "\n... [内容过长已截断]")]

        # 如果内容不超限，直接返回
        if len(content) <= max_chars:
            return [(title, content)]

        # ---- 策略1：尝试按下一级标题切分 ----
        sub_blocks = self._split_by_heading(content, level=level)
        if len(sub_blocks) > 1:
            results = []
            for sub_title, sub_content in sub_blocks:
                full_title = f"{title} → {sub_title}" if title else sub_title
                results.extend(self._split_oversized_block(
                    full_title, sub_content, max_chars, level + 1, _depth + 1
                ))
            return results

        # ---- 策略2：尝试按表格保护切分 ----
        # 将表格整体作为不可分割单元
        table_protected = self._protect_tables(content)
        if len(table_protected) > 1:
            # 按表格边界分割，但每个表格保持完整
            segments = self._split_by_table_boundary(content)
            if len(segments) > 1:
                results = []
                for seg in segments:
                    # 递归检查每个段是否仍超限
                    results.extend(self._split_oversized_block(
                        title, seg, max_chars, level, _depth + 1
                    ))
                return results

        # ---- 策略3：按段落（\n\n）切分 ----
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if len(paragraphs) > 1:
            results = []
            current_chunks = []
            current_len = 0

            for para in paragraphs:
                # 检查段落是否包含保护表格标记（避免表格被拆）
                para_len = len(para)

                # 如果单段落超限且不包含表格，递归到句子切分
                if para_len > max_chars and not self._contains_table(para):
                    # 先保存当前组
                    if current_chunks:
                        results.append((title, "\n\n".join(current_chunks)))
                        current_chunks = []
                        current_len = 0
                    # 递归处理这个超长段落
                    results.extend(self._split_oversized_block(
                        title, para, max_chars, level, _depth + 1
                    ))
                    continue

                # 单段落超限但包含表格 → 用表格保护逻辑处理
                if para_len > max_chars and self._contains_table(para):
                    if current_chunks:
                        results.append((title, "\n\n".join(current_chunks)))
                        current_chunks = []
                        current_len = 0
                    # 强制把表格作为整体
                    results.append((title, para))
                    continue

                # 正常合并段落
                if current_len + para_len > max_chars and current_chunks:
                    results.append((title, "\n\n".join(current_chunks)))
                    current_chunks = [para]
                    current_len = para_len
                else:
                    current_chunks.append(para)
                    current_len += para_len + 2

            if current_chunks:
                results.append((title, "\n\n".join(current_chunks)))

            # 如果切分后仍有超长块，递归处理
            final_results = []
            for t, c in results:
                if len(c) > max_chars:
                    final_results.extend(self._split_oversized_block(
                        t, c, max_chars, level, _depth + 1
                    ))
                else:
                    final_results.append((t, c))
            return final_results

        # ---- 策略4：兜底——按句子切分 ----
        sentences = re.split(r'([。！？])', content)
        # 重组句子（保留标点）
        sentences = [''.join(i) for i in zip(sentences[0::2], sentences[1::2])]
        results = []
        buffer = ""
        for sent in sentences:
            if len(buffer) + len(sent) > max_chars:
                if buffer:
                    results.append((title, buffer.strip()))
                buffer = sent
            else:
                buffer += sent
        if buffer:
            results.append((title, buffer.strip()))

        return results if results else [(title, content[:max_chars] + "\n... [内容过长已截断]")]

    # ---------- 表格保护辅助方法 ----------

    def _protect_tables(self, text: str) -> List[str]:
        """
        识别并提取文本中的表格，返回 [非表格文本, 表格文本, ...] 交替列表。
        用于保护表格不被段落切分破坏。
        """
        lines = text.splitlines()
        result = []
        current_segment = []
        in_table = False

        for line in lines:
            # 分隔行（| --- | --- |）含多个 |，已被 TABLE_ROW_PATTERN 覆盖
            is_table = bool(self.TABLE_ROW_PATTERN.match(line) if line.strip() else False)

            if is_table:
                if not in_table and current_segment:
                    result.append("\n".join(current_segment))
                    current_segment = []
                in_table = True
                current_segment.append(line)
            else:
                if in_table and current_segment:
                    result.append("\n".join(current_segment))
                    current_segment = []
                    in_table = False
                current_segment.append(line)

        if current_segment:
            result.append("\n".join(current_segment))

        return result

    def _split_by_table_boundary(self, content: str) -> List[str]:
        """
        按表格边界分割内容，返回段落列表，表格整体保留。
        """
        segments = []
        lines = content.splitlines()
        current = []
        in_table = False

        for line in lines:
            # 分隔行（| --- | --- |）含多个 |，已被 TABLE_ROW_PATTERN 覆盖
            is_table = bool(self.TABLE_ROW_PATTERN.match(line) if line.strip() else False)

            if is_table:
                if not in_table and current:
                    segments.append("\n".join(current))
                    current = []
                in_table = True
                current.append(line)
            else:
                if in_table and current:
                    segments.append("\n".join(current))
                    current = []
                    in_table = False
                # 空行作为段落分隔
                if not line.strip() and current:
                    segments.append("\n".join(current))
                    current = []
                else:
                    current.append(line)

        if current:
            segments.append("\n".join(current))

        return [s.strip() for s in segments if s.strip()]

    def _contains_table(self, text: str) -> bool:
        """检查文本是否包含表格"""
        lines = text.splitlines()
        for line in lines:
            if line.strip() and self.TABLE_ROW_PATTERN.match(line):
                return True
        return False

    # ---------- 辅助方法 ----------

    def _parse_frontmatter(self, raw: str) -> Tuple[Dict, str]:
        """分离 YAML frontmatter 和正文"""
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                fm_yaml = parts[1]
                body = parts[2]
                try:
                    fm = yaml.safe_load(fm_yaml)
                    return fm or {}, body
                except yaml.YAMLError:
                    return {}, raw
        return {}, raw

    def _split_by_heading(self, text: str, level: int = 2) -> List[Tuple[str, str]]:
        """按指定级别标题分割，返回 [(标题, 内容), ...]"""
        pattern = rf'^{"#" * level}\s+(.+)$'
        lines = text.splitlines()
        blocks = []
        current_title = ""
        current_content = []

        for line in lines:
            match = re.match(pattern, line)
            if match:
                if current_title or current_content:
                    blocks.append((current_title, "\n".join(current_content).strip()))
                current_title = match.group(1).strip()
                current_content = []
            else:
                current_content.append(line)

        if current_title or current_content:
            blocks.append((current_title, "\n".join(current_content).strip()))

        return blocks

    def _build_structure(self, body: str, file_id: str, rel_path: str) -> DocumentStructure:
        """从正文提取标题层级和摘要"""
        lines = body.splitlines()
        outline = []
        main_title = file_id

        for i, line in enumerate(lines):
            if line.startswith("# "):
                main_title = line[2:].strip()
                outline.append({"level": 1, "title": main_title, "line": i})
            elif line.startswith("## "):
                outline.append({"level": 2, "title": line[3:].strip(), "line": i})
            elif line.startswith("### "):
                outline.append({"level": 3, "title": line[4:].strip(), "line": i})
            # 保留四级标题用于更精确的结构
            elif line.startswith("#### "):
                outline.append({"level": 4, "title": line[5:].strip(), "line": i})

        # 摘要：取第一个非标题、非引用、非空行
        summary = ""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
                summary = stripped[:200]
                break

        return DocumentStructure(
            file_id=file_id,
            file_path=rel_path,
            title=main_title,
            outline=outline,
            summary=summary
        )

    # ---------- 对外接口 ----------

    def get_structure(self, file_id: str) -> Optional[DocumentStructure]:
        """获取文档结构"""
        return self.structures.get(file_id)

    def get_raw_text(self, file_id: str) -> Optional[str]:
        """获取全文原始文本"""
        return self._raw_text_cache.get(file_id)

    def get_documents_by_file(self, file_id: str) -> List[Document]:
        """获取某文件的所有块（已排序）"""
        return [d for d in self.documents if d.file_id == file_id]

    def reload(self):
        """重新加载所有文档（热更新用）"""
        self.documents.clear()
        self.structures.clear()
        self._raw_text_cache.clear()
        self._load_all()