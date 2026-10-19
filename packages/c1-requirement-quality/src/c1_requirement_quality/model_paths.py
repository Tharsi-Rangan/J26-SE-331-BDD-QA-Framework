"""Stable model-path and Hugging Face cache resolution for local ML components."""
from __future__ import annotations

import os
from pathlib import Path

MINILM_CACHED_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DEBERTA_NLI_MODEL_NAME = "cross-encoder/nli-deberta-v3-small"
DEBERTA_NLI_CACHED_REVISION = "fa2804872c3b4bd748f38c0185cc85775361e735"


def get_package_root() -> Path:
    """Return the root directory of the c1-requirement-quality package."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "c1_requirement_quality").is_dir():
            return parent
    return Path(__file__).resolve().parents[2]


def get_models_dir() -> Path:
    """Return the local models/ directory inside c1-requirement-quality."""
    env_dir = os.environ.get("C1_MODELS_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
    return get_package_root() / "models"


def get_distilbert_model_dir() -> Path:
    """Return the directory containing the local DistilBERT defect classifier checkpoint."""
    return get_models_dir() / "distilbert-requirement-defects"


def get_hf_hub_cache_dir() -> Path:
    """Return the active Hugging Face hub cache directory."""
    hub_env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub_env:
        return Path(hub_env)
    home_env = os.environ.get("HF_HOME")
    if home_env:
        return Path(home_env) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def get_minilm_cache_dir() -> Path:
    """Select the known cached all-MiniLM-L6-v2 snapshot without hub resolution or network."""
    primary = get_hf_hub_cache_dir() / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / MINILM_CACHED_REVISION
    if primary.is_dir():
        return primary

    repo_cache = get_package_root().parent.parent / ".pytest-tmp" / "hf-cache" / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / MINILM_CACHED_REVISION
    if repo_cache.is_dir():
        return repo_cache

    return primary


def get_deberta_nli_cache_dir() -> Path | None:
    """Return the cached DeBERTa NLI snapshot directory if available."""
    primary = get_hf_hub_cache_dir() / "models--cross-encoder--nli-deberta-v3-small" / "snapshots" / DEBERTA_NLI_CACHED_REVISION
    if primary.is_dir():
        return primary

    local_model = get_models_dir() / "cross-encoder-nli-deberta-v3-small"
    if local_model.is_dir():
        return local_model

    repo_cache = get_package_root().parent.parent / ".pytest-tmp" / "hf-cache" / "hub" / "models--cross-encoder--nli-deberta-v3-small" / "snapshots" / DEBERTA_NLI_CACHED_REVISION
    if repo_cache.is_dir():
        return repo_cache

    return None
