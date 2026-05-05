"""
Gerenciamento de tokens OAuth2 para a API v3 do Bling.

Fluxo:
  1. get_auth_url()        → abre no browser para o usuário autorizar
  2. exchange_code(code)   → troca o code por access + refresh token
  3. get_valid_access_token() → retorna token válido, renovando se necessário
"""
import base64
import json
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

_REDIRECT_URI = os.getenv("BLING_REDIRECT_URI", "http://localhost:8501")
_AUTH_URL     = "https://www.bling.com.br/Api/v3/oauth/authorize"
_TOKEN_URL    = "https://www.bling.com.br/Api/v3/oauth/token"
_TOKEN_FILE   = Path(__file__).parent.parent / "bling_tokens.json"


def _load_env() -> tuple:
    """
    Lê CLIENT_ID e CLIENT_SECRET do .env em tempo de execução (não no import).
    Garante que o dotenv seja carregado a partir do diretório do projeto,
    independentemente do CWD no momento do import.
    """
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    client_id     = os.getenv("BLING_CLIENT_ID", "").strip()
    client_secret = os.getenv("BLING_CLIENT_SECRET", "").strip()
    print(f"[BlingAuth] CLIENT_ID carregado: {client_id[:6]}***" if client_id else "[BlingAuth] CLIENT_ID VAZIO!")
    return client_id, client_secret


# ── URL de autorização ────────────────────────────────────────────────────────

def get_auth_url(state: str = "noxer_dashboard") -> str:
    """Gera a URL de autorização OAuth2 que o usuário deve abrir no browser."""
    client_id, _ = _load_env()
    if not client_id:
        raise RuntimeError("BLING_CLIENT_ID não encontrado no .env")
    params = urlencode({
        "response_type": "code",
        "client_id":     client_id,
        "redirect_uri":  _REDIRECT_URI,
        "state":         state,
    })
    return f"{_AUTH_URL}?{params}"


# ── Troca de code por tokens ──────────────────────────────────────────────────

def exchange_code(code: str) -> dict:
    """
    Troca o código de autorização (retornado pelo Bling via redirect) por
    access_token + refresh_token. Salva os tokens em bling_tokens.json.
    """
    print(f"[BlingAuth] Trocando code por tokens...")
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization":  _basic_header(),
            "Content-Type":   "application/x-www-form-urlencoded",
            "Accept":         "application/json",
        },
        data={
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": _REDIRECT_URI,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise Exception(
            f"Bling token exchange falhou (HTTP {resp.status_code}):\n{resp.text}"
        )
    tokens = resp.json()
    _save_tokens(tokens)
    print("[BlingAuth] Tokens obtidos e salvos com sucesso.")
    return tokens


# ── Refresh automático ────────────────────────────────────────────────────────

def _do_refresh(refresh_tok: str) -> dict:
    """Usa o refresh_token para obter um novo access_token."""
    print("[BlingAuth] Renovando access_token via refresh_token...")
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization":  _basic_header(),
            "Content-Type":   "application/x-www-form-urlencoded",
            "Accept":         "application/json",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_tok,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        _clear_tokens()
        raise Exception(
            f"Bling refresh falhou (HTTP {resp.status_code}):\n{resp.text}\n"
            "Tokens removidos — reconecte ao Bling."
        )
    tokens = resp.json()
    _save_tokens(tokens)
    print("[BlingAuth] Access_token renovado com sucesso.")
    return tokens


# ── Interface pública ─────────────────────────────────────────────────────────

def get_valid_access_token() -> str:
    """
    Retorna um access_token válido.

    - Carrega tokens do arquivo.
    - Se estiver expirado (ou a menos de 5 min), faz refresh automático.
    - Se o refresh falhar (401/qualquer erro), apaga bling_tokens.json e
      lança Exception pedindo re-autorização.
    - Lança Exception se não houver tokens salvos.
    """
    tokens = _load_tokens()
    if not tokens:
        raise Exception(
            "Nenhum token Bling encontrado. "
            "Clique em 'Conectar ao Bling' para autorizar."
        )

    expires_at = tokens.get("expires_at", 0)
    # Renova se expirado, faltam menos de 5 minutos, ou expires_at é 0 (corrompido)
    if expires_at == 0 or time.time() >= expires_at - 300:
        try:
            tokens = _do_refresh(tokens["refresh_token"])
        except Exception as exc:
            # _do_refresh já limpou o arquivo; re-lança com instrução clara
            raise Exception(
                f"Token Bling inválido ou expirado — tokens removidos.\n"
                f"Detalhe: {exc}\n"
                "Clique em 'Conectar ao Bling' para re-autorizar."
            )

    return tokens["access_token"]


def invalidate_tokens() -> None:
    """
    Apaga bling_tokens.json imediatamente.
    Chamado externamente quando a API retorna 401, forçando re-autorização.
    """
    print("[BlingAuth] Token invalidado por 401 da API — apagando arquivo.")
    _clear_tokens()


def has_valid_tokens() -> bool:
    """True se existem tokens salvos em disco (não verifica expiração)."""
    t = _load_tokens()
    return bool(t.get("access_token") and t.get("refresh_token"))


def clear_tokens() -> None:
    """Remove os tokens salvos (desconectar do Bling)."""
    _clear_tokens()


# ── Persistência ───────────────────────────────────────────────────────────────

def _basic_header() -> str:
    client_id, client_secret = _load_env()
    if not client_id or not client_secret:
        raise RuntimeError(
            "BLING_CLIENT_ID ou BLING_CLIENT_SECRET não encontrados no .env. "
            f"(client_id={'OK' if client_id else 'VAZIO'}, "
            f"client_secret={'OK' if client_secret else 'VAZIO'})"
        )
    creds = f"{client_id}:{client_secret}"
    return "Basic " + base64.b64encode(creds.encode()).decode()


def _save_tokens(data: dict) -> None:
    expires_in = int(data.get("expires_in", 3600))
    payload = {
        "access_token":  data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at":    int(time.time()) + expires_in,
    }
    _TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[BlingAuth] Tokens salvos → {_TOKEN_FILE.name}  (expira em {expires_in}s)")


def _load_tokens() -> dict:
    if not _TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(_TOKEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _clear_tokens() -> None:
    if _TOKEN_FILE.exists():
        _TOKEN_FILE.unlink()
        print("[BlingAuth] bling_tokens.json removido.")
