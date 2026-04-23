"""Application configuration: loading, defaults, environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.core.logging import log_config_error, log_config_warning
from app.models.common import VALID_PILLARS

BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR.parent / "prompts" / "system"

_env_local = BASE_DIR / ".env"
_env_root = BASE_DIR.parent / ".env"
load_dotenv(_env_local if _env_local.exists() else _env_root, override=True)


def unlocked_pillars_from_metadata_types(types: list[str]) -> set[str]:
    """Map metadata.type to the set of pillars to unlock (only pillar names count)."""
    lowered = [t.lower() for t in types]
    pillars = {p for p in lowered if p in VALID_PILLARS}
    if not pillars:
        raise ValueError(
            "metadata.type must include at least one valid pillar name "
            f"({sorted(VALID_PILLARS)})"
        )
    return pillars


PILLAR_METRICS: dict[str, list[str]] = {
    "spending": ["spend_to_income_ratio", "saving_consistency", "emergency_corpus"],
    "borrowing": ["emi_burden", "credit_score"],
    "protection": ["life_insurance", "health_insurance"],
    "tax": ["tax_filing_status", "tax_savings"],
    "wealth": ["investment_rate", "portfolio_diversification", "portfolio_overlap"],
}

PILLAR_SCORES: dict[str, str] = {
    "spending": "spending_score",
    "borrowing": "borrowing_score",
    "protection": "protection_score",
    "tax": "tax_score",
    "wealth": "wealth_score",
}

_DEFAULTS: dict[str, Any] = {
    # Keys referenced directly via _DEFAULTS["key"] as inline fallbacks.
    # Everything else lives exclusively in config.yaml and is merged via
    # _load_config() -> cfg.setdefault(key, default).
    "prompt_file": "synthesis_overall.txt",
    "insight_system_prompt_file": "insight_system.txt",
    "temperature_summary": 0.3,
    "max_tokens_pillar": 4096,
    "max_tokens_synthesis": 4096,
    "max_tokens_summary": 16384,
    "gemini_model": "gemini-2.5-flash",
    "gemini_max_output_tokens": 16384,
    "gemini_vertex_project": "aigateway",
    "gemini_vertex_location": "global",
    "gemini_http_api_version": "v1",
    "llm_debug": False,
}


def prompt_file_from_config(cfg: dict[str, Any]) -> str:
    """Return the pillar-summary prompt filename from ``config.yaml`` (``prompt_file`` key)."""
    pf = cfg.get("prompt_file")
    if isinstance(pf, str) and pf.strip():
        return pf.strip()
    return _DEFAULTS["prompt_file"]


FIELD_TO_PILLAR: dict[str, str] = {
    "spend_to_income_history": "spending",
    "spend_history": "spending",
    "saving_consistency": "spending",
    "emergency_corpus": "spending",
    "ideal_emergency_corpus": "spending",
    "liquidity_buffer": "spending",
    "emi_burden_history": "borrowing",
    "monthly_emi": "borrowing",
    "credit_score_history": "borrowing",
    "life_cover_adequacy": "protection",
    "health_cover_adequacy": "protection",
    "tax_filing_status": "tax",
    "tax_saving_index": "tax",
    "tax_saving_index_availed": "tax",
    "tax_saving_index_possible": "tax",
    "investment_rate_pct": "wealth",
    "monthly_investment": "wealth",
    "portfolio_diversification": "wealth",
    "portfolio_overlap": "wealth",
}


# ── Config loading ───────────────────────────────────────────────────────────

_config: dict[str, Any] = {}


def _load_config() -> dict:
    """Load and merge config.yaml with _DEFAULTS and environment overrides."""
    cfg_path = BASE_DIR.parent / "config.yaml"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        log_config_error("config.yaml not found: %s", cfg_path)
        raise
    except yaml.YAMLError as exc:
        log_config_error("Invalid YAML in config.yaml: %s", exc)
        raise
    if raw is None:
        cfg: dict[str, Any] = {}
    elif isinstance(raw, dict):
        cfg = raw
    else:
        raise ValueError("config.yaml must contain a mapping at the top level")

    for key, default in _DEFAULTS.items():
        cfg.setdefault(key, default)

    # -- Environment-variable overrides (secrets & tunables) ------------------

    _g = os.environ.get("GEMINI_API_KEY") or os.environ.get("Gemini_API_KEY") or ""
    cfg["gemini_api_key"] = _g.strip() if isinstance(_g, str) else ""
    cfg["gemini_base_url"] = (os.environ.get("GEMINI_BASE_URL") or "").strip().rstrip("/")

    cfg["gemini_model"] = (
        os.environ.get("GEMINI_MODEL") or cfg["gemini_model"]
    ).strip()

    try:
        cfg["gemini_max_output_tokens"] = int(
            os.environ.get("GEMINI_MAX_OUTPUT_TOKENS") or cfg["gemini_max_output_tokens"]
        )
    except (TypeError, ValueError):
        cfg["gemini_max_output_tokens"] = _DEFAULTS["gemini_max_output_tokens"]

    cfg["gemini_vertex_project"] = (
        os.environ.get("GEMINI_VERTEX_PROJECT") or cfg["gemini_vertex_project"]
    ).strip()
    cfg["gemini_vertex_location"] = (
        os.environ.get("GEMINI_VERTEX_LOCATION") or cfg["gemini_vertex_location"]
    ).strip()

    _mt_env = (os.environ.get("MAX_TOKENS") or "").strip()
    if _mt_env:
        try:
            cfg["max_tokens"] = int(_mt_env)
        except ValueError:
            log_config_warning("Invalid MAX_TOKENS=%r; using max_tokens from config.yaml", _mt_env)

    _insight_env = (os.environ.get("INSIGHT_SYSTEM_PROMPT_FILE") or "").strip()
    if _insight_env:
        cfg["insight_system_prompt_file"] = _insight_env

    _debug_env = os.environ.get("LLM_DEBUG")
    if _debug_env is not None:
        cfg["llm_debug"] = _debug_env.strip().lower() in ("1", "true", "yes")

    _log_chars_env = os.environ.get("LOG_MAX_BODY_CHARS")
    if _log_chars_env is not None:
        try:
            cfg["log_max_body_chars"] = int(_log_chars_env)
        except ValueError:
            pass

    # -- Context caching env overrides ----------------------------------------
    _cache_env = (os.environ.get("ENABLE_CONTEXT_CACHE") or "").strip().lower()
    if _cache_env:
        cfg["enable_context_cache"] = _cache_env in ("1", "true", "yes")
    else:
        cfg.setdefault("enable_context_cache", False)

    _ttl_env = (os.environ.get("CONTEXT_CACHE_TTL") or "").strip()
    if _ttl_env:
        cfg["context_cache_ttl"] = _ttl_env
    else:
        cfg.setdefault("context_cache_ttl", "3600s")

    # -- Enabled insight pillars (env override: comma-separated) ---------------
    _eip_env = (os.environ.get("ENABLED_INSIGHT_PILLARS") or "").strip()
    if _eip_env:
        cfg["enabled_insight_pillars"] = [
            p.strip().lower() for p in _eip_env.split(",") if p.strip()
        ]
    else:
        raw_list = cfg.get("enabled_insight_pillars")
        if isinstance(raw_list, list):
            cfg["enabled_insight_pillars"] = [
                str(p).strip().lower() for p in raw_list if str(p).strip()
            ]
        else:
            cfg["enabled_insight_pillars"] = sorted(VALID_PILLARS)

    invalid_eip = set(cfg["enabled_insight_pillars"]) - VALID_PILLARS
    if invalid_eip:
        log_config_warning(
            "enabled_insight_pillars contains invalid pillar(s) %s — ignoring them", invalid_eip,
        )
        cfg["enabled_insight_pillars"] = [
            p for p in cfg["enabled_insight_pillars"] if p in VALID_PILLARS
        ]

    cfg["prompt_file"] = prompt_file_from_config(cfg)
    return cfg


def set_config(cfg: dict[str, Any]) -> None:
    """Replace the module-level config dict (called once at startup)."""
    global _config
    _config.clear()
    _config.update(cfg)


def get_config() -> dict[str, Any]:
    """Return the current module-level config dict."""
    return _config


def get_enabled_insight_pillars() -> frozenset[str]:
    """Return the set of pillar names enabled for insight computation."""
    cfg = get_config()
    return frozenset(cfg.get("enabled_insight_pillars", sorted(VALID_PILLARS)))


def _llm_debug_enabled() -> bool:
    cfg = get_config()
    if cfg:
        return bool(cfg.get("llm_debug", _DEFAULTS["llm_debug"]))
    return os.environ.get("LLM_DEBUG", "0").strip().lower() in ("1", "true", "yes")
