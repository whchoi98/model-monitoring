from __future__ import annotations

import numpy as np
import pandas as pd


def compute_stats(df: pd.DataFrame, column: str) -> dict:
    """Compute summary statistics for a numeric column."""
    series = df[column].dropna()
    if series.empty:
        return {"avg": None, "p50": None, "p95": None, "p99": None, "min": None, "max": None}

    return {
        "avg": float(series.mean()),
        "p50": float(series.quantile(0.50)),
        "p95": float(series.quantile(0.95)),
        "p99": float(series.quantile(0.99)),
        "min": float(series.min()),
        "max": float(series.max()),
    }


def compute_model_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-model summary statistics.

    Returns a DataFrame with one row per model containing latency stats,
    average token counts, and error rate.
    """
    if df.empty:
        return pd.DataFrame()

    rows = []
    for model_name, group in df.groupby("model_name"):
        total = len(group)
        errors = len(group[group["status"] == "error"])
        success = group[group["status"] == "success"]

        latency = compute_stats(success, "wall_clock_ms")
        server_latency = compute_stats(success, "server_latency_ms")

        rows.append({
            "model_name": model_name,
            "probe_count": total,
            "error_count": errors,
            "error_rate": errors / total if total > 0 else 0.0,
            "avg_wall_clock_ms": latency["avg"],
            "p50_wall_clock_ms": latency["p50"],
            "p95_wall_clock_ms": latency["p95"],
            "p99_wall_clock_ms": latency["p99"],
            "avg_server_latency_ms": server_latency["avg"],
            "p50_server_latency_ms": server_latency["p50"],
            "p95_server_latency_ms": server_latency["p95"],
            "p99_server_latency_ms": server_latency["p99"],
            "avg_input_tokens": float(success["input_tokens"].mean()) if not success.empty else None,
            "avg_output_tokens": float(success["output_tokens"].mean()) if not success.empty else None,
        })

    return pd.DataFrame(rows)
