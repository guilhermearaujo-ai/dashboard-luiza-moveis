import plotly.graph_objects as go
import streamlit as st

from data.loader import build_roas_by_family
from data.meta import extract_skus_from_ad_name

NOXER_BLUE  = "#005CFE"
AMBER       = "#F59E0B"
SKY         = "#0EA5E9"
GREEN       = "#10B981"
GRID_COLOR  = "rgba(229,231,235,0.45)"
TRANSPARENT = "rgba(0,0,0,0)"


def _base_layout(**kwargs):
    base = dict(
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        font=dict(family="Inter, sans-serif"),
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis=dict(showgrid=False, zeroline=False,
                   tickfont=dict(size=11, color="#9CA3AF")),
        yaxis=dict(showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
                   tickfont=dict(size=11, color="#9CA3AF")),
    )
    base.update(kwargs)
    return base


def _build_sku_performance(df) -> "pd.DataFrame":
    """
    Cruza custo dos anúncios (Stract) com receita por SKU nos pedidos
    'WhatsApp - Meta Ads' (Bling).
    """
    import pandas as pd

    df_meta = df[df["campaign_name"] != "Bling Direto"][["ad_name", "spend"]].copy()
    df_meta["skus"] = df_meta["ad_name"].apply(extract_skus_from_ad_name)
    df_meta = df_meta[df_meta["skus"].apply(len) > 0].copy()

    if df_meta.empty:
        return pd.DataFrame()

    df_meta = df_meta.explode("skus").rename(columns={"skus": "sku"})
    meta_by_sku = (
        df_meta.groupby("sku", as_index=False)
        .agg(custo=("spend", "sum"))
    )

    result = meta_by_sku.copy()
    result["receita"] = 0.0

    if "loja" in df.columns and "sku" in df.columns:
        df_trafico = df[
            (df["campaign_name"] == "Bling Direto") &
            (df["loja"].str.contains("whatsapp|meta", case=False, na=False)) &
            (df["sku"].astype(str) != "")
        ][["sku", "total_price"]].copy()

        if not df_trafico.empty:
            bling_by_sku = (
                df_trafico.groupby("sku", as_index=False)
                .agg(receita=("total_price", "sum"))
            )
            result = pd.merge(meta_by_sku, bling_by_sku, on="sku", how="outer").fillna(0.0)

    result["roas"] = (
        result["receita"] / result["custo"].replace(0.0, float("nan"))
    ).fillna(0.0).round(2)

    return result.sort_values("receita", ascending=False).reset_index(drop=True)


def show(df):
    st.markdown("## Visão Geral")
    st.caption("Performance consolidada de Tráfego Pago + Vendas (Bling)")
    st.markdown("")

    # ── Seletor de Visão ──────────────────────────────────────────────────────
    view_mode = st.radio(
        "Visão:",
        ["Visão Global", "Visão Tráfego (Meta Ads)"],
        horizontal=True,
        key="dashboard_view_mode",
        label_visibility="collapsed",
    )
    st.markdown("")

    # ── Linhas Bling Direto (fonte de faturamento) ────────────────────────────
    df_bling = df[df["campaign_name"] == "Bling Direto"].copy()

    # DEBUG PERMANENTE — lista de lojas únicas vindas do Bling
    st.sidebar.subheader("DEBUG: Lojas no Bling")
    st.sidebar.write(df_bling["loja"].unique().tolist())

    # DEBUG: JSON bruto do pedido 13995 para mapear campo 'loja' correto
    import json as _json, os as _os
    _cache_path = "data/bling_cache.json"
    if _os.path.exists(_cache_path):
        try:
            with open(_cache_path) as _f:
                _raw_cache = _json.load(_f)
            _order_debug = None
            for _oid, _det in _raw_cache.items():
                if str(_det.get("numero", "")) == "13995":
                    _order_debug = {"_cache_key": _oid, **_det}
                    break
            if _order_debug:
                st.sidebar.subheader("DEBUG: Pedido 13995 (JSON bruto)")
                st.sidebar.json(_order_debug)
            else:
                st.sidebar.warning("Pedido 13995 não encontrado no cache — filtre o período que o inclua.")
        except Exception as _e:
            st.sidebar.error(f"Erro ao ler cache Bling: {_e}")
    else:
        st.sidebar.warning("Cache Bling não encontrado (data/bling_cache.json).")

    if df_bling.empty:
        st.info(
            "Sem dados de faturamento do Bling no período selecionado.  \n"
            "Verifique a conexão ou aguarde o carregamento dos pedidos."
        )

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_spend = float(df["spend"].sum())
    total_leads = float(df["leads"].sum())
    cpl         = total_spend / total_leads if total_leads else 0.0

    if view_mode == "Visão Global":
        total_revenue = float(df_bling["total_price"].sum()) if not df_bling.empty else 0.0
        total_units   = float(df_bling["quantity"].sum())    if not df_bling.empty else 0.0
    else:
        if not df_bling.empty and "loja" in df_bling.columns:
            df_trafico = df_bling[df_bling["loja"].str.contains("whatsapp|meta", case=False, na=False)]
            total_revenue = float(df_trafico["total_price"].sum())
            total_units   = float(df_trafico["quantity"].sum())
        else:
            total_revenue = 0.0
            total_units   = 0.0

    roas       = total_revenue / total_spend if total_spend  else 0.0
    avg_ticket = total_revenue / total_units if total_units  else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Investimento Total", "R$ {:,.0f}".format(total_spend))
    c2.metric("Faturamento Total",  "R$ {:,.0f}".format(total_revenue))
    c3.metric("ROAS",               "{:.2f}x".format(roas))
    c4.metric("CPL",                "R$ {:,.2f}".format(cpl))
    c5.metric("Ticket Médio",       "R$ {:,.0f}".format(avg_ticket))

    st.markdown("---")

    # ── Gráfico: Faturamento, Investimento, Leads e CPL Diário ───────────────
    df_meta_rows = df[df["campaign_name"] != "Bling Direto"]

    daily_meta = (
        df_meta_rows.groupby("date")
        .agg(spend=("spend", "sum"), leads=("leads", "sum"))
        .reset_index()
    )

    if not df_bling.empty:
        if view_mode == "Visão Global":
            daily_rev = (
                df_bling.groupby("date")["total_price"]
                .sum().reset_index().rename(columns={"total_price": "revenue"})
            )
        else:
            _df_t = (
                df_bling[df_bling["loja"].str.contains("whatsapp|meta", case=False, na=False)]
                if "loja" in df_bling.columns
                else df_bling.iloc[0:0]
            )
            daily_rev = (
                _df_t.groupby("date")["total_price"]
                .sum().reset_index().rename(columns={"total_price": "revenue"})
            )
        daily = daily_meta.merge(daily_rev, on="date", how="left")
    else:
        daily = daily_meta.copy()
        daily["revenue"] = 0.0

    daily = daily.sort_values("date")
    daily["revenue"] = daily["revenue"].fillna(0.0)
    daily["spend"]   = daily["spend"].fillna(0.0)
    daily["leads"]   = daily["leads"].fillna(0.0)
    daily["cpl"]     = (daily["spend"] / daily["leads"].replace(0, float("nan"))).fillna(0.0)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["revenue"],
        name="Faturamento",
        mode="lines",
        line=dict(color=NOXER_BLUE, width=3, shape="spline", smoothing=0.8),
        fill="tozeroy",
        fillcolor="rgba(0,92,254,0.08)",
        hovertemplate="%{x|%d/%m}: R$ %{y:,.0f}<extra>Faturamento</extra>",
        yaxis="y1",
    ))

    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["spend"],
        name="Investimento",
        mode="lines",
        line=dict(color=AMBER, width=2, dash="dot", shape="spline", smoothing=0.8),
        hovertemplate="%{x|%d/%m}: R$ %{y:,.0f}<extra>Investimento</extra>",
        yaxis="y1",
    ))

    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["leads"],
        name="Leads",
        mode="lines+markers",
        line=dict(color=GREEN, width=2, shape="spline", smoothing=0.8),
        marker=dict(size=4),
        hovertemplate="%{x|%d/%m}: %{y:.0f} leads<extra>Leads</extra>",
        yaxis="y2",
    ))

    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["cpl"],
        name="CPL",
        mode="lines+markers",
        line=dict(color=SKY, width=2, shape="spline", smoothing=0.8),
        marker=dict(size=4),
        hovertemplate="%{x|%d/%m}: R$ %{y:.2f}<extra>CPL</extra>",
        yaxis="y3",
    ))

    fig.update_layout(
        **_base_layout(
            title=dict(text="Faturamento, Investimento, Leads e CPL — Visão Diária",
                       font=dict(size=14, color="#111827"), x=0.01),
            height=420,
            margin=dict(l=20, r=80, t=55, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", y=1.12, x=1, xanchor="right",
                        font=dict(size=12, color="#6B7280")),
            xaxis=dict(showgrid=False, zeroline=False,
                       tickfont=dict(size=10, color="#9CA3AF")),
            yaxis=dict(
                title="R$ (Faturamento / Investimento)",
                showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
                tickfont=dict(size=10, color="#9CA3AF"),
                tickprefix="R$ ", tickformat=",.0f",
            ),
            yaxis2=dict(
                title="Leads",
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                tickfont=dict(size=10, color=GREEN),
            ),
            yaxis3=dict(
                overlaying="y", side="right",
                anchor="free", position=1.0,
                showgrid=False, zeroline=False, visible=False,
            ),
        )
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Resumo por campanha ───────────────────────────────────────────────────
    st.markdown("#### Resumo por Campanha")
    camp = (
        df.groupby("campaign_name")
        .agg(Gasto=("spend", "sum"), Leads=("leads", "sum"),
             Faturamento=("total_price", "sum"))
        .reset_index()
        .rename(columns={"campaign_name": "Campanha"})
    )
    for col in ["Gasto", "Leads", "Faturamento"]:
        camp[col] = camp[col].astype(float).fillna(0.0)
    camp["ROAS"] = (camp["Faturamento"] / camp["Gasto"].replace(0.0, float("nan"))).fillna(0.0).round(2)
    camp["CPL"]  = (camp["Gasto"] / camp["Leads"].replace(0.0, float("nan"))).fillna(0.0).round(2)
    st.dataframe(
        camp.style.format({
            "Gasto":       "R$ {:,.0f}",
            "Leads":       "{:,.0f}",
            "Faturamento": "R$ {:,.0f}",
            "CPL":         "R$ {:,.2f}",
            "ROAS":        "{:.2f}x",
        }),
        use_container_width=True, hide_index=True,
    )

    # ── Tabela Mestra de ROAS por Produto ─────────────────────────────────────
    st.markdown("#### Performance e ROAS por Produto (Meta Ads vs Bling)")

    if df_bling.empty:
        st.info("Nenhum dado de produto encontrado. Verifique a conexão com o Bling.")
        return

    prod = build_roas_by_family(df)

    if prod.empty:
        st.info("Nenhum produto com dados suficientes para exibir.")
        return

    tbl = prod[[
        "produto", "investimento", "leads", "cpl",
        "unidades", "tx_conversao", "ticket_medio", "faturamento", "roas",
    ]].copy()

    for col in ["investimento", "leads", "cpl", "unidades",
                "tx_conversao", "ticket_medio", "faturamento", "roas"]:
        tbl[col] = tbl[col].astype(float).fillna(0.0)

    tbl = tbl.rename(columns={
        "produto":      "Produto",
        "investimento": "Investimento",
        "leads":        "Leads",
        "cpl":          "CPL",
        "unidades":     "Vendas",
        "tx_conversao": "Tx. Conversão",
        "ticket_medio": "Ticket Médio",
        "faturamento":  "Faturamento",
        "roas":         "ROAS",
    })

    st.dataframe(
        tbl.style.format({
            "Investimento":  "R$ {:,.0f}",
            "Leads":         "{:,.0f}",
            "CPL":           "R$ {:,.2f}",
            "Vendas":        "{:,.0f}",
            "Tx. Conversão": "{:.1f}%",
            "Ticket Médio":  "R$ {:,.0f}",
            "Faturamento":   "R$ {:,.0f}",
            "ROAS":          "{:.2f}x",
        }),
        use_container_width=True, hide_index=True,
    )

    # ── Performance por SKU (Tráfego) ─────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Performance por SKU (Tráfego)")
    st.caption(
        "Custo do anúncio (Stract) × Receita dos SKUs nos pedidos "
        "**WhatsApp - Meta Ads** (Bling)  ·  Padrão: `ID_CATEGORIA_NOME_SKU1-SKU2`"
    )

    df_sku = _build_sku_performance(df)

    if df_sku.empty:
        st.info(
            "Nenhum SKU identificado nos nomes dos anúncios ou sem vendas "
            "de tráfego no período selecionado."
        )
    else:
        tbl_sku = df_sku.rename(columns={
            "sku":     "SKU",
            "custo":   "Custo (Stract)",
            "receita": "Receita (Bling)",
            "roas":    "ROAS",
        })
        st.dataframe(
            tbl_sku.style.format({
                "Custo (Stract)":  "R$ {:,.0f}",
                "Receita (Bling)": "R$ {:,.0f}",
                "ROAS":            "{:.2f}x",
            }),
            use_container_width=True, hide_index=True,
        )
