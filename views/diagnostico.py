"""
Aba de Diagnóstico — inspeciona JSON bruto do Bling para mapear campos.
Visível apenas para admin@noxer.com.br.
"""
import json
import os

import streamlit as st


def show():
    # Import lazy — evita crash se data.bling_auth falhar no import global
    from data.bling import get_venda_especifica, _LOJAS_CACHE, _TRAFICO_LOJA_IDS
    st.markdown("## Diagnóstico do Bling")
    st.caption(
        "Use esta aba para inspecionar o JSON bruto retornado pela API v3 "
        "e identificar a estrutura de campos como `loja`, `canal`, `vendedor`."
    )
    st.markdown("")

    # ── Seção 1: Lojas detectadas ──────────────────────────────────────────────
    st.markdown("#### Lojas / Depósitos Detectados")
    if _LOJAS_CACHE:
        for lid, desc in _LOJAS_CACHE.items():
            is_trafico = lid in _TRAFICO_LOJA_IDS
            icon = "🟢" if is_trafico else "⚪"
            st.markdown(f"{icon} **ID {lid}**: {desc}" + (" ← *Tráfego Pago*" if is_trafico else ""))
    else:
        st.info("Nenhuma loja carregada ainda. Os dados são carregados quando o dashboard é acessado.")

    st.markdown("---")

    # ── Seção 2: Inspeção de pedido ────────────────────────────────────────────
    st.markdown("#### Inspecionar Pedido (JSON Bruto)")

    col1, col2 = st.columns([2, 1])
    with col1:
        numero = st.text_input("Número do pedido", value="13995", placeholder="Ex: 13995")
    with col2:
        st.markdown("")
        buscar = st.button("Buscar Pedido", type="primary", use_container_width=True)

    if buscar and numero.strip():
        with st.spinner(f"Buscando pedido {numero}..."):
            resultado = get_venda_especifica(numero.strip())

        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        else:
            # Mostra campos-chave primeiro
            detalhe = resultado.get("_detalhe_completo", {})
            if detalhe:
                st.markdown("##### Campos-chave do pedido:")

                # Loja
                loja = detalhe.get("loja")
                canal = detalhe.get("canal")
                loja_virtual = detalhe.get("lojaVirtual")
                st.markdown(f"- **loja**: `{json.dumps(loja, ensure_ascii=False)}`")
                st.markdown(f"- **canal**: `{json.dumps(canal, ensure_ascii=False)}`")
                st.markdown(f"- **lojaVirtual**: `{json.dumps(loja_virtual, ensure_ascii=False)}`")

                # Vendedor
                vendedor = detalhe.get("vendedor")
                st.markdown(f"- **vendedor**: `{json.dumps(vendedor, ensure_ascii=False)}`")

                # Situação
                situacao = detalhe.get("situacao")
                st.markdown(f"- **situacao**: `{json.dumps(situacao, ensure_ascii=False)}`")

                # Número de itens
                itens = detalhe.get("itens", [])
                st.markdown(f"- **itens**: {len(itens)} produto(s)")

                st.markdown("---")

            # JSON completo expansível
            with st.expander("Ver JSON completo do DETALHE", expanded=False):
                st.json(resultado.get("_detalhe_completo", {}))

            with st.expander("Ver JSON da LISTAGEM (resumo)", expanded=False):
                st.json(resultado.get("_lista_resumo", {}))

            # Dica sobre todas as chaves disponíveis
            if detalhe:
                with st.expander("Todas as chaves de primeiro nível", expanded=False):
                    st.code(json.dumps(list(detalhe.keys()), ensure_ascii=False, indent=2))

    st.markdown("---")

    # ── Seção 3: Cache ─────────────────────────────────────────────────────────
    st.markdown("#### Gerenciamento de Cache")

    col_a, col_b = st.columns(2)

    with col_a:
        if st.button("Limpar Cache do Streamlit", use_container_width=True):
            st.cache_data.clear()
            st.success("Cache do Streamlit limpo! A próxima carga buscará dados frescos.")

    with col_b:
        cache_file = "data/bling_cache.json"
        cache_size = "N/A"
        if os.path.exists(cache_file):
            size_bytes = os.path.getsize(cache_file)
            cache_size = f"{size_bytes / 1024:.1f} KB"
        if st.button(f"Limpar Cache de Pedidos ({cache_size})", use_container_width=True):
            if os.path.exists(cache_file):
                os.remove(cache_file)
            st.cache_data.clear()
            st.success("Cache de pedidos removido! Todos os detalhes serão re-buscados da API.")
