"""RAG pipeline: chunking, embeddings, Qdrant vector store, retrieval (SRS §32, §33).

Knowledge is indexed offline (``scripts/ingest_knowledge.py``) and retrieved at
runtime by the Enterprise MCP knowledge tools via :class:`KnowledgeRetriever`.
Agents never import this package — they reach knowledge only through MCP.
"""
