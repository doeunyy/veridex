"""Chat model construction for the two generation providers."""

from typing import Literal

from langchain_core.language_models import BaseChatModel

from veridex.config import Settings, settings

Provider = Literal["openai", "gemini"]
PROVIDERS: tuple[Provider, ...] = ("openai", "gemini")


class ProviderUnavailable(RuntimeError):
    """The provider has no credentials configured."""


def model_id(provider: Provider, config: Settings | None = None) -> str:
    config = config or settings
    return config.openai_model if provider == "openai" else config.gemini_model


def is_configured(provider: Provider, config: Settings | None = None) -> bool:
    config = config or settings
    key = config.openai_api_key if provider == "openai" else config.google_api_key
    return bool(key and key.strip())


def create_chat_model(
    provider: Provider, config: Settings | None = None, *, thinking_budget: int | None = None
) -> BaseChatModel:
    """Build a bounded chat model; no request is sent here.

    Temperature is left at the provider default: the GPT-6 reasoning models reject
    any other value, and Gemini 3 recommends its default for reasoning quality.
    """
    config = config or settings
    if not is_configured(provider, config):
        raise ProviderUnavailable(f"{provider} is not configured.")
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.openai_model,
            api_key=config.openai_api_key,
            timeout=config.provider_timeout_seconds,
            max_retries=config.provider_max_retries,
            max_completion_tokens=config.agent_max_completion_tokens,
            stream_usage=True,
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    extra = {} if thinking_budget is None else {"thinking_budget": thinking_budget}
    return ChatGoogleGenerativeAI(
        model=config.gemini_model,
        google_api_key=config.google_api_key,
        timeout=config.provider_timeout_seconds,
        max_retries=config.provider_max_retries,
        max_output_tokens=config.agent_max_completion_tokens,
        **extra,
    )
