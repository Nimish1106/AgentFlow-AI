"""Typed payloads flowing through the RAG pipeline (SRS §32, §33)."""

from typing import List

from pydantic import BaseModel, ConfigDict, Field

# Payload keys stored alongside every vector in Qdrant. The retriever reads
# them back verbatim, so ingestion and retrieval must agree on these names.
PAYLOAD_TEXT = "text"
PAYLOAD_SOURCE = "source"
PAYLOAD_TITLE = "title"
PAYLOAD_DOC_TYPE = "doc_type"
PAYLOAD_CHUNK_INDEX = "chunk_index"


class KnowledgeDocument(BaseModel):
    """One source document loaded from the knowledge docs directory."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    title: str
    doc_type: str
    text: str


class KnowledgeChunk(BaseModel):
    """One indexable chunk of a knowledge document."""

    model_config = ConfigDict(from_attributes=True)

    text: str
    source: str
    title: str
    doc_type: str
    chunk_index: int

    def payload(self) -> dict:
        """Qdrant point payload for this chunk."""
        return {
            PAYLOAD_TEXT: self.text,
            PAYLOAD_SOURCE: self.source,
            PAYLOAD_TITLE: self.title,
            PAYLOAD_DOC_TYPE: self.doc_type,
            PAYLOAD_CHUNK_INDEX: self.chunk_index,
        }


class RetrievedChunk(BaseModel):
    """One search hit returned to the knowledge tools, with its citation."""

    model_config = ConfigDict(from_attributes=True)

    text: str
    source: str
    title: str
    doc_type: str
    score: float = Field(ge=-1.0, le=1.0)


class IngestionReport(BaseModel):
    """Summary of one offline ingestion run."""

    model_config = ConfigDict(from_attributes=True)

    documents: int
    chunks: int
    collection: str
    sources: List[str]
