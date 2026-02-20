#!/usr/bin/env python3
"""
13F Dashboard
Interactive Streamlit app to visualise parsed 13F hedge-fund holdings.

Run with:
    streamlit run dashboard.py
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="13F Filing Explorer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

OUTPUT_DIR = Path("output")

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def load_all_funds(output_dir: Path) -> Dict[str, dict]:
    """Load every per-fund JSON file in output_dir."""
    funds = {}
    for p in sorted(output_dir.glob("*_13f.json")):
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        funds[data["fund_name"]] = data
    return funds


def flatten_holdings(funds: Dict[str, dict]) -> pd.DataFrame:
    """
    Expand all funds × quarters × holdings into a single flat DataFrame.
    Exited positions (value_usd == 0) are excluded from the main table
    but kept with a 'change_type == exited' flag if you want them.
    """
    rows = []
    for fund_name, fund_data in funds.items():
        for filing in fund_data.get("filings", []):
            period = filing["period"]
            period_date = filing["period_of_report"]
            total_val = filing["total_value_usd"]
            for h in filing.get("holdings", []):
                rows.append(
                    {
                        "fund": fund_name,
                        "period": period,
                        "period_date": pd.to_datetime(period_date),
                        "total_portfolio_usd": total_val,
                        "name": h["name"],
                        "cusip": h["cusip"],
                        "shares": h["shares"],
                        "value_usd": h["value_usd"],
                        "pct_portfolio": h["pct_portfolio"],
                        "change_type": h.get("change_type", "unknown"),
                        "share_change": h.get("share_change"),
                        "share_change_pct": h.get("share_change_pct"),
                        "value_change_usd": h.get("value_change_usd"),
                        "put_call": h.get("put_call", ""),
                    }
                )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.sort_values(["fund", "period_date", "value_usd"], ascending=[True, True, False], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def portfolio_over_time(funds: Dict[str, dict]) -> pd.DataFrame:
    rows = []
    for fund_name, fund_data in funds.items():
        for filing in fund_data.get("filings", []):
            rows.append(
                {
                    "fund": fund_name,
                    "period": filing["period"],
                    "period_date": pd.to_datetime(filing["period_of_report"]),
                    "total_value_usd": filing["total_value_usd"],
                    "holdings_count": filing["holdings_count"],
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values(["fund", "period_date"])
    return df


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def sidebar(funds: Dict[str, dict]):
    st.sidebar.header("Filters")

    fund_names = sorted(funds.keys())
    selected_funds = st.sidebar.multiselect(
        "Funds", fund_names, default=fund_names[:5] if len(fund_names) >= 5 else fund_names
    )

    all_periods = sorted(
        {
            f["period"]
            for fd in funds.values()
            for f in fd.get("filings", [])
        }
    )
    if all_periods:
        period_range = st.sidebar.select_slider(
            "Period range",
            options=all_periods,
            value=(all_periods[0], all_periods[-1]),
        )
    else:
        period_range = (None, None)

    top_n = st.sidebar.slider("Top N holdings to show", min_value=5, max_value=50, value=15)

    return selected_funds, period_range, top_n


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------


def chart_portfolio_aum(df_time: pd.DataFrame):
    st.subheader("Portfolio AUM Over Time")
    fig = px.line(
        df_time,
        x="period_date",
        y="total_value_usd",
        color="fund",
        markers=True,
        labels={"total_value_usd": "Total Value (USD)", "period_date": "Quarter"},
        title="13F Reported AUM per Quarter",
    )
    fig.update_yaxes(tickformat="$,.0f")
    fig.update_layout(hovermode="x unified", legend_title_text="Fund")
    st.plotly_chart(fig, use_container_width=True)


def chart_holdings_count(df_time: pd.DataFrame):
    st.subheader("Number of Disclosed Positions Over Time")
    fig = px.line(
        df_time,
        x="period_date",
        y="holdings_count",
        color="fund",
        markers=True,
        labels={"holdings_count": "Number of Holdings", "period_date": "Quarter"},
    )
    fig.update_layout(hovermode="x unified", legend_title_text="Fund")
    st.plotly_chart(fig, use_container_width=True)


def chart_top_holdings(df: pd.DataFrame, fund: str, period: str, top_n: int):
    sub = df[(df["fund"] == fund) & (df["period"] == period) & (df["value_usd"] > 0)]
    sub = sub.nlargest(top_n, "value_usd")
    if sub.empty:
        st.info(f"No holdings data for {fund} / {period}.")
        return

    fig = px.bar(
        sub,
        x="pct_portfolio",
        y="name",
        orientation="h",
        color="change_type",
        color_discrete_map={
            "new": "#2ecc71",
            "increased": "#3498db",
            "unchanged": "#95a5a6",
            "decreased": "#e67e22",
            "exited": "#e74c3c",
            "unknown": "#bdc3c7",
        },
        labels={"pct_portfolio": "% of Portfolio", "name": "Security"},
        title=f"{fund} – Top {top_n} Holdings ({period})",
        hover_data=["value_usd", "shares", "change_type", "share_change_pct"],
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    fig.update_xaxes(ticksuffix="%")
    st.plotly_chart(fig, use_container_width=True)


def chart_portfolio_treemap(df: pd.DataFrame, fund: str, period: str, top_n: int):
    sub = df[(df["fund"] == fund) & (df["period"] == period) & (df["value_usd"] > 0)]
    sub = sub.nlargest(top_n, "value_usd").copy()
    if sub.empty:
        return
    sub["label"] = sub["name"] + "<br>" + sub["pct_portfolio"].map(lambda x: f"{x:.1f}%")
    fig = px.treemap(
        sub,
        path=["name"],
        values="value_usd",
        color="pct_portfolio",
        color_continuous_scale="Blues",
        title=f"{fund} – Portfolio Treemap ({period})",
        hover_data=["shares", "value_usd", "change_type"],
    )
    fig.update_traces(texttemplate="%{label}<br>%{customdata[2]}")
    st.plotly_chart(fig, use_container_width=True)


def chart_stock_across_funds(df: pd.DataFrame, stock_query: str):
    """Track how much each fund holds of a stock over time."""
    mask = df["name"].str.contains(stock_query, case=False, na=False)
    sub = df[mask & (df["value_usd"] > 0)]
    if sub.empty:
        st.warning(f"No matches for '{stock_query}'.")
        return

    fig = px.line(
        sub,
        x="period_date",
        y="value_usd",
        color="fund",
        markers=True,
        labels={"value_usd": "Market Value (USD)", "period_date": "Quarter"},
        title=f"'{stock_query}' – Holdings Across Funds Over Time",
    )
    fig.update_yaxes(tickformat="$,.0f")
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # Also show share counts
    fig2 = px.line(
        sub,
        x="period_date",
        y="pct_portfolio",
        color="fund",
        markers=True,
        labels={"pct_portfolio": "% of Portfolio", "period_date": "Quarter"},
        title=f"'{stock_query}' – % of Each Fund's Portfolio",
    )
    fig2.update_yaxes(ticksuffix="%")
    fig2.update_layout(hovermode="x unified")
    st.plotly_chart(fig2, use_container_width=True)


def chart_overlap_heatmap(df: pd.DataFrame, selected_funds: List[str], period: str, top_n: int):
    """
    Heatmap: selected funds × their top holdings. Value = % of portfolio.
    Shows what stocks multiple funds own simultaneously.
    """
    sub = df[(df["fund"].isin(selected_funds)) & (df["period"] == period) & (df["value_usd"] > 0)]
    # Pick the union of each fund's top-N positions
    top_stocks = (
        sub.groupby("fund")
        .apply(lambda g: g.nlargest(top_n, "value_usd")["name"])
        .explode()
        .unique()
    )
    sub = sub[sub["name"].isin(top_stocks)]
    pivot = sub.pivot_table(index="name", columns="fund", values="pct_portfolio", fill_value=0)

    if pivot.empty:
        st.info("No data for the selected filters.")
        return

    # Sort rows by total weight across funds
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    pivot = pivot.head(min(top_n * 2, 60))  # cap rows

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            colorscale="Blues",
            hoverongaps=False,
            colorbar_title="% Portfolio",
            text=pivot.values.round(1),
            texttemplate="%{text}%",
        )
    )
    fig.update_layout(
        title=f"Holdings Overlap – {period}",
        xaxis_title="Fund",
        yaxis_title="Security",
        height=max(400, len(pivot) * 20),
        yaxis={"autorange": "reversed"},
    )
    st.plotly_chart(fig, use_container_width=True)


def chart_changes_waterfall(df: pd.DataFrame, fund: str, period: str):
    """Bar chart of new/increased vs decreased/exited positions by value."""
    sub = df[(df["fund"] == fund) & (df["period"] == period)]
    if sub.empty:
        return

    buys = sub[sub["change_type"].isin(["new", "increased"])]["value_change_usd"].sum()
    sells = sub[sub["change_type"].isin(["decreased", "exited"])]["value_change_usd"].sum()

    categories = ["Added / Increased", "Reduced / Exited"]
    values = [buys, sells]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in values]

    fig = go.Figure(
        go.Bar(
            x=categories,
            y=values,
            marker_color=colors,
            text=[f"${v:,.0f}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title=f"{fund} – Quarter Changes ({period})",
        yaxis_title="Value Change (USD)",
        yaxis_tickformat="$,.0f",
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


def main():
    st.title("13F Filing Explorer")
    st.caption(
        "Parses SEC EDGAR 13F-HR filings for major hedge funds. "
        "Run `python parse_13f.py` first to generate the data."
    )

    if not OUTPUT_DIR.exists() or not any(OUTPUT_DIR.glob("*_13f.json")):
        st.error(
            f"No parsed data found in `{OUTPUT_DIR}/`. "
            "Run the parser first:\n\n"
            "```bash\npython parse_13f.py\n```"
        )
        st.stop()

    funds = load_all_funds(OUTPUT_DIR)
    df_all = flatten_holdings(funds)
    df_time = portfolio_over_time(funds)

    selected_funds, period_range, top_n = sidebar(funds)

    if not selected_funds:
        st.warning("Select at least one fund in the sidebar.")
        st.stop()

    # Apply filters
    if period_range[0] and period_range[1]:
        df_all = df_all[
            (df_all["period"] >= period_range[0]) & (df_all["period"] <= period_range[1])
        ]
        df_time = df_time[
            (df_time["period"] >= period_range[0]) & (df_time["period"] <= period_range[1])
        ]

    df_funds = df_all[df_all["fund"].isin(selected_funds)]
    df_time_funds = df_time[df_time["fund"].isin(selected_funds)]

    # ---- Tab layout -------------------------------------------------------
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📊 AUM & Positions", "🏦 Fund Deep-Dive", "🔍 Stock Tracker", "🗺 Overlap Heatmap", "📋 Raw Data"]
    )

    with tab1:
        chart_portfolio_aum(df_time_funds)
        chart_holdings_count(df_time_funds)

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            fund_sel = st.selectbox("Fund", selected_funds, key="dd_fund")
        with c2:
            periods_for_fund = sorted(
                df_funds[df_funds["fund"] == fund_sel]["period"].unique()
            )
            period_sel = st.selectbox(
                "Quarter", periods_for_fund, index=len(periods_for_fund) - 1 if periods_for_fund else 0, key="dd_period"
            )

        if fund_sel and period_sel:
            col1, col2 = st.columns(2)
            with col1:
                chart_top_holdings(df_funds, fund_sel, period_sel, top_n)
            with col2:
                chart_portfolio_treemap(df_funds, fund_sel, period_sel, top_n)
            chart_changes_waterfall(df_funds, fund_sel, period_sel)

    with tab3:
        stock_q = st.text_input("Search for a stock (partial name, e.g. 'Apple', 'MSFT', 'Meta')")
        if stock_q:
            chart_stock_across_funds(df_all[df_all["fund"].isin(selected_funds)], stock_q)
        else:
            st.info("Type a stock name above to track it across all selected funds.")

    with tab4:
        all_periods_for_heatmap = sorted(df_funds["period"].unique())
        if all_periods_for_heatmap:
            hm_period = st.selectbox(
                "Quarter for heatmap",
                all_periods_for_heatmap,
                index=len(all_periods_for_heatmap) - 1,
                key="hm_period",
            )
            chart_overlap_heatmap(df_funds, selected_funds, hm_period, top_n)
        else:
            st.info("No data available for selected filters.")

    with tab5:
        st.subheader("Holdings Data")
        display_cols = [
            "fund", "period", "name", "cusip", "value_usd", "shares",
            "pct_portfolio", "change_type", "share_change_pct",
        ]
        available_cols = [c for c in display_cols if c in df_funds.columns]
        show_exited = st.checkbox("Include exited positions", value=False)
        df_display = df_funds if show_exited else df_funds[df_funds["value_usd"] > 0]
        st.dataframe(
            df_display[available_cols].reset_index(drop=True),
            use_container_width=True,
            height=500,
        )
        csv = df_display[available_cols].to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, "13f_holdings.csv", "text/csv")


if __name__ == "__main__":
    main()
