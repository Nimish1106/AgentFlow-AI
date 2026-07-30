"""Offline knowledge ingestion CLI (SRS §32: knowledge is indexed offline).

Run inside the Compose stack (Qdrant reachable at ``QDRANT_URL``):

    docker compose exec backend python -m scripts.ingest_knowledge

or locally against the exposed port:

    QDRANT_URL=http://localhost:6333 python -m scripts.ingest_knowledge
"""

import argparse
import asyncio
from pathlib import Path

from app.config.settings import get_settings
from app.observability.logging import configure_logging
from app.rag.ingestion import ingest_directory


async def main(docs_dir: Path) -> None:
    """Ingest every knowledge document under ``docs_dir`` into Qdrant."""
    report = await ingest_directory(docs_dir)
    print(
        f"Ingested {report.documents} documents ({report.chunks} chunks) "
        f"into collection '{report.collection}':"
    )
    for source in report.sources:
        print(f"  - {source}")


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=Path(get_settings().knowledge_docs_dir),
        help="Directory of Markdown knowledge documents",
    )
    args = parser.parse_args()
    asyncio.run(main(args.docs_dir))
