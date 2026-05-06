# ── Page config — DEVE ser o primeiro comando Streamlit ───────────────────────
import streamlit as st
st.set_page_config(
    page_title="Noxer · Dashboard",
    page_icon="assets/simbolo1.svg",
    layout="wide",
    initial_sidebar_state="expanded",
)

import base64
import pandas as pd
from streamlit_option_menu import option_menu

from data.bling_auth import clear_tokens, exchange_code, get_auth_url, has_valid_tokens
from data.loader import load_data
from views import campanhas, comercial, dashboard, produtos, sku_dictionary

# ── Brand palette ──────────────────────────────────────────────────────────────
NOXER_BLUE  = "#005CFE"
NOXER_DARK  = "#0140B3"
NOXER_LIGHT = "#EBF5FF"
BG_ICE      = "#F8FAFC"
GRID_COLOR  = "rgba(229,231,235,0.45)"

# ── Valid users ────────────────────────────────────────────────────────────────
USERS = {
    "admin@noxer.com.br":          "noxer2026",
    "luiza@luizamoveis.com.br":    "vendas123",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
def _file_b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()

def _svg_img_tag(path: str, max_width: str = "160px") -> str:
    """Inline SVG as base64 <img> tag — works reliably across Streamlit versions."""
    data = _file_b64(path)
    return (
        f'<img src="data:image/svg+xml;base64,{data}" '
        f'style="width:100%; max-width:{max_width}; display:block; margin-bottom:8px;">'
    )

# ── CSS: login full-bleed ──────────────────────────────────────────────────────
def _inject_login_css() -> None:
    bg_data = _file_b64("assets/login_bg.jpg")
    bg_url  = f"data:image/jpeg;base64,{bg_data}"

    st.markdown(f"""<style>
/* ── Oculta sidebar, toggle e header nativo ── */
[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu, footer {{ display: none !important; }}

/* ── Fundo full-bleed com a imagem ── */
[data-testid="stAppViewContainer"] {{
  background-image: url("{bg_url}");
  background-size: cover;
  background-position: center;
  min-height: 100vh;
}}
[data-testid="stAppViewContainer"] > .main {{
  background: transparent !important;
}}

/* ── Empurra o conteúdo para baixo, criando centralização vertical ── */
.block-container {{
  padding-top: 15vh !important;
  padding-bottom: 0 !important;
  max-width: 100% !important;
}}

/* ── O st.form vira o card branco flutuante ── */
[data-testid="stForm"] {{
  background-color: #ffffff !important;
  padding: 40px 36px !important;
  border-radius: 20px !important;
  box-shadow: 0 10px 40px rgba(0,0,0,0.14), 0 2px 8px rgba(0,0,0,0.06) !important;
  border: none !important;
}}
[data-testid="stForm"]:hover {{
  border: none !important;
}}

/* ── Inputs ── */
[data-testid="stTextInput"] input {{
  border: 1.5px solid #E5E7EB !important;
  border-radius: 10px !important;
  font-size: 14px !important;
  transition: border-color 0.3s ease, box-shadow 0.3s ease !important;
  background: {BG_ICE} !important;
}}
[data-testid="stTextInput"] input:focus {{
  border-color: {NOXER_BLUE} !important;
  box-shadow: 0 0 0 3px rgba(0,92,254,.12) !important;
  background: #fff !important;
  outline: none !important;
}}

/* ── Botão submit do form (type="primary") ── */
[data-testid="stFormSubmitButton"] > button {{
  background: {NOXER_BLUE} !important;
  color: white !important;
  border: none !important;
  border-radius: 10px !important;
  font-size: 15px !important;
  font-weight: 700 !important;
  padding: 12px !important;
  width: 100% !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 4px 14px rgba(0,92,254,.32) !important;
}}
[data-testid="stFormSubmitButton"] > button:hover {{
  background: {NOXER_DARK} !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 20px rgba(0,92,254,.42) !important;
}}

/* ── Mensagem de erro ── */
[data-testid="stAlert"] {{
  border-radius: 10px !important;
  font-size: 13px !important;
}}
</style>""", unsafe_allow_html=True)


# ── CSS: dashboard principal (carregado de assets/style.css) ──────────────────
def _inject_dashboard_css() -> None:
    with open("assets/style.css", "r", encoding="utf-8") as fh:
        css = fh.read()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ── Session state ──────────────────────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "login_error" not in st.session_state:
    st.session_state.login_error = False

# ══════════════════════════════════════════════════════════════════════════════
# BLING OAUTH CALLBACK — PRIORIDADE MÁXIMA
# Quando o Bling redireciona para localhost:8501?code=XXX a sessão é nova
# (session state zerado). Por isso, além de trocar o code, já definimos
# logged_in = True aqui mesmo, antes de qualquer st.stop() ou verificação.
# ══════════════════════════════════════════════════════════════════════════════
_params = st.query_params
_bling_code = _params.get("code", "")
# Só processa o code UMA vez — a flag impede loop em caso de rerun
_code_already_used = st.session_state.get("_bling_code_processed", False)
if _bling_code and not _code_already_used:
    st.session_state._bling_code_processed = True   # trava antes de qualquer rerun
    st.query_params.clear()                          # remove ?code= da URL imediatamente
    try:
        exchange_code(str(_bling_code))
        # Loga automaticamente — o usuário já estava autenticado quando
        # clicou em "Autorizar Bling"; restauramos a sessão aqui.
        st.session_state.logged_in   = True
        st.session_state.login_error = False
        st.session_state.bling_flash = "success"
    except Exception as _exc:
        st.session_state.bling_flash = (
            f"error:Falha ao obter tokens do Bling. "
            f"Clique em 'Autorizar Bling' novamente.\n\nDetalhe: {_exc}"
        )
    st.rerun()

# ── Fallback: se bling_tokens.json existe e é válido, loga automaticamente ────
# Cobre o caso de refresh de página ou nova aba com token já salvo em disco.
if not st.session_state.logged_in and has_valid_tokens():
    st.session_state.logged_in = True

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    _inject_login_css()

    # Colunas para centralizar o card horizontalmente
    _, col_meio, _ = st.columns([1, 1.2, 1])

    with col_meio:
        with st.form(key="login_form"):
            # Logo dentro do card
            st.markdown(
                _svg_img_tag("assets/logo1.svg", max_width="150px"),
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p style="font-size:21px;font-weight:800;color:#111827;margin:18px 0 4px">'
                'Bem-vindo de volta</p>'
                '<p style="font-size:13.5px;color:#6B7280;margin:0 0 24px">'
                'Acesse seu painel de performance</p>',
                unsafe_allow_html=True,
            )

            email    = st.text_input("E-mail", placeholder="seu@email.com.br")
            password = st.text_input("Senha",  placeholder="••••••••", type="password")

            submitted = st.form_submit_button(
                "Entrar →", type="primary", use_container_width=True
            )

            st.markdown(
                '<p style="font-size:11px;color:#9CA3AF;margin-top:16px;line-height:1.8">'
                '🔑 <b>admin@noxer.com.br</b> / noxer2026<br>'
                '🔑 <b>luiza@luizamoveis.com.br</b> / vendas123</p>',
                unsafe_allow_html=True,
            )

        if submitted:
            if USERS.get(email.strip()) == password:
                st.session_state.logged_in   = True
                st.session_state.login_error = False
                st.rerun()
            else:
                st.session_state.login_error = True
                st.rerun()

        if st.session_state.login_error:
            st.error("E-mail ou senha inválidos. Tente novamente.")

    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# BLING CONNECTION SCREEN  (usuário logado no Noxer, mas Bling não conectado)
# ══════════════════════════════════════════════════════════════════════════════
if not has_valid_tokens():
    _inject_login_css()   # reutiliza o mesmo estilo de card centralizado

    # Flash messages (sucesso/erro vindos do callback)
    _flash = st.session_state.pop("bling_flash", None)
    if _flash == "success":
        st.success("✅ Bling conectado com sucesso!")
    elif _flash and _flash.startswith("error:"):
        st.error(f"Erro ao conectar ao Bling: {_flash[6:]}")

    _, _col, _ = st.columns([1, 1.2, 1])
    with _col:
        with st.container():
            st.markdown(f"""
<div style="background:#fff;border-radius:20px;padding:40px 36px;
            box-shadow:0 10px 40px rgba(0,0,0,0.14);text-align:center;">
  {_svg_img_tag("assets/logo1.svg", max_width="130px").replace('display:block','display:inline-block')}
  <p style="font-size:20px;font-weight:800;color:#111827;margin:20px 0 6px">
    Conectar ao Bling
  </p>
  <p style="font-size:13px;color:#6B7280;margin:0 0 28px;line-height:1.6">
    Para exibir os dados reais de faturamento, autorize o acesso à sua conta Bling.<br>
    Você será redirecionado e voltará automaticamente.
  </p>
</div>""", unsafe_allow_html=True)
            st.link_button("🔗 Conectar ao Bling", url=get_auth_url())

    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD (logged in + Bling conectado)
# ══════════════════════════════════════════════════════════════════════════════
_inject_dashboard_css()

# Flash de conexão bem-sucedida (pode aparecer na primeira carga pós-OAuth)
_flash = st.session_state.pop("bling_flash", None)
if _flash == "success":
    st.success("✅ Bling conectado com sucesso! Carregando dados reais...")

# ── Data ───────────────────────────────────────────────────────────────────────
try:
    df_full = load_data()
except RuntimeError as _err:
    st.error("**Erro ao carregar dados do Meta Ads**\n\n{}".format(_err))
    st.stop()

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(_svg_img_tag("assets/logo1.svg", max_width="140px"), unsafe_allow_html=True)
    st.markdown('<hr class="sb-div"/>', unsafe_allow_html=True)

    page = option_menu(
        menu_title=None,
        options=["Dashboard", "Produtos", "Campanhas", "Comercial", "Dicionário de SKUs"],
        icons=["bar-chart-line", "box-seam", "megaphone", "people", "book"],
        default_index=0,
        styles={
            "container":        {"padding": "4px 0", "background-color": "transparent"},
            "icon":             {"color": "#9CA3AF", "font-size": "14px"},
            "nav-link":         {
                "font-size": "13.5px",
                "color": "#6B7280",
                "padding": "8px 14px",
                "border-radius": "9px",
                "margin": "1px 0",
                "--hover-color": NOXER_LIGHT,
            },
            "nav-link-selected": {
                "background-color": NOXER_BLUE,
                "color": "white",
                "font-weight": "700",
            },
        },
    )

    st.markdown('<hr class="sb-div"/>', unsafe_allow_html=True)

    if st.button("Desconectar Bling", use_container_width=True):
        clear_tokens()
        st.cache_data.clear()
        st.session_state.pop("_bling_code_processed", None)  # permite nova autorização
        st.rerun()

    if st.button("Sair", use_container_width=True):
        st.session_state.logged_in   = False
        st.session_state.login_error = False
        st.rerun()

    st.markdown("---")
    st.info("V3 - Mapeamento Ativo")
    st.markdown('<div class="sb-footer">v2.1.0 · Meta real · Bling mock</div>',
                unsafe_allow_html=True)

# ── Dicionário de SKUs — não precisa de filtros nem do df ─────────────────────
if page == "Dicionário de SKUs":
    sku_dictionary.show()
    st.stop()

# ── Filter bar (apenas para abas analíticas) ───────────────────────────────────
date_min = df_full["date"].min()
date_max = df_full["date"].max()

fc1, fc2, fc3, fc4, fc5 = st.columns([2.5, 2.5, 2.5, 1.2, 1.2])

with fc1:
    sel_products = st.multiselect(
        "Produtos", options=sorted(df_full["ad_name"].unique()),
        default=[], placeholder="Todos — Anúncios / Produtos",
        label_visibility="collapsed",
    )
with fc2:
    sel_campaigns = st.multiselect(
        "Campanhas", options=sorted(df_full["campaign_name"].unique()),
        default=[], placeholder="Todas — Campanhas",
        label_visibility="collapsed",
    )
with fc3:
    sel_adsets = st.multiselect(
        "Conjuntos", options=sorted(df_full["adset_name"].unique()),
        default=[], placeholder="Todos — Conjuntos",
        label_visibility="collapsed",
    )
with fc4:
    start_date = st.date_input("De",  value=date_min, min_value=date_min,
                               max_value=date_max, label_visibility="collapsed")
with fc5:
    end_date   = st.date_input("Até", value=date_max, min_value=date_min,
                               max_value=date_max, label_visibility="collapsed")

# Converte para Timestamp para ser compatível com df["date"] datetime64[ns]
start_ts = pd.to_datetime(start_date)
end_ts   = pd.to_datetime(end_date)

# ── Apply filters ──────────────────────────────────────────────────────────────
prods  = sel_products  or df_full["ad_name"].unique().tolist()
camps  = sel_campaigns or df_full["campaign_name"].unique().tolist()
adsets = sel_adsets    or df_full["adset_name"].unique().tolist()

df = df_full[
    (df_full["date"] >= start_ts)
    & (df_full["date"] <= end_ts)
    & (df_full["ad_name"].isin(prods))
    & (df_full["campaign_name"].isin(camps))
    & (df_full["adset_name"].isin(adsets))
].copy()

if df.empty:
    st.warning("Nenhum dado encontrado para os filtros selecionados.")
    st.stop()

st.caption(
    "Período: **{}** – **{}**  ·  Meta Ads: dados reais (Stract)  ·  Bling: dados reais".format(
        start_ts.strftime("%d %b"), end_ts.strftime("%d %b, %Y"),
    )
)

# ── Routing ────────────────────────────────────────────────────────────────────
try:
    if page == "Dashboard":
        dashboard.show(df)
    elif page == "Produtos":
        produtos.show(df)
    elif page == "Campanhas":
        campanhas.show(df)
    elif page == "Comercial":
        comercial.show(df)
except Exception as _view_err:
    st.error(f"Erro ao carregar a aba **{page}**: {_view_err}")
