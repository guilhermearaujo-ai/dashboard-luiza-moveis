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

    - Custo: soma do spend por SKU extraído do ad_name (padrão ID_CAT_NOME_SKUs)
    - Receita: soma do total_price por SKU nos pedidos da loja "WhatsApp - Meta Ads"
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

    # Bling: receita por SKU nos pedidos de tráfego
    if "loja" in df.columns and "sku" in df.columns:
        df_trafico = df[
            (df["campaign_name"] == "Bling Direto") &
            (df["loja"] == "WhatsApp - Meta Ads") &
            (df["sku"] != "")
        ][["sku", "total_price"]].copy()

        if not df_trafico.empty:
            bling_by_sku = (
                df_trafico.groupby("sku", as_index=False)
                .agg(receita=("total_price", "sum"))
            )
            result = pd.merge(meta_by_sku, bling_by_sku, on="sku", how="outer").fillna(0.0)
        else:
            result = meta_by_sku.copy()
            result["receita"] = 0.0
    else:
        result = meta_by_sku.copy()
        result["receita"] = 0.0

    result["roas"] = (
        result["receita"] / result["custo"].replace(0.0, float("nan"))
    ).fillna(0.0).round(2)

    return result.sort_values("receita", ascending=False).reset_index(drop=True)


def show(df):
    st.markdown("## Visão Geral")
    st.caption("Performance consolidada de Tráfego Pago + Vendas (Bling)")
    st.markdown("")

    # Proteção contra cache legado ou falha de merge
    if "bling_revenue_day" not in df.columns:
        df = df.copy()
        df["bling_revenue_day"] = 0.0
    if "bling_trafico_day" not in df.columns:
        df = df.copy()
        df["bling_trafico_day"] = 0.0

    # ── Seletor de Visão ──────────────────────────────────────────────────────
    view_mode = st.radio(
        "Visão:",
        ["Visão Global", "Visão Tráfego (Meta Ads)"],
        horizontal=True,
        key="dashboard_view_mode",
        label_visibility="collapsed",
    )
    st.markdown("")

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_spend = float(df["spend"].sum())
    total_leads = float(df["leads"].sum())
    cpl         = total_spend / total_leads if total_leads else 0.0

    if view_mode == "Visão Global":
        total_revenue = float(df.groupby("date")["bling_revenue_day"].max().sum())
        total_units   = float(df["quantity"].sum())
    else:
        total_revenue = float(df.groupby("date")["bling_trafico_day"].max().sum())
        if "loja" in df.columns:
            _trafico_mask = (
                (df["campaign_name"] == "Bling Direto") &
                (df["loja"] == "WhatsApp - Meta Ads")
            )
            total_units = float(df[_trafico_mask]["quantity"].sum())
        else:
            total_units = 0.0

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
    revenue_col = (
        "bling_trafico_day"
        if view_mode == "Visão Tráfego (Meta Ads)" and "bling_trafico_day" in df.columns
        else "bling_revenue_day"
    )

    daily = (
        df.groupby("date")
        .agg(
            spend=("spend",       "sum"),
            leads=("leads",       "sum"),
        )
        .reset_index()
        .sort_values("date")
    )
    # Agrega a coluna de receita correta separadamente para evitar erro de nome dinâmico
    daily_rev = (
        df.groupby("date")[revenue_col]
        .max()
        .reset_index()
        .rename(columns={revenue_col: "revenue"})
    )
    daily = daily.merge(daily_rev, on="date", how="left")
    daily["revenue"] = daily["revenue"].fillna(0.0)
    daily["cpl"] = (daily["spend"] / daily["leads"].replace(0, float("nan"))).fillna(0.0)

    fig = go.Figure()

    # Faturamento — Y1
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

    # Investimento — Y1
    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["spend"],
        name="Investimento",
        mode="lines",
        line=dict(color=AMBER, width=2, dash="dot", shape="spline", smoothing=0.8),
        hovertemplate="%{x|%d/%m}: R$ %{y:,.0f}<extra>Investimento</extra>",
        yaxis="y1",
    ))

    # Leads — Y2
    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["leads"],
        name="Leads",
        mode="lines+markers",
        line=dict(color=GREEN, width=2, shape="spline", smoothing=0.8),
        marker=dict(size=4),
        hovertemplate="%{x|%d/%m}: %{y:.0f} leads<extra>Leads</extra>",
        yaxis="y2",
    ))

    # CPL — Y3 (escala independente, eixo oculto)
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
            # Y1 — Faturamento / Investimento (R$)
            yaxis=dict(
                title="R$ (Faturamento / Investimento)",
                showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
                tickfont=dict(size=10, color="#9CA3AF"),
                tickprefix="R$ ", tickformat=",.0f",
            ),
            # Y2 — Leads (inteiros, eixo direito visível)
            yaxis2=dict(
                title="Leads",
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                tickfont=dict(size=10, color=GREEN),
            ),
            # Y3 — CPL (R$ pequeno, eixo oculto para não poluir)
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

    df_bling = df[df["campaign_name"] == "Bling Direto"]

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
        "**WhatsApp - Meta Ads** (Bling)  ·  Padrão de taxonomia: "
        "`ID_CATEGORIA_NOME_SKU1-SKU2`"
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
