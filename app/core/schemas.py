"""JSON schemas for Gemini ``response_json_schema`` constrained decoding.

Each schema is a plain dict (JSON Schema draft compatible) that Gemini uses to
enforce the *structure* of its output at the token-generation level.  The
schemas are intentionally loose on ``additionalProperties`` so that dynamically
keyed maps (metric_summaries, pillar_summaries) are accepted.
"""

from __future__ import annotations

# ── Insight schema ────────────────────────────────────────────────────────────

INSIGHT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "theme": {"type": "string"},
        "headline": {"type": "string"},
        "description": {"type": "string"},
        "cta": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["text", "action"],
        },
    },
    "required": ["theme", "headline", "description", "cta"],
}

# ── Single-pillar (split) summary schema ──────────────────────────────────────

PILLAR_SUMMARY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "metric_summaries": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "metric_summaries_ui": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "pillar_summary": {"type": "string"},
    },
    "required": ["metric_summaries", "metric_summaries_ui", "pillar_summary"],
}

# ── Synthesis (overall_summary) schema ────────────────────────────────────────

SYNTHESIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "overall_summary": {
            "type": "object",
            "properties": {
                "overview": {"type": "string"},
                "whats_going_well": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "whats_needs_attention": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["overview", "whats_going_well", "whats_needs_attention"],
        },
    },
    "required": ["overall_summary"],
}

# ── Monolithic summary schema (all pillars in one call) ──────────────────────

MONOLITHIC_SUMMARY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "metric_summaries": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "metric_summaries_ui": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "pillar_summaries": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "overall_summary": {
            "type": "object",
            "properties": {
                "overview": {"type": "string"},
                "whats_going_well": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "whats_needs_attention": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["overview", "whats_going_well", "whats_needs_attention"],
        },
    },
    "required": [
        "metric_summaries",
        "metric_summaries_ui",
        "pillar_summaries",
        "overall_summary",
    ],
}
