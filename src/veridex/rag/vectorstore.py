from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from veridex.config import settings
from veridex.rag.embeddings import get_embeddings


def get_vector_store() -> Chroma:
    """Connect to the persistent Chroma collection."""
    index_dir = Path(settings.chroma_persist_dir)

    return Chroma(
        collection_name=settings.chroma_collection,
        embedding_function=get_embeddings(),
        persist_directory=str(index_dir),
    )


def index_documents(
    documents: list[Document],
    batch_size: int = 50,
) -> int:
    """Add chunks to Chroma in batches using stable IDs."""
    if not documents:
        return 0

    store = get_vector_store()

    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]

        store.add_documents(
            documents=batch,
            ids=[doc.metadata["chunk_id"] for doc in batch],
        )

    return len(documents)
