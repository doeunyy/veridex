import sys

import chromadb
import fastapi
import langchain
import langgraph
import pytest

from veridex.config import Settings


def test_python_version():
    assert sys.version_info[:2] == (3, 13)


def test_core_dependencies():
    assert fastapi is not None
    assert langchain is not None
    assert langgraph is not None
    assert chromadb is not None
    assert pytest is not None


def test_settings():
    config = Settings(_env_file=None)
    assert config.app_env == "development"
    assert config.chroma_collection == "veridex_corpus_v3"
    assert (config.openai_model, config.gemini_model) == ("gpt-6.1-sol", "gemini-3.8-flash")
