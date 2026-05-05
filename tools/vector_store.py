"""Chroma vector store for contract clause retrieval — B.

封装 Contract Agent 用的 RAG 知识库:
- 把 CEA 标准租约 PDF (5 份) 按页切块,embedding 入库
- 给定查询文本 (e.g. "deposit amount"), 返回 top-k 相关条款片段

存储:
- persist_dir: 默认 .chroma/ (项目根, .gitignore 已排除)
- 不传 persist_dir → 内存模式 (测试 / CI 用,关掉就没)

embedding:
- 用 chromadb 自带 DefaultEmbeddingFunction (ONNX all-MiniLM-L6-v2)
- 不依赖外部 API key,首次运行会下载 ~90MB 模型
- 后续若想升级 Gemini text-embedding-004,只改一处即可
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import settings
from tools.pdf_parser import extract_pages

logger = logging.getLogger(__name__)


CEA_COLLECTION_NAME = "cea_standard_lease"


@dataclass
class SearchResult:
    text: str
    document: str
    page: int
    score: float
    """Lower = more similar (Chroma uses distance, not cosine similarity)."""


class ContractKnowledgeBase:
    """Chroma 向量库的薄封装,聚焦 contract clause retrieval。"""

    def __init__(
        self,
        collection_name: str = CEA_COLLECTION_NAME,
        persist_dir: Path | str | None = None,
    ) -> None:
        import chromadb

        if persist_dir is None:
            self.client = chromadb.EphemeralClient()
        else:
            persist_path = Path(persist_dir)
            persist_path.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(persist_path))

        self.collection = self.client.get_or_create_collection(name=collection_name)

    def ingest_pdf(self, pdf_path: Path | str, doc_id: str | None = None) -> int:
        """把 PDF 按页切块入库。

        Returns:
            实际入库的 chunk 数量 (跳过空页)。
        """
        pdf_path = Path(pdf_path)
        if doc_id is None:
            doc_id = pdf_path.stem

        pages = extract_pages(pdf_path)
        if not pages:
            logger.warning("No text extracted from %s, skipping ingest", pdf_path)
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for page_num, page_text in enumerate(pages, start=1):
            if len(page_text.strip()) < 20:
                continue
            ids.append(f"{doc_id}::page_{page_num}")
            documents.append(page_text)
            metadatas.append(
                {
                    "document": doc_id,
                    "page": page_num,
                    "source": str(pdf_path),
                }
            )

        if not ids:
            logger.warning("All pages of %s were empty, nothing to ingest", pdf_path)
            return 0

        # upsert: 如果已经存在同 ID,替换;不存在则插入
        # 这样对同一份 PDF 重复 ingest 不会爆出重复
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info("Ingested %d chunks from %s", len(ids), pdf_path.name)
        return len(ids)

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        """查询 top-k 相关 chunk。"""
        if not query.strip():
            return []

        result_count = min(k, self.collection.count())
        if result_count == 0:
            return []

        raw = self.collection.query(query_texts=[query], n_results=result_count)

        # Chroma 返回的是 list-of-lists (因为支持 batch query),取第一组
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        return [
            SearchResult(
                text=doc,
                document=str(meta.get("document", "unknown")),
                page=int(meta.get("page", 0)),
                score=float(dist),
            )
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "collection": self.collection.name,
            "chunk_count": self.collection.count(),
        }


def seed_from_cea_templates(
    kb: ContractKnowledgeBase | None = None,
    *,
    cea_dir: Path | None = None,
    force: bool = False,
) -> int:
    """把 data/cea_standard_lease/ 下所有 PDF ingest 进知识库。

    Args:
        kb: 现有 KB 实例,不传则用默认 .chroma/ 持久化路径新建一个。
        cea_dir: CEA PDF 目录,默认 settings.cea_standard_lease_dir。
        force: True 时即使集合非空也重新 ingest (用于强制刷新)。

    Returns:
        本次新增 / 更新的 chunk 总数。
    """
    if kb is None:
        kb = ContractKnowledgeBase(persist_dir=settings.chroma_persist_dir)

    if not force and kb.stats()["chunk_count"] > 0:
        logger.info(
            "Collection already has %d chunks, skip seeding (force=True 强制刷新)",
            kb.stats()["chunk_count"],
        )
        return 0

    target_dir = cea_dir or settings.cea_standard_lease_dir
    if not target_dir.exists():
        logger.warning("CEA template dir not found: %s", target_dir)
        return 0

    total = 0
    for pdf_path in sorted(target_dir.glob("*.pdf")):
        total += kb.ingest_pdf(pdf_path)

    logger.info("Seeded knowledge base with %d total chunks from %s", total, target_dir)
    return total


__all__ = [
    "CEA_COLLECTION_NAME",
    "ContractKnowledgeBase",
    "SearchResult",
    "seed_from_cea_templates",
]
