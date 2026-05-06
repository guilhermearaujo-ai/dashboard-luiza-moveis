import plotly.graph_objects as go
import streamlit as st

# Noxer-aligned palette (primary blue first)
VEND_COLORS = ["#005CFE", "#0EA5E9", "#10B981", "#F59E0B", "#F43F5E"]
MEDALS      = ["🥇", "🥈", "🥉", "4°", "5°", "6°", "7°", "8°"]

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


def show(df):
    st.markdown("## Comercial")
    st.caption("Performance da equipe de vendas via WhatsApp")
    st.markdown("")

    # Linhas Bling Direto têm os dados reais de vendedor e pedido
    df_bling = df[df["campaign_name"] == "Bling Direto"].copy()
    df_meta  = df[df["campaign_name"] != "Bling Direto"].copy()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_leads  = int(df_meta["leads"].sum())
    total_rev    = df_bling["total_price"].sum()
    total_pedidos = df_bling["order_id"].nunique()          # pedidos únicos
    conv_rate    = total_pedidos / total_leads * 100 if total_leads else 0.0
    avg_ticket   = total_rev / total_pedidos if total_pedidos else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Leads Totais",      "{:,}".format(total_leads))
    c2.metric("Vendas Fechadas",   "{:,}".format(total_pedidos))
    c3.metric("Taxa de Conversão", "{:.1f}%".format(conv_rate))
    c4.metric("Ticket Médio",      "R$ {:,.0f}".format(avg_ticket))
    c5.metric("Faturamento",       "R$ {:,.0f}".format(total_rev))

    st.markdown("---")

    if df_bling.empty:
        st.info("Nenhum dado comercial encontrado. Verifique a conexão com o Bling.")
        return

    # ── Agregação por vendedor (pedidos únicos via order_id) ──────────────────
    df_vend = df_bling[df_bling["vendedor"].notna() & (df_bling["vendedor"] != "")]
    vend = (
        df_vend
        .groupby("vendedor")
        .agg(
            vendas=("order_id",    "nunique"),   # pedidos únicos por vendedor
            faturamento=("total_price", "sum"),
        )
        .reset_index()
        .sort_values("faturamento", ascending=False)
        .reset_index(drop=True)
    )
    vend["ticket_medio"] = (
        vend["faturamento"] / vend["vendas"].replace(0, float("nan"))
    ).fillna(0.0)
    vend["share"] = (vend["faturamento"] / vend["faturamento"].sum() * 100).round(1)
    vend["cor"]   = [VEND_COLORS[i % len(VEND_COLORS)] for i in range(len(vend))]

    col1, col2 = st.columns(2)

    # ── Barras: faturamento por vendedor ──────────────────────────────────────
    with col1:
        fig = go.Figure(go.Bar(
            x=vend["vendedor"],
            y=vend["faturamento"],
            marker_color=vend["cor"].tolist(),
            text=vend["faturamento"].apply("R$ {:,.0f}".format),
            textposition="outside",
            textfont=dict(size=11, color="#374151"),
            hovertemplate="<b>%{x}</b><br>R$ %{y:,.0f}<extra></extra>",
        ))
        fig.update_layout(
            **_base_layout(
                title=dict(text="Faturamento por Vendedor",
                           font=dict(size=14, color="#111827")),
                height=360,
                xaxis=dict(showgrid=False, zeroline=False,
                           tickfont=dict(size=11, color="#374151")),
                yaxis=dict(showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
                           tickfont=dict(size=11, color="#9CA3AF"),
                           tickprefix="R$ ", tickformat=",.0f"),
            )
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Donut: participação no faturamento ────────────────────────────────────
    with col2:
        fig2 = go.Figure(go.Pie(
            labels=vend["vendedor"],
            values=vend["faturamento"],
            hole=0.55,
            textinfo="label+percent",
            textfont=dict(size=12),
            marker=dict(colors=vend["cor"].tolist()),
            hovertemplate="<b>%{label}</b><br>R$ %{value:,.0f} (%{percent})<extra></extra>",
        ))
        fig2.update_layout(
            paper_bgcolor=TRANSPARENT,
            title=dict(text="Participação no Faturamento",
                       font=dict(size=14, color="#111827")),
            height=360,
            margin=dict(l=20, r=20, t=50, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    # ── Ranking de vendedores ─────────────────────────────────────────────────
    st.markdown("#### Ranking de Vendedores")
    rank = vend[["vendedor", "vendas", "faturamento", "ticket_medio", "share"]].copy()
    rank.insert(0, "Posicao", MEDALS[:len(rank)])
    rank = rank.rename(columns={
        "Posicao":      "Pos.",
        "vendedor":     "Vendedor",
        "vendas":       "Pedidos",
        "faturamento":  "Faturamento",
        "ticket_medio": "Ticket Medio",
        "share":        "Share",
    })
    for col in ["Faturamento", "Ticket Medio", "Share"]:
        rank[col] = rank[col].astype(float).fillna(0.0)
    fmt = {
        "Faturamento":  "R$ {:,.0f}",
        "Ticket Medio": "R$ {:,.0f}",
        "Share":        "{:.1f}%",
    }
    st.dataframe(rank.style.format(fmt), use_container_width=True, hide_index=True)

    # ── Evolução diária das vendas por vendedor ───────────────────────────────
    st.markdown("#### Evolução Diária de Vendas por Vendedor")
    daily_vend = (
        df_vend
        .groupby(["date", "vendedor"])
        .agg(faturamento=("total_price", "sum"))
        .reset_index()
        .sort_values("date")
    )

    fig3 = go.Figure()
    for i, vend_name in enumerate(vend["vendedor"]):
        subset = daily_vend[daily_vend["vendedor"] == vend_name]
        fig3.add_trace(go.Scatter(
            x=subset["date"],
            y=subset["faturamento"],
            name=vend_name,
            mode="lines+markers",
            line=dict(color=VEND_COLORS[i % len(VEND_COLORS)], width=2,
                      shape="spline", smoothing=0.7),
            marker=dict(size=4),
            hovertemplate="%{x|%d/%m}: R$ %{y:,.0f}<extra>" + vend_name + "</extra>",
        ))
    fig3.update_layout(
        **_base_layout(
            height=320,
            margin=dict(l=20, r=20, t=20, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", y=1.08, x=1, xanchor="right",
                        font=dict(size=11, color="#6B7280")),
            xaxis=dict(showgrid=False, zeroline=False,
                       tickfont=dict(size=10, color="#9CA3AF")),
            yaxis=dict(showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
                       tickfont=dict(size=10, color="#9CA3AF"),
                       tickprefix="R$ ", tickformat=",.0f"),
        )
    )
    st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})
