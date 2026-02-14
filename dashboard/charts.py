from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def latency_line_chart(df: pd.DataFrame) -> go.Figure:
    """Time-series line chart of wall-clock latency per model."""
    if df.empty:
        return _empty_figure("No latency data available")

    success = df[df["status"] == "success"].copy()
    if success.empty:
        return _empty_figure("No successful probes to chart")

    success["timestamp"] = pd.to_datetime(success["timestamp"])

    fig = px.line(
        success,
        x="timestamp",
        y="wall_clock_ms",
        color="model_name",
        markers=True,
        labels={
            "timestamp": "Time",
            "wall_clock_ms": "Wall Clock Latency (ms)",
            "model_name": "Model",
        },
    )
    fig.update_layout(
        title="Response Latency Over Time",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def token_bar_chart(df: pd.DataFrame) -> go.Figure:
    """Grouped bar chart of average input/output tokens per model."""
    if df.empty:
        return _empty_figure("No token data available")

    success = df[df["status"] == "success"]
    if success.empty:
        return _empty_figure("No successful probes to chart")

    agg = success.groupby("model_name").agg(
        avg_input=("input_tokens", "mean"),
        avg_output=("output_tokens", "mean"),
    ).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Input Tokens",
        x=agg["model_name"],
        y=agg["avg_input"],
        marker_color="#636EFA",
    ))
    fig.add_trace(go.Bar(
        name="Output Tokens",
        x=agg["model_name"],
        y=agg["avg_output"],
        marker_color="#EF553B",
    ))
    fig.update_layout(
        title="Average Token Usage by Model",
        barmode="group",
        xaxis_title="Model",
        yaxis_title="Tokens",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def latency_comparison_chart(df: pd.DataFrame) -> go.Figure:
    """Grouped bar chart comparing server latency vs wall-clock latency per model."""
    if df.empty:
        return _empty_figure("No latency data available")

    success = df[df["status"] == "success"]
    if success.empty:
        return _empty_figure("No successful probes to chart")

    agg = success.groupby("model_name").agg(
        avg_wall=("wall_clock_ms", "mean"),
        avg_server=("server_latency_ms", "mean"),
    ).reset_index()

    agg["network_overhead"] = agg["avg_wall"] - agg["avg_server"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Server Latency",
        x=agg["model_name"],
        y=agg["avg_server"],
        marker_color="#636EFA",
    ))
    fig.add_trace(go.Bar(
        name="Network Overhead",
        x=agg["model_name"],
        y=agg["network_overhead"],
        marker_color="#FFA15A",
    ))
    fig.update_layout(
        title="Server Latency vs Network Overhead",
        barmode="stack",
        xaxis_title="Model",
        yaxis_title="Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def model_summary_table(summary_df: pd.DataFrame) -> go.Figure:
    """Formatted table of per-model summary statistics."""
    if summary_df.empty:
        return _empty_figure("No summary data available")

    display = summary_df.copy()

    fmt_cols = {
        "avg_wall_clock_ms": "Avg Latency (ms)",
        "p50_wall_clock_ms": "p50 (ms)",
        "p95_wall_clock_ms": "p95 (ms)",
        "p99_wall_clock_ms": "p99 (ms)",
        "avg_input_tokens": "Avg In Tokens",
        "avg_output_tokens": "Avg Out Tokens",
        "error_rate": "Error Rate",
    }

    header_values = ["Model"] + list(fmt_cols.values())
    cell_values = [display["model_name"].tolist()]

    for col, _ in fmt_cols.items():
        vals = display[col].tolist()
        if col == "error_rate":
            cell_values.append([f"{v:.1%}" if v is not None else "N/A" for v in vals])
        else:
            cell_values.append([f"{v:,.0f}" if v is not None else "N/A" for v in vals])

    fig = go.Figure(data=[go.Table(
        header=dict(values=header_values, fill_color="#3366CC", font=dict(color="white", size=12), align="left"),
        cells=dict(values=cell_values, fill_color="lavender", align="left"),
    )])
    fig.update_layout(title="Model Comparison Summary", margin=dict(l=0, r=0, t=40, b=0))
    return fig


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=16))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig
