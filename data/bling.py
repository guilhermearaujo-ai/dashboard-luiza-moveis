"""
Integração com a API v3 do Bling — extração em 2 etapas obrigatórias:

  Etapa 1 — Listagem paginada (/pedidos/vendas)
    → Coleta IDs e metadados. A listagem NÃO contém itens nem vendedor.

  Etapa 2 — Detalhe individual (/pedidos/vendas/{id})
    → Para CADA pedido, faz uma chamada separada para obter:
      • itens[]  — produtos, quantidades e valores
      • vendedor — nome do responsável pela venda
    → time.sleep(0.33) entre chamadas = respeita limite de 3 req/s do Bling.
    → Cache em disco (data/bling_cache.json): apenas IDs novos são buscados.
"""
import json
import os
import re
import time
import unicodedata
from datetime import date
from typing import Optional

import pandas as pd
import requests

from data.bling_auth import get_valid_access_token, invalidate_tokens

_BASE_URL   = "https://www.bling.com.br/Api/v3/pedidos/vendas"
_PAGE_SIZE  = 100
_CANCELLED  = {"cancelado", "cancelada", "cancelados", "cancelamento"}
_CACHE_FILE = "data/bling_cache.json"

_COLUMNS = ["date", "order_id", "product_name",
            "quantity", "unit_price", "total_price", "vendedor", "loja", "sku", "_bling_key"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def _parse_date(value) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return pd.to_datetime(str(value), format=fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def _to_float(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return 0.0


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


# ── Cache em disco ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    """Carrega cache de detalhes do disco. Retorna {} se não existir ou falhar."""
    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # JSON serializa chaves como string; converte de volta para int
        return {int(k): v for k, v in raw.items()}
    except Exception as exc:
        print(f"[Cache] Falha ao ler cache ({exc}) — iniciando do zero.")
        return {}


def _save_cache(detalhes: dict) -> None:
    """Persiste o dict {id: detalhe} em disco."""
    os.makedirs("data", exist_ok=True)
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in detalhes.items()}, f,
                      ensure_ascii=False, separators=(",", ":"))
        print(f"[Cache] {len(detalhes)} pedidos salvos em {_CACHE_FILE}.")
    except Exception as exc:
        print(f"[Cache] Falha ao salvar cache: {exc}")


def _fetch_vendedores(token: str) -> dict:
    """
    GET /vendedores — retorna {vendedor_id: nome} para todos os vendedores ativos.

    Na API v3 o pedido retorna apenas vendedor.id. O nome real está em
    vendedor.contato.nome dentro do endpoint /vendedores.
    """
    try:
        resp = requests.get(
            "https://www.bling.com.br/Api/v3/vendedores",
            headers=_headers(token),
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[Bling] /vendedores HTTP {resp.status_code} — usando 'Venda Direta' como fallback.")
            return {}
        mapping = {}
        for v in resp.json().get("data", []):
            vid  = v.get("id")
            nome = (v.get("contato") or {}).get("nome", "").strip()
            if vid and nome:
                mapping[int(vid)] = nome
        print(f"[Bling] {len(mapping)} vendedores carregados: {mapping}")
        return mapping
    except Exception as exc:
        print(f"[Bling] Erro ao buscar vendedores: {exc}")
        return {}


def _vendedor_nome(obj: dict, vendedores_map: dict) -> str:
    """
    Resolve o nome do vendedor do pedido usando o mapa {id: nome} pré-carregado.

    A API v3 retorna apenas vendedor.id no detalhe do pedido; o nome vem de
    /vendedores (buscado uma vez por carga em _fetch_vendedores).
    Retorna 'Venda Direta' se o id não estiver no mapa ou o campo estiver ausente.
    """
    raw = obj.get("vendedor")
    if isinstance(raw, dict):
        vid = raw.get("id")
        if vid and vendedores_map:
            nome = vendedores_map.get(int(vid), "")
            if nome:
                return nome
        # fallback: algumas versões antigas podem ter 'nome' diretamente
        nome_direto = (raw.get("nome") or raw.get("name") or "").strip()
        if nome_direto:
            return nome_direto
    elif isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "Venda Direta"


# ── Etapa 1: listagem paginada ─────────────────────────────────────────────────

def _listar_pedidos(token: str, sd: str, ed: str) -> list[dict]:
    """
    Pagina /pedidos/vendas e retorna lista de dicts com:
    id, numero, data, total, vendedor_resumo (fallback da listagem).
    Para quando a API retorna lista vazia.
    """
    pedidos = []
    page    = 1

    while True:
        resp = requests.get(
            _BASE_URL,
            headers=_headers(token),
            params=[
                ("pagina",      page),
                ("limite",      _PAGE_SIZE),
                ("dataInicial", sd),
                ("dataFinal",   ed),
            ],
            timeout=30,
        )

        if resp.status_code in (204, 404):
            print(f"[Bling] Página {page}: HTTP {resp.status_code} — sem mais dados.")
            break

        if resp.status_code == 401:
            invalidate_tokens()
            try:
                import streamlit as _st
                _st.cache_data.clear()
            except Exception:
                pass
            raise Exception(
                "Bling 401 — token expirado. "
                "Clique em 'Conectar ao Bling' para re-autorizar."
            )

        if resp.status_code != 200:
            raise Exception(
                f"Bling HTTP {resp.status_code} na listagem.\nCorpo: {resp.text[:400]}"
            )

        payload = resp.json()
        data = payload.get("data", [])
        if not data:
            print(f"[Bling] Página {page}: lista vazia — fim da paginação.")
            break

        for o in data:
            sit = o.get("situacao", {})
            sit_nome = normalize(
                sit.get("valor", "") if isinstance(sit, dict) else str(sit)
            )
            if sit_nome in _CANCELLED:
                continue

            bling_id = o.get("id")
            if not bling_id:
                continue

            pedidos.append({
                "id":              bling_id,
                "numero":          str(o.get("numero", bling_id)).strip(),
                "data":            o.get("data"),
                "total":           _to_float(o.get("total", o.get("valor", 0))),
                "vendedor_lista":  "Venda Direta",   # listagem não contém nome; resolvido via /vendedores
            })

        print(f"[Bling] Página {page}: {len(data)} pedidos | {len(pedidos)} acumulados")
        page += 1

    return pedidos


# ── Etapa 2: detalhe individual por pedido ─────────────────────────────────────

def _buscar_detalhe(bling_id: int, numero: str, token: str) -> dict:
    """
    GET /pedidos/vendas/{id} — retorna o JSON completo com itens e vendedor.
    Retorna {} em caso de falha.
    """
    print(f"  Lendo detalhes do pedido {numero} (id={bling_id})...")
    try:
        resp = requests.get(
            f"{_BASE_URL}/{bling_id}",
            headers=_headers(token),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("data", {})
        print(f"  [AVISO] Pedido {numero}: HTTP {resp.status_code} no detalhe.")
    except Exception as exc:
        print(f"  [AVISO] Pedido {numero}: erro de rede — {exc}")
    return {}


# ── Etapa 3: montar DataFrame de itens ────────────────────────────────────────

def _construir_itens(pedidos: list[dict], detalhes: dict, vendedores_map: dict) -> list[dict]:
    """
    Para cada pedido, usa os itens do detalhe para criar uma linha por produto.
    Fallback: se não houver itens, cria uma linha com 'Outros / Não Identificado'.
    """
    rows = []

    for p in pedidos:
        try:
            # ── data do pedido ───────────────────────────────────────────────
            order_date = _parse_date(p.get("data"))
            if order_date is None:
                print(f"[Bling] Pedido {p.get('numero','?')}: data inválida '{p.get('data')}' — ignorado.")
                continue

            order_num   = p.get("numero", str(p.get("id", "?")))
            order_total = _to_float(p.get("total", 0))
            detalhe     = detalhes.get(p.get("id"), {}) or {}
            vendedor    = _vendedor_nome(detalhe, vendedores_map) if detalhe else p.get("vendedor_lista", "Venda Direta")
            itens       = detalhe.get("itens") or []

            # ── Extrai loja — mapeamento robusto ────────────────────────────
            loja_raw = detalhe.get("loja") or {}
            if isinstance(loja_raw, dict):
                l_id   = str(loja_raw.get("id", "")).strip()
                l_desc = str(loja_raw.get("descricao", "")).lower()
            else:
                l_id   = str(loja_raw).strip()
                l_desc = str(loja_raw).lower()

            if l_id or "whatsapp" in l_desc or "meta" in l_desc:
                loja_nome = "WhatsApp - Meta Ads"
            else:
                loja_nome = "Outros"

            # ── Itens do pedido ──────────────────────────────────────────────
            if itens:
                items_sum = 0.0
                for item in itens:
                    descricao  = (item.get("descricao") or "").strip() or "Produto sem descrição"
                    qty        = _to_float(item.get("quantidade", 1))
                    unit_price = _to_float(item.get("valor", 0))
                    line_total = round(qty * unit_price, 2)
                    items_sum += line_total
                    sku        = (item.get("codigo") or "").strip()

                    rows.append({
                        "date":         order_date,
                        "order_id":     order_num,
                        "product_name": descricao,
                        "quantity":     qty,
                        "unit_price":   unit_price,
                        "total_price":  line_total,
                        "vendedor":     vendedor,
                        "loja":         loja_nome,
                        "sku":          sku,
                        "_bling_key":   normalize(descricao),
                    })

                # Ajuste de desconto / frete: preserva o total oficial
                diff = round(order_total - items_sum, 2)
                if abs(diff) > 0.05 and order_total > 0:
                    rows.append({
                        "date":         order_date,
                        "order_id":     order_num,
                        "product_name": "Desconto / Frete / Ajuste",
                        "quantity":     1.0,
                        "unit_price":   diff,
                        "total_price":  diff,
                        "vendedor":     vendedor,
                        "loja":         loja_nome,
                        "sku":          "",
                        "_bling_key":   "desconto frete ajuste",
                    })
            else:
                # Sem itens: registra o total do pedido como linha única
                rows.append({
                    "date":         order_date,
                    "order_id":     order_num,
                    "product_name": "Outros / Não Identificado",
                    "quantity":     1.0,
                    "unit_price":   order_total,
                    "total_price":  order_total,
                    "vendedor":     vendedor,
                    "loja":         loja_nome,
                    "sku":          "",
                    "_bling_key":   "outros nao identificado",
                })

        except Exception as exc:
            print(f"[Bling] Pedido {p.get('numero', p.get('id', '?'))}: erro ao processar — {exc}. Ignorado.")
            continue

    return rows


# ── Entrada pública ────────────────────────────────────────────────────────────

def fetch_bling_orders(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Busca todos os pedidos de venda na API v3 do Bling.

    - dataInicial fixo em 2026-01-01 (histórico completo do ano).
    - Etapa 1: listagem paginada para coletar IDs.
    - Etapa 2: uma chamada a /pedidos/vendas/{id} por pedido,
               com time.sleep(0.33) para respeitar 3 req/s do Bling.
    - Fallback de produto: 'Outros / Não Identificado'.
    - Fallback de vendedor: 'Venda Direta'.
    """
    # ── Valida limite de 360 dias da API do Bling ────────────────────────────
    days_diff = (end_date - start_date).days
    if days_diff > 360:
        raise ValueError(
            f"Período de {days_diff} dias excede o limite de 360 dias da API do Bling. "
            "Ajuste os filtros de data para um intervalo menor."
        )

    token = get_valid_access_token()

    sd = start_date.strftime("%Y-%m-%d")
    ed = end_date.strftime("%Y-%m-%d")
    print(f"[Bling] Período: {sd} → {ed}")

    # ── Pré-carga de vendedores (1 chamada, mapa {id: nome}) ─────────────────
    vendedores_map = _fetch_vendedores(token)

    # ── Etapa 1 ───────────────────────────────────────────────────────────────
    pedidos = _listar_pedidos(token, sd, ed)
    print(f"[Bling] {len(pedidos)} pedidos não-cancelados encontrados.")

    if not pedidos:
        return pd.DataFrame(columns=_COLUMNS)

    # ── Etapa 2 — com cache em disco ─────────────────────────────────────────
    cached   = _load_cache()
    ids_api  = {p["id"] for p in pedidos}
    ids_novos = ids_api - set(cached.keys())

    print(f"[Cache] {len(cached)} no cache | {len(ids_novos)} novos para buscar.")

    # Aproveita detalhes já cacheados
    detalhes: dict[int, dict] = {pid: cached[pid] for pid in ids_api if pid in cached}

    if ids_novos:
        novos = [p for p in pedidos if p["id"] in ids_novos]
        total_novos = len(novos)
        print(f"[Bling] Buscando {total_novos} detalhes novos (~{total_novos*0.33:.0f}s)...")

        for i, p in enumerate(novos, 1):
            detalhes[p["id"]] = _buscar_detalhe(p["id"], p["numero"], token)
            time.sleep(0.33)   # respeita limite de 3 req/s da API do Bling

            if i % 50 == 0:
                print(f"[Bling] Progresso: {i}/{total_novos} novos detalhes carregados...")

        # Persiste cache atualizado (antigos + novos)
        _save_cache({**cached, **detalhes})
    else:
        print("[Cache] Todos os pedidos já estão no cache — nenhuma chamada de detalhe necessária.")

    # ── Etapa 3 ───────────────────────────────────────────────────────────────
    rows = _construir_itens(pedidos, detalhes, vendedores_map)

    print(f"[Bling] Total de itens processados: {len(rows)}")

    if not rows:
        return pd.DataFrame(columns=_COLUMNS)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    # Garante que colunas numéricas sejam float (defensive cast)
    for _num_col in ("quantity", "unit_price", "total_price"):
        df[_num_col] = pd.to_numeric(df[_num_col], errors="coerce").fillna(0.0)

    # Preenche vendedores vazios
    df["vendedor"] = df["vendedor"].replace("", "Venda Direta").fillna("Venda Direta")

    print(f"[Bling] Faturamento total: R$ {df['total_price'].sum():,.2f}")
    print(f"[Bling] Vendedores encontrados: {sorted(df['vendedor'].unique().tolist())}")

    return df


# ── Diagnóstico: busca direta por número de pedido ────────────────────────────

def get_venda_especifica(numero_pedido: str = "13995") -> dict:
    """
    Busca o pedido pelo número via GET /pedidos/vendas?numero=<n>.
    Retorna o JSON bruto do primeiro resultado (listagem + detalhe completo)
    para diagnóstico do mapeamento de campos da API v3.
    """
    try:
        token = get_valid_access_token()
    except Exception as exc:
        return {"erro": f"Token inválido: {exc}"}

    # Etapa 1: achar o ID pelo número
    try:
        resp = requests.get(
            _BASE_URL,
            headers=_headers(token),
            params={"numero": numero_pedido, "limite": 5},
            timeout=15,
        )
        print(f"[Debug] /pedidos/vendas?numero={numero_pedido} → HTTP {resp.status_code}")
        if resp.status_code != 200:
            return {"erro": f"HTTP {resp.status_code}", "body": resp.text[:400]}
        lista = resp.json().get("data", [])
        if not lista:
            return {"erro": f"Pedido {numero_pedido} não encontrado na listagem."}
    except Exception as exc:
        return {"erro": f"Erro na listagem: {exc}"}

    resumo = lista[0]
    bling_id = resumo.get("id")

    # Etapa 2: detalhe completo
    try:
        resp2 = requests.get(
            f"{_BASE_URL}/{bling_id}",
            headers=_headers(token),
            timeout=15,
        )
        print(f"[Debug] /pedidos/vendas/{bling_id} → HTTP {resp2.status_code}")
        if resp2.status_code == 200:
            detalhe = resp2.json().get("data", {})
            return {"_lista_resumo": resumo, "_detalhe_completo": detalhe}
        return {"_lista_resumo": resumo, "erro_detalhe": f"HTTP {resp2.status_code}"}
    except Exception as exc:
        return {"_lista_resumo": resumo, "erro_detalhe": str(exc)}
