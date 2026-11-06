"""
Monitor de Gestores e Consultores — CVM.

Rodar com:
    streamlit run app.py

Páginas (menu lateral): Dashboard, Novos Registros, Consulta, Relatórios e Exportações.
Toda a lógica fica em src/ (ui.py = telas, analytics.py = cálculos, pipeline.py = atualização).
"""
import streamlit as st

from src import ui

st.set_page_config(page_title="Monitor CVM: Gestores e Consultores", page_icon=":material/monitoring:", layout="wide")
ui.injetar_css()

navegacao = st.navigation([
    st.Page(ui.pagina_dashboard, title="Dashboard", icon=":material/dashboard:", url_path="dashboard", default=True),
    st.Page(ui.pagina_novos, title="Novos Registros", icon=":material/fiber_new:", url_path="novos-registros"),
    st.Page(ui.pagina_consulta, title="Consulta", icon=":material/search:", url_path="consulta"),
    st.Page(ui.pagina_relatorios, title="Relatórios", icon=":material/description:", url_path="relatorios"),
    st.Page(ui.pagina_exportacoes, title="Exportações", icon=":material/download:", url_path="exportacoes"),
])
ui.barra_lateral()
navegacao.run()