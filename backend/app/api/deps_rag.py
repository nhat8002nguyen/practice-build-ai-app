from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.rag.embeddings import Embedder, build_embedder
from app.rag.store import QdrantStore, build_store
from app.services.llm import LLM, ConfiguredLLM


@lru_cache
def get_store() -> QdrantStore:
    return build_store()


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder()


@lru_cache
def get_llm() -> LLM:
    return ConfiguredLLM()


Store = Annotated[QdrantStore, Depends(get_store)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
LLMDep = Annotated[LLM, Depends(get_llm)]
