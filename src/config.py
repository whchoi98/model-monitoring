from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelConfig:
    id: str
    name: str


@dataclass
class ProbingConfig:
    interval_seconds: int = 300
    max_tokens: int = 256
    temperature: float = 0.1
    prompts: list[str] = field(default_factory=lambda: [
        "Explain what cloud computing is in 2-3 sentences.",
        "What is 15 multiplied by 27?",
    ])


@dataclass
class AppConfig:
    aws_region: str = "us-east-1"
    models: list[ModelConfig] = field(default_factory=list)
    probing: ProbingConfig = field(default_factory=ProbingConfig)
    db_path: str = "monitoring.db"


_DEFAULT_MODELS = [
    ModelConfig("us.anthropic.claude-opus-4-5-20251101-v1:0", "Claude Opus 4.5"),
    ModelConfig("us.anthropic.claude-opus-4-6-v1", "Claude Opus 4.6"),
    ModelConfig("us.anthropic.claude-sonnet-4-5-20250929-v1:0", "Claude Sonnet 4.5"),
    ModelConfig("us.amazon.nova-2-lite-v1:0", "Nova 2.0 Lite"),
]


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load configuration from a YAML file. Falls back to defaults if missing."""
    path = Path(path)
    if not path.exists():
        return AppConfig(models=list(_DEFAULT_MODELS))

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    aws_region = raw.get("aws", {}).get("region", "us-east-1")

    models_raw = raw.get("models", [])
    models = [ModelConfig(id=m["id"], name=m["name"]) for m in models_raw] if models_raw else list(_DEFAULT_MODELS)

    probing_raw = raw.get("probing", {})
    probing = ProbingConfig(
        interval_seconds=probing_raw.get("interval_seconds", 300),
        max_tokens=probing_raw.get("max_tokens", 256),
        temperature=probing_raw.get("temperature", 0.1),
        prompts=probing_raw.get("prompts", ProbingConfig().prompts),
    )

    db_path = raw.get("db", {}).get("path", "monitoring.db")

    return AppConfig(
        aws_region=aws_region,
        models=models,
        probing=probing,
        db_path=db_path,
    )
