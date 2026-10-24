"""Import RAGAS with the current langchain-community.

ragas 0.4.3 (the latest release) imports ``langchain_community.chat_models.vertexai``,
which langchain-community 0.4 removed. Veridex never uses Vertex AI through RAGAS, so a
placeholder class is registered for that one import before RAGAS loads.
"""

import importlib
import sys
import types

_MODULE = "langchain_community.chat_models.vertexai"


def import_ragas():
    try:
        importlib.import_module(_MODULE)
    except ModuleNotFoundError:
        shim = types.ModuleType(_MODULE)

        class ChatVertexAI:  # never instantiated; only used in isinstance checks
            pass

        shim.ChatVertexAI = ChatVertexAI
        sys.modules[_MODULE] = shim
    return importlib.import_module("ragas")
