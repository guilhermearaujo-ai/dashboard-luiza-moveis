"""
Carrega e limpa os dados reais do Meta Ads exportados via Stract → Google Sheets.
"""
import pandas as pd

_SHEET_ID = "1UKL-A0eAq-Mtt2rtevojJkMtUbLKAC6QxMKyRpKn9zU"
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    + _SHEET_ID
    + "/export?format=csv"
)

# Mapeamento exato: nome original da coluna → nome interno
_RENAME = {
    "Date":                       "date",
    "Campaign Name":              "campaign_name",
    "Adset Name":                 "adset_name",
    "Ad Name":                    "ad_name",
    "Spend (Cost, Amount Spent)": "spend",
    "Results":                    "leads",
    "Impressions":                "impressions",
    "Action Link Clicks":         "clicks",
}


def load_meta_data():
    """
    Baixa o CSV do Google Sheets, renomeia colunas, trata tipos e
    calcula CTR, CPC e CPM.

    Retorna um pd.DataFrame limpo ou levanta RuntimeError se falhar.
    Sem @st.cache_data — o cache é gerido pelo load_data() em loader.py.
    """
    try:
        raw = pd.read_csv(CSV_URL)
    except Exception as exc:
        raise RuntimeError(
            "Falha ao carregar Google Sheets ({}).\n"
            "Verifique se a planilha está pública para leitura.".format(exc)
        )

    # ── Mantém só as colunas mapeadas que existem no CSV ──────────────
    present = {k: v for k, v in _RENAME.items() if k in raw.columns}
    missing = set(_RENAME.keys()) - set(present.keys())
    if missing:
        raise RuntimeError(
            "Colunas ausentes no CSV do Meta Ads: {}".format(missing)
        )
    df = raw[list(present.keys())].rename(columns=present).copy()

    # ── Data ──────────────────────────────────────────────────────────
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date"])

    # ── Spend: "31,68" → 31.68 (padrão pt-BR) ────────────────────────
    df["spend"] = (
        df["spend"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.", "", regex=True)   # remove separador de milhar
        .str.replace(",", ".", regex=False)   # decimal pt-BR → en
        .str.replace(r"[^\d.]", "", regex=True)
    )
    df["spend"] = pd.to_numeric(df["spend"], errors="coerce").fillna(0.0)

    # ── Colunas numéricas ─────────────────────────────────────────────
    for col in ("leads", "impressions", "clicks"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # ── Strings sem NaN ───────────────────────────────────────────────
    for col in ("campaign_name", "adset_name", "ad_name"):
        df[col] = df[col].fillna("").astype(str).str.strip()

    df = df[df["ad_name"] != ""].reset_index(drop=True)

    # ── Métricas calculadas ───────────────────────────────────────────
    df["ctr"] = (
        (df["clicks"] / df["impressions"]) * 100
    ).where(df["impressions"] > 0, 0.0).round(2)

    df["cpc"] = (
        df["spend"] / df["clicks"]
    ).where(df["clicks"] > 0, 0.0).round(2)

    df["cpm"] = (
        (df["spend"] / df["impressions"]) * 1000
    ).where(df["impressions"] > 0, 0.0).round(2)

    return df


def extract_skus_from_ad_name(ad_name: str) -> list:
    """
    Extrai lista de SKUs do nome do anúncio seguindo a taxonomia:
    ID_CATEGORIA_NOME_[SKUs]  →  ex: AD001_mesa_ametista_173319-173320

    Retorna lista de strings numéricas (ex: ['173319', '173320'])
    ou [] se o padrão não for identificado.
    """
    parts = str(ad_name).strip().split("_")
    if len(parts) < 2:
        return []
    sku_part = parts[-1]
    return [s.strip() for s in sku_part.split("-") if s.strip().isdigit()]
