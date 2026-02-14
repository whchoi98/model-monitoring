from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from src.config import load_config
from src.db import Database
from src.metrics import compute_model_summary
from dashboard.charts import (
    latency_comparison_chart,
    latency_line_chart,
    model_summary_table,
    token_bar_chart,
)

st.set_page_config(page_title="Bedrock Model Monitor", page_icon=":bar_chart:", layout="wide")


@st.cache_resource
def get_db() -> Database:
    config = load_config()
    return Database(config.db_path)


def main() -> None:
    st.title("Bedrock Model Monitoring Dashboard")

    db = get_db()

    # --- Sidebar ---
    st.sidebar.header("Filters")

    time_range = st.sidebar.selectbox(
        "Time Range",
        options=["1h", "6h", "24h", "7d", "30d", "Custom"],
        index=2,
    )

    now = datetime.now(timezone.utc)
    if time_range == "Custom":
        start_date = st.sidebar.date_input("Start date", value=now.date() - timedelta(days=1))
        end_date = st.sidebar.date_input("End date", value=now.date())
        start_time = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        end_time = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).isoformat()
    else:
        delta_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}
        hours = delta_map[time_range]
        start_time = (now - timedelta(hours=hours)).isoformat()
        end_time = now.isoformat()

    all_models = db.get_all_models()
    model_names = {m["model_id"]: m["model_name"] for m in all_models}

    selected_models = st.sidebar.multiselect(
        "Models",
        options=list(model_names.keys()),
        default=list(model_names.keys()),
        format_func=lambda mid: model_names.get(mid, mid),
    )

    auto_refresh = st.sidebar.toggle("Auto Refresh (60s)", value=False)
    if auto_refresh:
        st.sidebar.caption("Page refreshes every 60 seconds")
        st.cache_data.clear()
        import time
        # Streamlit will rerun when this expires
        st.empty()
        _auto_refresh_placeholder = st.sidebar.empty()

    # --- Load Data ---
    results = db.get_results(start_time=start_time, end_time=end_time)
    df = pd.DataFrame(results)

    if not df.empty and selected_models:
        df = df[df["model_id"].isin(selected_models)]

    # --- Latest Status Cards ---
    st.subheader("Latest Probe Status")
    latest = db.get_latest_results()

    if latest:
        cols = st.columns(min(len(latest), 6))
        for i, row in enumerate(latest):
            if selected_models and row["model_id"] not in selected_models:
                continue
            with cols[i % len(cols)]:
                status_icon = "OK" if row["status"] == "success" else "ERR"
                st.metric(
                    label=row["model_name"],
                    value=f"{row['wall_clock_ms']:,.0f} ms" if row["wall_clock_ms"] else "N/A",
                    delta=f"{status_icon} | In:{row.get('input_tokens', 'N/A')} Out:{row.get('output_tokens', 'N/A')}",
                    delta_color="normal" if row["status"] == "success" else "inverse",
                )
    else:
        st.info("No probe data yet. Run the prober first: `python3 run_prober.py --once`")

    if df.empty:
        st.warning("No data found for the selected time range and models.")
        if auto_refresh:
            import time as _time
            _time.sleep(60)
            st.rerun()
        return

    # --- Model Comparison Table ---
    st.subheader("Model Comparison")
    summary = compute_model_summary(df)
    st.plotly_chart(model_summary_table(summary), use_container_width=True)

    # --- Latency Chart ---
    st.subheader("Response Latency Over Time")
    st.plotly_chart(latency_line_chart(df), use_container_width=True)

    # --- Token Usage Chart ---
    st.subheader("Token Usage")
    st.plotly_chart(token_bar_chart(df), use_container_width=True)

    # --- Server vs Client Latency ---
    st.subheader("Server Latency vs Network Overhead")
    st.plotly_chart(latency_comparison_chart(df), use_container_width=True)

    # --- Raw Data ---
    with st.expander("Raw Data"):
        st.dataframe(df, use_container_width=True)

    if auto_refresh:
        import time as _time
        _time.sleep(60)
        st.rerun()


if __name__ == "__main__":
    main()
