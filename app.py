"""
Interface Streamlit do protótipo.

Rodar com:
    streamlit run app.py

Fonte de dados: por padrão usa a fonte REAL da CVM (baixa os ZIPs oficiais).
Se quiser demonstrar offline, marque "Usar dados de demonstração" na barra
lateral — nesse caso os dados são fictícios (src/collector_mock.py).

Abas:
  - Dashboard: métricas gerais + botão para rodar a coleta agora
  - Novos Registros: tabela filtrável dos registros novos do dia selecionado
  - Relatórios: relatório do dia (com resumo IA) + histórico de execuções
"""
import random
from datetime import date

import pandas as pd
import streamlit as st

from src.comparator import compare_snapshot
from src.report import build_report
from src.storage import (
    add_injected_record,
    get_history_dates,
    get_new_records_by_date,
    get_totals,
    init_db,
    save_new_records,
    save_snapshot,
)

st.set_page_config(page_title="Monitor CVM — Gestores e Consultorias", layout="wide")
init_db()

# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Fonte de dados")
    modo_demo = st.toggle(
        "Usar dados de demonstração (offline)",
        value=False,
        help="Ative para apresentar sem depender de internet. Os dados ficam fictícios.",
    )
    st.caption(
        "Desligado (padrão): baixa e processa os arquivos reais e atualizados "
        "da CVM (dados.cvm.gov.br)."
    )

if modo_demo:
    from src.collector_mock import collect_all
    st.warning(
        "⚠️ **Modo demonstração ativo**: os dados abaixo são fictícios. "
        "Desligue o toggle na barra lateral para usar a fonte real da CVM.",
        icon="⚠️",
    )
else:
    from src.collector import collect_all, FonteCVMError

st.title("📊 Monitor de Gestores e Consultorias — CVM")

tab_dashboard, tab_novos, tab_relatorios = st.tabs(
    ["🏠 Dashboard", "🆕 Novos Registros", "📄 Relatórios"]
)

# ============================== DASHBOARD ==================================
with tab_dashboard:
    totals = get_totals()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Última atualização", totals["ultima_atualizacao"] or "—")
    col2.metric("Total de gestores", totals["gestores"])
    col3.metric("Total de consultorias", totals["consultorias"])

    hoje = date.today().isoformat()
    novos_hoje = get_new_records_by_date(hoje)
    novos_gestores_hoje = len([r for r in novos_hoje if r["tipo"] == "Gestor"])
    novas_consultorias_hoje = len([r for r in novos_hoje if r["tipo"] == "Consultoria"])
    col4.metric("Novos gestores hoje", novos_gestores_hoje)
    col5.metric("Novas consultorias hoje", novas_consultorias_hoje)

    st.divider()
    st.subheader("Executar coleta")

    colA, colB = st.columns(2)
    with colA:
        st.caption(
            "Roda o pipeline completo agora: coleta → snapshot → comparação → "
            "relatório. Em produção, isso rodaria automaticamente 1x/dia "
            "(veja README para cron / GitHub Actions)."
        )
        if st.button("▶️ Executar coleta agora", type="primary"):
            with st.spinner("Coletando e comparando... (pode levar alguns segundos)"):
                try:
                    records = collect_all()
                    comparison = compare_snapshot(records)
                    save_snapshot(records, data_coleta=hoje)
                    if comparison.novos:
                        save_new_records(comparison.novos, data_deteccao=hoje)
                    report = build_report(comparison, data_coleta=hoje, use_ai=True)
                except Exception as exc:
                    st.error(f"Falha na coleta: {exc}")
                    st.stop()
            st.success(
                f"Coleta concluída: {report['total_novos_gestores']} novos "
                f"gestores, {report['total_novas_consultorias']} novas "
                f"consultorias, {report['total_alterados']} alterações."
            )
            st.rerun()

    with colB:
        if modo_demo:
            st.caption(
                "🎭 **Apenas para demonstração**: injeta 1–3 registros fictícios "
                "novos, simulando o que aconteceria se a CVM publicasse cadastros "
                "novos amanhã. Depois clique em 'Executar coleta agora'."
            )
            if st.button("🎲 Simular novos cadastros para o próximo dia"):
                qtd = random.randint(1, 3)
                for _ in range(qtd):
                    tipo = random.choice(["Gestor", "Consultoria"])
                    cnpj = f"{random.randint(10,99)}.{random.randint(100,999)}.{random.randint(100,999)}/0001-{random.randint(10,99)}"
                    hoje_str = date.today().isoformat()
                    add_injected_record(
                        {
                            "chave_unica": f"{cnpj}|{hoje_str}|{tipo}",
                            "tipo": tipo,
                            "pessoa": "PJ",
                            "nome": f"{'Gestora' if tipo == 'Gestor' else 'Consultoria'} Demo {cnpj[:8]} Ltda",
                            "cnpj": cnpj,
                            "situacao": "EM FUNCIONAMENTO NORMAL",
                            "data_registro": hoje_str,
                        }
                    )
                st.info(f"{qtd} registro(s) fictício(s) injetado(s). Clique em 'Executar coleta agora'.")
        else:
            st.caption(
                "Conectado à fonte real da CVM. Cada execução baixa os ZIPs "
                "mais recentes de dados.cvm.gov.br — pode levar de 10 a 30 "
                "segundos dependendo da conexão."
            )

# ============================ NOVOS REGISTROS ===============================
with tab_novos:
    st.subheader("Novos registros")

    history_dates = get_history_dates()
    if not history_dates:
        st.info("Ainda não há execuções registradas. Rode a coleta na aba Dashboard.")
    else:
        data_selecionada = st.selectbox("Data da detecção", history_dates)
        novos = get_new_records_by_date(data_selecionada)
        df = pd.DataFrame(novos).fillna("—")

        colf1, colf2 = st.columns(2)
        with colf1:
            tipo_filtro = st.multiselect(
                "Filtrar por tipo", options=["Gestor", "Consultoria"], default=["Gestor", "Consultoria"]
            )
        with colf2:
            busca = st.text_input("Buscar por nome ou CNPJ")

        if not df.empty:
            df_filtrado = df[df["tipo"].isin(tipo_filtro)]
            if busca:
                mask = df_filtrado["nome"].str.contains(busca, case=False, na=False) | df_filtrado[
                    "cnpj"
                ].astype(str).str.contains(busca, case=False, na=False)
                df_filtrado = df_filtrado[mask]

            st.dataframe(
                df_filtrado[["tipo", "pessoa", "nome", "cnpj", "situacao", "data_registro"]],
                use_container_width=True,
                hide_index=True,
            )

            with st.expander("Ver detalhes de um registro"):
                if not df_filtrado.empty:
                    nomes = df_filtrado["nome"].tolist()
                    escolhido = st.selectbox("Registro", nomes)
                    detalhe = df_filtrado[df_filtrado["nome"] == escolhido].iloc[0]
                    st.json(detalhe.to_dict())
        else:
            st.info("Nenhum registro novo nesta data.")

# =============================== RELATÓRIOS =================================
with tab_relatorios:
    st.subheader("Relatório do dia")

    history_dates = get_history_dates()
    if not history_dates:
        st.info("Ainda não há relatórios gerados. Rode a coleta na aba Dashboard.")
    else:
        data_rel = st.selectbox("Selecione a data do relatório", history_dates, key="rel_date")
        novos = get_new_records_by_date(data_rel)
        novos_gestores = [r for r in novos if r["tipo"] == "Gestor"]
        novas_consultorias = [r for r in novos if r["tipo"] == "Consultoria"]

        st.markdown(
            f"### Hoje foram identificados **{len(novos_gestores)} novos gestores** "
            f"e **{len(novas_consultorias)} novas consultorias**."
        )

        if novos:
            st.dataframe(
                pd.DataFrame(novos).fillna("—")[["tipo", "pessoa", "nome", "cnpj", "situacao", "data_registro"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Nenhum novo registro nesta data.")

        from src.config import REPORTS_DIR

        md_path = REPORTS_DIR / f"relatorio_{data_rel}.md"
        if md_path.exists():
            with st.expander("Ver relatório completo (markdown, com resumo de IA)"):
                st.markdown(md_path.read_text(encoding="utf-8"))

    st.divider()
    st.subheader("Histórico de execuções")
    if history_dates:
        st.write(", ".join(history_dates))
    else:
        st.caption("Nenhuma execução registrada ainda.")