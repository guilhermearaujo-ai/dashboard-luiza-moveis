"""
Constrói o DataFrame final da aplicação cruzando Meta Ads (real) com Bling (real).

NÃO há dados mockados. Se o Bling retornar vazio ou falhar, as colunas de
faturamento ficam zeradas — o dashboard exibe R$ 0, não valores falsos.
"""
import difflib
import re
import unicodedata

import pandas as pd
import streamlit as st

from data.bling import fetch_bling_orders
from data.meta import load_meta_data


# ── Agrupamento por Família de Produto ────────────────────────────────────────

# Palavras-chave que definem uma família diretamente (prioridade máxima)
_FAMILY_KEYWORDS = [
    "sofa", "mesa", "cozinha", "roupeiro", "colchao",
    "painel", "escrivaninha", "cadeira",
]

# Cores conhecidas a remover do nome antes de extrair a família (fallback)
_COLORS = {
    "branca", "branco", "preta", "preto", "cinza", "bege",
    "marrom", "azul", "verde", "vermelha", "vermelho",
    "amarela", "amarelo", "rose", "off", "nude",
}

# Medidas decimais com unidade opcional: 1,38 / 1.58m / 190cm / 2,00mt
_RE_MEASURE = re.compile(r"\b\d+[,\.]\d+\s*(?:m(?:t)?|cm)?\b", re.IGNORECASE)


def get_family_name(name: str) -> str:
    """
    Normaliza um nome de produto/anúncio em um nome de família.

    Prioridade:
    1. Keyword: se o nome contém uma palavra-chave de categoria, retorna ela.
    2. Fallback: primeiras duas palavras após remover medidas e cores conhecidas.
    """
    # Normaliza: minúsculas, sem acentos
    s = str(name).lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")

    # Remove medidas decimais
    s = _RE_MEASURE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # 1. Keyword match (varredura na ordem da lista — mais específico primeiro)
    for kw in _FAMILY_KEYWORDS:
        if kw in s.split() or f" {kw} " in f" {s} ":
            return kw

    # 2. Fallback: remove cores e retorna as duas primeiras palavras restantes
    words = [w for w in s.split() if w not in _COLORS and len(w) > 1]
    return " ".join(words[:2]) if words else s


def build_roas_by_family(df: pd.DataFrame) -> pd.DataFrame:
    """
    Constrói a tabela de ROAS consolidada por família de produto.

    Fluxo:
    - Bling Direto → agrupa total_price e quantity por get_family_name(product_name)
    - Meta Ads     → agrupa spend e leads por get_family_name(ad_name)
    - Merge outer  por _family → calcula CPL, Tx. Conversão, Ticket Médio, ROAS
    - Filtra linhas sem vendas E sem investimento (ambos zero)

    Retorna DataFrame ordenado por faturamento decrescente com colunas:
      produto, investimento, leads, cpl, unidades, tx_conversao, ticket_medio,
      faturamento, roas
    """
    df_bling = df[df["campaign_name"] == "Bling Direto"].copy()
    df_meta  = df[df["campaign_name"] != "Bling Direto"].copy()

    if df_bling.empty:
        return pd.DataFrame()

    # ── Bling: faturamento e unidades por família ─────────────────────────────
    df_bling["_family"] = df_bling["product_name"].apply(get_family_name)
    bling_agg = (
        df_bling.groupby("_family", as_index=False)
        .agg(faturamento=("total_price", "sum"), unidades=("quantity", "sum"))
    )

    # ── Meta: investimento e leads por família (baseado no ad_name) ───────────
    if not df_meta.empty:
        df_meta["_family"] = df_meta["ad_name"].apply(get_family_name)
        meta_agg = (
            df_meta.groupby("_family", as_index=False)
            .agg(investimento=("spend", "sum"), leads=("leads", "sum"))
        )
    else:
        meta_agg = pd.DataFrame(columns=["_family", "investimento", "leads"])

    # ── Merge outer: preserva famílias com só vendas ou só anúncio ───────────
    merged = pd.merge(bling_agg, meta_agg, on="_family", how="outer")

    for col in ["faturamento", "unidades", "investimento", "leads"]:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    # Filtra linhas com ambas as métricas zeradas
    merged = merged[(merged["unidades"] > 0) | (merged["investimento"] > 0)].copy()

    if merged.empty:
        return pd.DataFrame()

    # ── Métricas derivadas ────────────────────────────────────────────────────
    leads_s = merged["leads"].replace(0.0, float("nan"))
    inv_s   = merged["investimento"].replace(0.0, float("nan"))
    uni_s   = merged["unidades"].replace(0.0, float("nan"))

    merged["cpl"]          = (merged["investimento"] / leads_s).fillna(0.0).round(2)
    merged["tx_conversao"] = (merged["unidades"] / leads_s * 100).fillna(0.0).round(2)
    merged["ticket_medio"] = (merged["faturamento"] / uni_s).fillna(0.0).round(2)
    merged["roas"]         = (merged["faturamento"] / inv_s).fillna(0.0).round(2)

    merged["produto"] = merged["_family"].str.title()

    return (
        merged
        .drop(columns=["_family"])
        .sort_values("faturamento", ascending=False)
        .reset_index(drop=True)
    )


# ── Helpers de normalização / matching ────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, remove acentos, colapsa espaços."""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def _similarity(a: str, b: str) -> float:
    """
    Combina word-overlap com SequenceMatcher para matching mais robusto.
    Ex: 'guarda roupa 6 portas' vs 'guarda-roupa zeus 6 portas espelho' → ~0.6
    """
    # Word-overlap
    wa = set(a.split())
    wb = set(b.split())
    overlap = len(wa & wb) / max(len(wa), len(wb)) if wa and wb else 0.0
    # Sequence ratio (char-level)
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    return max(overlap, seq)


def _build_key_mapping(meta_keys, bling_keys, threshold: float = 0.35) -> dict:
    """
    Para cada chave normalizada do Meta, encontra a chave do Bling com maior
    similaridade (mínimo = threshold). Retorna {meta_key: bling_key}.
    Threshold reduzido para 0.35 para capturar matches parciais comuns
    em nomes de móveis (ex: 'guarda roupa' ↔ 'guarda-roupa zeus 6 portas').
    """
    mapping = {}
    for mk in meta_keys:
        best_score, best_bk = 0.0, None
        for bk in bling_keys:
            score = _similarity(mk, bk)
            if score > best_score:
                best_score, best_bk = score, bk
        if best_score >= threshold and best_bk:
            mapping[mk] = best_bk
    return mapping


# ── Merge Meta × Bling ────────────────────────────────────────────────────────

def _merge(meta: pd.DataFrame, bling: pd.DataFrame) -> pd.DataFrame:
    """
    Cruza Meta Ads com o DataFrame do Bling (real ou vazio).

    Se bling estiver vazio, todas as colunas de venda ficam com valor 0/"".
    """
    meta = meta.copy()

    # ── Normaliza datas para datetime64[ns] — evita mismatch de tipos ────
    # Ambos os DataFrames podem ter datetime.date (object) ou Timestamp;
    # .dt.normalize() garante que só a parte de data é comparada.
    meta["date"] = pd.to_datetime(meta["date"]).dt.normalize()

    meta["_meta_key"] = meta["ad_name"].apply(_normalize)

    if bling.empty:
        print("[Loader] Bling DataFrame vazio — faturamento será R$ 0.")
        df = meta.copy()
        df["quantity"]          = 0
        df["unit_price"]        = 0.0
        df["total_price"]       = 0.0
        df["bling_revenue_day"]  = 0.0
        df["bling_trafico_day"]  = 0.0
        df["vendedor"]           = ""
        df["product_name"]       = df["ad_name"]
        df["order_id"]           = ""
        df["matched"]            = False
        df["order_date"]         = df["date"]
        df["order_status"]       = "—"
        df["loja"]               = ""
        df["sku"]                = ""
        df["roas"] = 0.0
        df["cpl"]  = (df["spend"] / df["leads"]).where(df["leads"] > 0, 0.0).round(2)
        return df.drop(columns=["_meta_key"], errors="ignore").reset_index(drop=True)

    bling = bling.copy()
    bling["date"] = pd.to_datetime(bling["date"]).dt.normalize()

    print(f"[Loader] Datas no Bling: {bling['date'].dt.date.unique()[:5].tolist()}")
    print(f"[Loader] Datas no Meta:  {meta['date'].dt.date.unique()[:5].tolist()}")

    # ── Faturamento diário total — NÃO depende de match por produto ───────
    # Garante que o KPI "Faturamento Total" sempre mostre o valor real do Bling.
    bling_daily = (
        bling
        .groupby("date", as_index=False)
        .agg(bling_revenue_day=("total_price", "sum"))
    )

    # ── Agrega Bling por (data, produto) para atribuição por anúncio ─────
    bling_agg = (
        bling
        .groupby(["date", "_bling_key"], as_index=False)
        .agg(
            quantity    =("quantity",     "sum"),
            unit_price  =("unit_price",   "first"),
            total_price =("total_price",  "sum"),
            vendedor    =("vendedor",     "first"),
            product_name=("product_name", "first"),
            order_id    =("order_id",     "first"),
        )
    )

    # Mapeamento fuzzy: meta_key → bling_key mais próxima
    meta_keys  = meta["_meta_key"].unique().tolist()
    bling_keys = bling_agg["_bling_key"].unique().tolist()
    key_map    = _build_key_mapping(meta_keys, bling_keys)

    print(f"[Loader] Mapeamento de nomes encontrado: {key_map}")

    meta["_join_key"] = meta["_meta_key"].apply(lambda k: key_map.get(k, k))
    bling_agg = bling_agg.rename(columns={"_bling_key": "_join_key"})

    df = meta.merge(
        bling_agg[["date", "_join_key", "quantity", "unit_price",
                   "total_price", "vendedor", "product_name", "order_id"]],
        on=["date", "_join_key"],
        how="left",
    )

    # ── Anexa faturamento diário (independente de match por produto) ──────
    df = df.merge(bling_daily, on="date", how="left")
    df["bling_revenue_day"] = df["bling_revenue_day"].fillna(0.0)

    # ── Faturamento diário apenas dos pedidos "WhatsApp - Meta Ads" ───────
    if "loja" in bling.columns:
        bling_trafico_daily = (
            bling[bling["loja"] == "WhatsApp - Meta Ads"]
            .groupby("date", as_index=False)
            .agg(bling_trafico_day=("total_price", "sum"))
        )
        df = df.merge(bling_trafico_daily, on="date", how="left")
    if "bling_trafico_day" not in df.columns:
        df["bling_trafico_day"] = 0.0
    else:
        df["bling_trafico_day"] = df["bling_trafico_day"].fillna(0.0)

    # ── Garante colunas loja e sku nas linhas Meta (vazio — vêm do Bling Direto) ─
    if "loja" not in df.columns:
        df["loja"] = ""
    if "sku" not in df.columns:
        df["sku"] = ""

    df["quantity"]    = df["quantity"].fillna(0).astype(int)
    df["total_price"] = df["total_price"].fillna(0.0)
    df["unit_price"]  = df["unit_price"].fillna(0.0)
    df["vendedor"]    = df["vendedor"].fillna("")
    df["product_name"]= df["product_name"].fillna(df["ad_name"])
    df["order_id"]    = df["order_id"].fillna("")
    df["matched"]     = df["quantity"] > 0
    df["order_date"]  = df["date"]
    df["order_status"]= "Pago"

    df["roas"] = (df["bling_revenue_day"] / df["spend"]).where(df["spend"] > 0, 0.0).round(2)
    df["cpl"]  = (df["spend"] / df["leads"]).where(df["leads"] > 0, 0.0).round(2)

    df = df.drop(columns=["_meta_key", "_join_key"], errors="ignore")

    matched_meta = int(df["matched"].sum())
    total_meta   = len(df)
    total_bling  = bling_daily["bling_revenue_day"].sum()
    print(f"[Loader] Merge Meta↔Bling: {matched_meta}/{total_meta} linhas com match por produto.")
    print(f"[Loader] Faturamento Bling total: R$ {total_bling:,.2f}")

    # ── Linhas Bling Direto ────────────────────────────────────────────────────
    # Uma linha por item de pedido Bling, independente de match com Meta.
    # Alimenta as abas Produtos e Comercial sem depender do fuzzy match.
    # bling_revenue_day = 0 para não re-contar no KPI de Visão Geral.
    _bd_cols = ["date", "order_id", "product_name", "quantity",
                "unit_price", "total_price", "vendedor"]
    for _c in ("loja", "sku"):
        if _c in bling.columns:
            _bd_cols.append(_c)
    bling_direct = bling[_bd_cols].copy()

    # Fallback: produto sem nome vira "Outros / Não Identificado"
    bling_direct["product_name"] = (
        bling_direct["product_name"]
        .fillna("Outros / Não Identificado")
        .astype(str)
        .str.strip()
        .replace("", "Outros / Não Identificado")
    )

    # Fallback: vendedor vazio vira "Venda Direta"
    bling_direct["vendedor"] = (
        bling_direct["vendedor"]
        .fillna("Venda Direta")
        .astype(str)
        .str.strip()
        .replace("", "Venda Direta")
    )

    bling_direct["campaign_name"]     = "Bling Direto"
    bling_direct["adset_name"]        = "Bling Direto"
    bling_direct["ad_name"]           = bling_direct["product_name"]
    bling_direct["spend"]             = 0.0
    bling_direct["leads"]             = 0.0
    bling_direct["impressions"]       = 0.0
    bling_direct["clicks"]            = 0.0
    bling_direct["ctr"]               = 0.0
    bling_direct["cpc"]               = 0.0
    bling_direct["cpm"]               = 0.0
    bling_direct["bling_revenue_day"] = 0.0
    bling_direct["matched"]           = True
    bling_direct["order_date"]        = bling_direct["date"]
    bling_direct["order_status"]      = "Pago"
    bling_direct["roas"]              = 0.0
    bling_direct["cpl"]               = 0.0

    # Garante que colunas ausentes existam com defaults seguros
    for col in df.columns:
        if col not in bling_direct.columns:
            dtype = df[col].dtype
            if dtype == object:
                bling_direct[col] = ""
            elif dtype == bool:
                bling_direct[col] = False
            else:
                bling_direct[col] = 0

    bling_direct = bling_direct[df.columns]  # mesma ordem de colunas
    df = pd.concat([df, bling_direct], ignore_index=True)

    print(f"[Match] Vendas mapeadas: {matched_meta} de {total_meta} linhas Meta | "
          f"{len(bling_direct)} linhas Bling Direto adicionadas.")
    print(f"[Match] Vendedores Bling Direto: {df[df['campaign_name'] == 'Bling Direto']['vendedor'].unique().tolist()}")

    return df.reset_index(drop=True)


# ── Entrada pública ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_data() -> pd.DataFrame:
    """
    Retorna o DataFrame completo para todas as views.

    - Meta Ads : sempre real (Google Sheets via Stract).
    - Bling    : sempre real (API v2). Se falhar ou retornar vazio,
                 as colunas de faturamento ficam zeradas (R$ 0).
                 Nenhum dado falso é gerado.

    Lança RuntimeError se o Meta Ads falhar (capturado em app.py).
    """
    try:
        meta = load_meta_data()
    except Exception as exc:
        raise RuntimeError(
            "Falha ao carregar dados do Meta Ads (Google Sheets).\n\n"
            f"Detalhe: {exc}\n\n"
            "Verifique se a planilha está pública para leitura."
        ) from exc

    date_min = meta["date"].min()
    date_max = meta["date"].max()

    print(f"[Loader] Meta carregado: {len(meta)} linhas | {date_min} → {date_max}")

    try:
        bling = fetch_bling_orders(date_min, date_max)
        if bling.empty:
            st.info("Nenhum pedido Bling encontrado no período — Faturamento será R$ 0.")
    except Exception as exc:
        msg = str(exc)
        print(f"[Loader] ERRO ao buscar Bling: {msg}")
        st.warning(f"⚠️ Bling indisponível — {msg[:200]}")
        bling = pd.DataFrame()

    df = _merge(meta, bling)

    # ── Proteção de schema: garante que todas as colunas esperadas existam ──
    _required = {
        "bling_revenue_day":  0.0,
        "bling_trafico_day":  0.0,
        "total_price":        0.0,
        "quantity":           0,
        "unit_price":         0.0,
        "vendedor":           "",
        "loja":               "",
        "sku":                "",
        "matched":            False,
    }
    for col, default in _required.items():
        if col not in df.columns:
            print(f"[Loader] AVISO: coluna '{col}' ausente — preenchendo com {default!r}")
            df[col] = default

    print(f"[Loader] DataFrame final: {len(df)} linhas | colunas: {df.columns.tolist()}")
    print(f"[Loader] bling_revenue_day — dtype: {df['bling_revenue_day'].dtype} | sum: {df['bling_revenue_day'].sum():.2f}")

    return df
