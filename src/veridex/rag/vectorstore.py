from pathlib import Path
from threading import Lock

from langchain_chroma import Chroma
from langchain_core.documents import Document

from veridex.config import settings
from veridex.rag.embeddings import get_embeddings

_store_lock = Lock()
_stores: dict[tuple, Chroma] = {}
_index_identities: dict[Path, tuple] = {}


def _index_identity(index_dir: Path) -> tuple:
    """Detect deletion/replacement, without treating normal database writes as replacement."""
    identities = []
    for path in (index_dir, index_dir / "chroma.sqlite3"):
        try:
            stat = path.stat()
            identities.append((stat.st_dev, stat.st_ino))
        except FileNotFoundError:
            identities.append(None)
    return tuple(identities)


def assert_index_not_in_use(index_dir: Path) -> None:
    """Disk rebuilds must run in a fresh process, before Chroma has been opened.

    Dropping our cache alone would leave Chroma's own shared system alive.
    This guard does not coordinate with other processes; stop readers before rebuilding.
    """
    with _store_lock:
        if index_dir.resolve() in _index_identities:
            raise RuntimeError("Index already opened in this process; rebuild in a fresh process.")


def get_vector_store() -> Chroma:
    """Reuse a fully initialized store per configuration, with serialized startup."""
    with _store_lock:
        index_dir = Path(settings.chroma_persist_dir).resolve()
        key = (
            index_dir,
            settings.chroma_collection,
            settings.openai_embedding_model,
            settings.openai_api_key,
        )
        if (
            index_dir in _index_identities
            and _index_identity(index_dir) != _index_identities[index_dir]
        ):
            raise RuntimeError("Index was deleted or replaced; restart before accessing it again.")

        if key not in _stores:
            store = Chroma(
                collection_name=settings.chroma_collection,
                embedding_function=get_embeddings(),
                persist_directory=str(index_dir),
            )
            # Publish only after construction succeeds. Keep old configurations alive
            # so switching does not close a client still used by another retrieval.
            _stores[key] = store
            _index_identities[index_dir] = _index_identity(index_dir)
        return _stores[key]


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
