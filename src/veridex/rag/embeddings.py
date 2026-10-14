from langchain_openai import OpenAIEmbeddings

from veridex.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    """Create the embedding model used for indexing and retrieval."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
        request_timeout=settings.provider_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )
