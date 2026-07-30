"""Offline knowledge ingestion: docs -> chunks -> embeddings -> Qdrant (SRS §32).

Knowledge is indexed offline via ``scripts/ingest_knowledge.py``; nothing in
the request path imports this module. Source documents are Markdown files with
a minimal front-matter block declaring ``title`` and ``doc_type``:

    ---
    title: Refund Policy
    doc_type: refund_policy
    ---

    Document body...
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

from app.config.settings import get_settings
from app.rag.chunking import chunk_text
from app.rag.embeddings import EmbeddingModel, get_embedding_model
from app.rag.schemas import IngestionReport, KnowledgeChunk, KnowledgeDocument
from app.rag.vector_store import KnowledgeVectorStore

logger = logging.getLogger(__name__)

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_document(source: str, raw: str) -> KnowledgeDocument:
    """Parse one Markdown file into a document with metadata.

    Missing front matter degrades to sensible defaults (title from the file
    name, ``doc_type`` ``product_doc``) rather than failing the whole run.
    """
    metadata, body = _split_front_matter(raw)
    return KnowledgeDocument(
        source=source,
        title=metadata.get("title") or Path(source).stem.replace("-", " ").title(),
        doc_type=metadata.get("doc_type", "product_doc"),
        text=body.strip(),
    )


def _split_front_matter(raw: str) -> Tuple[dict, str]:
    match = _FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    metadata = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if _ and key.strip():
            metadata[key.strip().lower()] = value.strip()
    return metadata, raw[match.end() :]


def load_documents(docs_dir: Path) -> List[KnowledgeDocument]:
    """Load every Markdown document under ``docs_dir`` (recursive, sorted)."""
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"knowledge docs directory not found: {docs_dir}")
    documents = []
    for path in sorted(docs_dir.rglob("*.md")):
        raw = path.read_text(encoding="utf-8")
        document = parse_document(path.relative_to(docs_dir).as_posix(), raw)
        if document.text:
            documents.append(document)
    return documents


def chunk_document(document: KnowledgeDocument) -> List[KnowledgeChunk]:
    """Chunk one document, carrying its citation metadata onto every chunk."""
    settings = get_settings()
    return [
        KnowledgeChunk(
            text=text,
            source=document.source,
            title=document.title,
            doc_type=document.doc_type,
            chunk_index=index,
        )
        for index, text in enumerate(
            chunk_text(
                document.text,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
        )
    ]


async def ingest_directory(
    docs_dir: Path,
    *,
    store: Optional[KnowledgeVectorStore] = None,
    embedder: Optional[EmbeddingModel] = None,
) -> IngestionReport:
    """Index every document under ``docs_dir`` into Qdrant; returns a report."""
    store = store or KnowledgeVectorStore()
    embedder = embedder or get_embedding_model()

    documents = load_documents(docs_dir)
    chunks: List[KnowledgeChunk] = []
    for document in documents:
        chunks.extend(chunk_document(document))

    await store.ensure_collection()
    vectors = await embedder.embed([chunk.text for chunk in chunks])
    written = await store.upsert_chunks(chunks, vectors)

    report = IngestionReport(
        documents=len(documents),
        chunks=written,
        collection=store.collection,
        sources=[document.source for document in documents],
    )
    logger.info(
        "knowledge ingestion complete: documents=%s chunks=%s collection=%s",
        report.documents,
        report.chunks,
        report.collection,
    )
    return report
