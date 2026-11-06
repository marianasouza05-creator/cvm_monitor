"""
Interface do painel (Streamlit). Cinco páginas, como nos layouts de referência:
Dashboard, Novos Registros, Consulta, Relatórios e Exportações.

Regras de apresentação:
  * dados oficiais da CVM e dados comerciais internos ficam em blocos separados;
  * campo vazio na fonte aparece como "não disponível na fonte";
  * PF não tem CPF, e-mail, UF nem telefone nos dados abertos da CVM.
"""
import hashlib
import html
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from src import analytics as an
from src import storage
from src.config import AI_ENABLED, REPORTS_DIR, STATUS_COMERCIAL

CORES = {"Gestor PF": "#0F766E", "Gestor PJ": "#1D4ED8", "Consultor PF": "#F59E0B", "Consultor PJ": "#10B981"}
AZUL, TINTA, MUDO = "#1D4ED8", "#1F2A3C", "#6B7587"
PERIODOS = ["Últimos 7 dias", "Últimos 30 dias", "Mês atual", "Ano atual", "Tudo", "Personalizado"]
SITUACOES = ["Todas", "Em funcionamento", "Outras situações"]
NAO_DISPONIVEL = "<em class='m-nd'>não disponível na fonte</em>"

CSS = """
<style>
.block-container { padding-top: 2.2rem; max-width: 1560px; }
h1.m-titulo { font-size: 2.1rem; font-weight: 700; letter-spacing: -0.015em; color: #1F2A3C; margin: 0 0 .5rem 0; padding: 0; }
.m-chips { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 1.1rem 0; }
.m-chip { background: #E8EEFB; color: #1D4ED8; padding: 5px 14px; border-radius: 999px; font-size: .82rem; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 18px; background: #FFFFFF; border-color: #DDE3EE; }
.m-card { background: #FFFFFF; border: 1px solid #DDE3EE; border-radius: 18px; padding: 16px 22px 14px 22px; height: 100%; }
.m-card-title { font-weight: 700; font-size: 1.12rem; color: #1F2A3C; margin-bottom: 4px; }
.m-rotulo { font-size: .8rem; color: #6B7587; }
.m-valor { font-size: 1.9rem; font-weight: 700; line-height: 1.25; }
.m-sub { font-size: .78rem; color: #6B7587; min-height: 1.1em; }
.m-trio { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.m-trio span { display: block; font-size: .8rem; color: #6B7587; }
.m-trio b { font-size: 2rem; font-weight: 700; line-height: 1.2; }
.m-tile { background: #F8FAFD; border: 1px solid #DDE3EE; border-radius: 14px; padding: 10px 16px; }
.m-secao { font-size: 1.05rem; font-weight: 700; color: #1F2A3C; margin: 0 0 6px 0; }
.m-nd { color: #98A1B0; font-style: italic; }
.m-bloco { font-size: .78rem; font-weight: 600; color: #6B7587; margin: 14px 0 6px 0; padding-top: 10px; border-top: 1px solid #E6EBF3; }
.m-f { display: grid; grid-template-columns: 112px 1fr; gap: 8px; padding: 3px 0; font-size: .88rem; line-height: 1.4; }
.m-f > span { color: #6B7587; }
.m-f > div { color: #1F2A3C; overflow-wrap: anywhere; }
.m-badge { display: inline-block; background: #EEF2F8; color: #1F2A3C; border-radius: 999px; padding: 2px 10px; font-size: .78rem; margin: 0 6px 6px 0; }
.m-badge.ok { background: #DDF3EE; color: #0F766E; }
.m-badge.warn { background: #FEF3C7; color: #92400E; }
.m-alerta { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; font-size: .9rem; color: #1F2A3C; }
.m-ponto { width: 10px; height: 10px; border-radius: 50%; margin-top: 6px; flex: 0 0 10px; }
.m-ponto.ok { background: #10B981; } .m-ponto.aviso { background: #F59E0B; } .m-ponto.erro { background: #DC2626; }
section[data-testid="stSidebar"] { border-right: 1px solid #DDE3EE; }
a[data-testid="stSidebarNavLink"][aria-current="page"] { background: #DDF3EE; font-weight: 700; }
</style>
"""


def injetar_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------
@st.cache_resource
def _iniciar_banco() -> bool:
    storage.init_db()
    return True


@st.cache_data(show_spinner=False)
def _carregar(versao: tuple) -> pd.DataFrame:
    return an.preparar(storage.load_entidades_df())


def dados() -> pd.DataFrame:
    """Base de entidades; o cache se renova sozinho a cada carga ou edição comercial."""
    _iniciar_banco()
    return _carregar(storage.get_data_version())


def atualizar_base() -> None:
    """Roda o pipeline (baixa da CVM, compara, grava) e guarda a mensagem para a próxima tela."""
    from src.pipeline import run_update

    with st.spinner("Baixando e comparando os arquivos da CVM. Leva cerca de 30 segundos."):
        try:
            _, rel = run_update(use_ai=AI_ENABLED)
        except Exception as exc:
            st.session_state["_aviso"] = ("erro", f"A atualização falhou: {exc}")
        else:
            if rel["baseline"]:
                msg = (f"Base inicial carregada: {an.fmt_int(rel['total_registros'])} registros. "
                       "Os registros novos passam a aparecer a partir da próxima atualização.")
            else:
                n = rel["novos"]
                msg = (f"Atualização concluída: {n['gestores']} novos gestores, "
                       f"{n['consultores']} novos consultores, {rel['total_alterados']} alterações.")
            st.session_state["_aviso"] = ("ok", msg)
    st.rerun()


def barra_lateral() -> None:
    """Avisos pendentes e o botão de atualização (aparece em todas as páginas)."""
    aviso = st.session_state.pop("_aviso", None)
    if aviso:
        (st.success if aviso[0] == "ok" else st.error)(aviso[1])
    toast = st.session_state.pop("_toast", None)
    if toast:
        st.toast(toast)

    _iniciar_banco()
    with st.sidebar:
        st.divider()
        ultima = storage.last_ok_carga()
        if ultima:
            quando = datetime.fromisoformat(ultima["iniciada_em"]).strftime("%d/%m/%Y %H:%M")
            st.caption(f"Última atualização: {quando}")
        else:
            st.caption("Nenhuma atualização feita ainda.")
        if st.button("Atualizar base agora", type="primary", width="stretch"):
            atualizar_base()


def estado_vazio() -> None:
    """Tela mostrada enquanto o banco ainda não tem nenhuma carga."""
    cabecalho("Monitor de Gestores e Consultores — CVM", ["Dados abertos da CVM", "Atualização diária"])
    with st.container(border=True):
        st.markdown("<div class='m-secao'>A base ainda está vazia</div>", unsafe_allow_html=True)
        st.write("Clique em **Atualizar base agora** (menu lateral) para baixar os arquivos da CVM. "
                 "A primeira carga leva cerca de 30 segundos e forma a base de comparação: a partir da "
                 "segunda atualização o monitor passa a detectar registros novos.")


# ----------------------------------------------------------------------------
# Componentes visuais
# ----------------------------------------------------------------------------
def cabecalho(titulo: str, chips: list[str]) -> None:
    st.markdown(f"<h1 class='m-titulo'>{html.escape(titulo)}</h1>", unsafe_allow_html=True)
    st.markdown("<div class='m-chips'>" + "".join(f"<span class='m-chip'>{html.escape(c)}</span>" for c in chips)
                + "</div>", unsafe_allow_html=True)


def chips_padrao(ref: date) -> list[str]:
    return [f"Dados da CVM até {ref:%d/%m/%Y}", "Atualização diária", "Histórico de detecção"]


def kpi(rotulo: str, valor: str, sub: str = "", cor: str = TINTA) -> None:
    st.markdown(
        f"<div class='m-card'><div class='m-rotulo'>{html.escape(rotulo)}</div>"
        f"<div class='m-valor' style='color:{cor}'>{valor}</div><div class='m-sub'>{sub}</div></div>",
        unsafe_allow_html=True)


def card_segmento(titulo: str, numeros: dict, cor: str) -> None:
    trio = "".join(
        f"<div><span>{rot}</span><b style='color:{cor}'>{an.fmt_int(numeros[chave])}</b></div>"
        for rot, chave in (("Dia", "dia"), ("Mês", "mes"), ("Ano", "ano")))
    st.markdown(f"<div class='m-card'><div class='m-card-title'>{titulo}</div><div class='m-trio'>{trio}</div></div>",
                unsafe_allow_html=True)


def tile(rotulo: str, valor, cor: str = AZUL) -> None:
    st.markdown(f"<div class='m-tile'><div class='m-rotulo'>{html.escape(rotulo)}</div>"
                f"<div class='m-valor' style='color:{cor}'>{an.fmt_int(valor)}</div></div>", unsafe_allow_html=True)


def secao(titulo: str) -> None:
    st.markdown(f"<div class='m-secao'>{html.escape(titulo)}</div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Filtros globais
# ----------------------------------------------------------------------------
@dataclass
class Filtros:
    tipo: str = "Todos"
    pessoa: str = "Todas"
    ufs: tuple = ()
    busca: str = ""
    periodo: str = "Últimos 30 dias"
    inicio: date | None = None
    fim: date | None = None


def _memoria(chave: str, padrao):
    """Valor escolhido em outra página: mantém os filtros ao trocar de tela."""
    return st.session_state.get(f"_mem_{chave}", padrao)


def filtros_globais(df: pd.DataFrame, ref: date, pagina: str, com_periodo: bool = True) -> Filtros:
    """Barra de filtros no topo da página. Os valores acompanham o usuário entre as telas."""
    ufs_disponiveis = sorted(df["uf"].dropna().unique())
    f = Filtros()
    with st.container(border=True):
        larguras = [1.3, 1, 1, 1.4, 2.4] if com_periodo else [1, 1, 1.4, 2.8]
        colunas = st.columns(larguras)
        i = 0
        if com_periodo:
            padrao = _memoria("periodo", "Últimos 30 dias")
            f.periodo = colunas[i].selectbox("Período", PERIODOS, index=PERIODOS.index(padrao), key=f"{pagina}_periodo")
            i += 1
        tipos = ["Todos", "Gestor", "Consultor"]
        f.tipo = colunas[i].selectbox("Tipo", tipos, index=tipos.index(_memoria("tipo", "Todos")), key=f"{pagina}_tipo")
        pessoas = ["Todas", "PF", "PJ"]
        f.pessoa = colunas[i + 1].selectbox("Pessoa", pessoas, index=pessoas.index(_memoria("pessoa", "Todas")),
                                            key=f"{pagina}_pessoa")
        ufs_padrao = [u for u in _memoria("ufs", []) if u in ufs_disponiveis]
        f.ufs = tuple(colunas[i + 2].multiselect("UF", ufs_disponiveis, default=ufs_padrao, key=f"{pagina}_ufs",
                                                 help="UF existe só para pessoa jurídica; filtrar por UF oculta PF."))
        f.busca = colunas[i + 3].text_input("Buscar por nome ou CNPJ", value=_memoria("busca", ""), key=f"{pagina}_busca",
                                            placeholder="Nome, nome fantasia ou CNPJ")
        if com_periodo and f.periodo == "Personalizado":
            ini_padrao = _memoria("inicio", ref - timedelta(days=29))
            fim_padrao = _memoria("fim", ref)
            intervalo = st.date_input("Intervalo de datas", value=(ini_padrao, fim_padrao), format="DD/MM/YYYY",
                                      key=f"{pagina}_intervalo")
            if isinstance(intervalo, (tuple, list)) and len(intervalo) == 2:
                f.inicio, f.fim = intervalo
            elif isinstance(intervalo, (tuple, list)) and len(intervalo) == 1:
                f.inicio, f.fim = intervalo[0], None

    for campo, valor in (("periodo", f.periodo), ("tipo", f.tipo), ("pessoa", f.pessoa), ("ufs", list(f.ufs)),
                         ("busca", f.busca), ("inicio", f.inicio), ("fim", f.fim)):
        if valor is not None:
            st.session_state[f"_mem_{campo}"] = valor
    return f


def limites(f: Filtros, ref: date):
    return an.limites_periodo(f.periodo, ref, f.inicio, f.fim)


def aplicar(df: pd.DataFrame, f: Filtros, ref: date, *, com_periodo: bool = True, campo_data: str = "data_registro_dt",
            situacao: str = "Todas", so_detectados: bool = False) -> pd.DataFrame:
    return an.filtrar(
        df, tipo=f.tipo, pessoa=f.pessoa, ufs=list(f.ufs), busca=f.busca,
        periodo=limites(f, ref) if com_periodo else None, campo_data=campo_data,
        situacao=situacao, so_detectados=so_detectados)


# ----------------------------------------------------------------------------
# Gráficos
# ----------------------------------------------------------------------------
def _escala_cores() -> alt.Scale:
    return alt.Scale(domain=list(CORES), range=list(CORES.values()))


def grafico_linha(longo: pd.DataFrame, altura: int = 280) -> alt.Chart:
    return (
        alt.Chart(longo)
        .mark_line(point=alt.OverlayMarkDef(size=36), strokeWidth=2.4)
        .encode(
            x=alt.X("data:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0, grid=False)),
            y=alt.Y("novos:Q", title=None, axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("segmento:N", scale=_escala_cores(), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip("data:T", title="Data", format="%d/%m/%Y"), alt.Tooltip("segmento:N", title="Segmento"),
                     alt.Tooltip("novos:Q", title="Novos registros")],
        )
        .properties(height=altura)
    )


def grafico_barras(longo: pd.DataFrame, eixo: str, ordem: list, altura: int = 280) -> alt.Chart:
    return (
        alt.Chart(longo)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{eixo}:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("novos:Q", title=None, axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("segmento:N", scale=_escala_cores(), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip(f"{eixo}:N", title="Período"), alt.Tooltip("segmento:N", title="Segmento"),
                     alt.Tooltip("novos:Q", title="Novos registros")],
        )
        .properties(height=altura)
    )


# ----------------------------------------------------------------------------
# Tabela de registros + ficha da entidade
# ----------------------------------------------------------------------------
def _visao_tabela(df: pd.DataFrame) -> pd.DataFrame:
    texto = lambda s: s.fillna("—")  # noqa: E731
    return pd.DataFrame({
        "Tipo": df["tipo"],
        "Pessoa": df["pessoa"],
        "Nome / Razão social": df["nome"],
        "CNPJ": texto(df["cnpj"]),
        "Situação": texto(df["situacao"]),
        "UF": texto(df["uf"]),
        "Registro": df["data_registro_dt"],
        "Detectado em": df["detectado_em"],
        "Status comercial": df["status_comercial"].fillna("Sem tratamento"),
    })


def _selecionadas(chave: str, total: int) -> list[int]:
    estado = st.session_state.get(chave)
    try:
        linhas = list(estado["selection"]["rows"]) if estado else []
    except (KeyError, TypeError):
        linhas = []
    return [i for i in linhas if 0 <= i < total]


def _chave_tabela(pagina: str, df: pd.DataFrame) -> str:
    """Muda quando muda a lista exibida, o que zera a seleção antiga."""
    assinatura = hashlib.md5("|".join(df["chave_unica"].head(3000)).encode()).hexdigest()[:10]
    return f"tbl_{pagina}_{len(df)}_{assinatura}"


def tabela_com_ficha(df: pd.DataFrame, pagina: str, acoes: bool = False, altura: int = 560) -> None:
    """Tabela selecionável à esquerda e ficha completa da entidade à direita."""
    if df.empty:
        st.info("Nenhum registro encontrado com esses filtros. Amplie o período ou limpe a busca.")
        return
    df = df.sort_values(["data_registro_dt", "nome"], ascending=[False, True]).reset_index(drop=True)
    chave = _chave_tabela(pagina, df)
    escolhidas = _selecionadas(chave, len(df))

    if acoes:
        acoes_rapidas(df, escolhidas, pagina)

    esq, dir_ = st.columns([2.1, 1])
    with esq:
        evento = st.dataframe(
            _visao_tabela(df), key=chave, on_select="rerun", selection_mode="multi-row", hide_index=True,
            width="stretch", height=altura,
            column_config={
                "Registro": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Detectado em": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Nome / Razão social": st.column_config.TextColumn(width="large", pinned=True),
            })
        st.caption(f"{an.fmt_int(len(df))} registros. Clique numa linha para abrir a ficha.")
    with dir_:
        linhas = [i for i in evento.selection.rows if 0 <= i < len(df)]
        if linhas:
            if len(linhas) > 1:
                st.caption(f"{len(linhas)} linhas selecionadas. Mostrando a primeira.")
            ficha(df.iloc[linhas[0]])
        else:
            with st.container(border=True):
                secao("Ficha da entidade")
                st.caption("Selecione uma linha da tabela para ver os dados completos e registrar o contato comercial.")


def acoes_rapidas(df: pd.DataFrame, escolhidas: list[int], pagina: str) -> None:
    """Exportar CSV, copiar lista e marcar leads (nas linhas selecionadas)."""
    st.markdown("<div class='m-secao'>Ações rápidas</div>", unsafe_allow_html=True)
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    exportacao = an.preparar_exportacao(df, an.COLUNAS_EXPORT_PADRAO)
    c1.download_button("Exportar CSV", an.para_csv(exportacao), file_name=f"novos_registros_{date.today():%Y%m%d}.csv",
                       mime="text/csv", key=f"csv_{pagina}", width="stretch")
    with c2.popover("Copiar lista", width="stretch"):
        st.caption("Use o ícone de copiar no canto do bloco. Colunas separadas por tabulação (cola direto no Excel).")
        linhas = ["\t".join(["Nome", "CNPJ", "UF", "E-mail", "Site"])] + [
            "\t".join(str(v) if pd.notna(v) else "" for v in (r.nome, r.cnpj, r.uf, r.email, r.site))
            for r in df.head(300).itertuples()]
        st.code("\n".join(linhas), language=None)
        if len(df) > 300:
            st.caption(f"Mostrando as 300 primeiras de {an.fmt_int(len(df))}. Use Exportar CSV para a lista completa.")
    with c3.popover("Marcar leads", width="stretch"):
        if not escolhidas:
            st.caption("Selecione uma ou mais linhas na tabela para marcar.")
        else:
            st.caption(f"{len(escolhidas)} linha(s) selecionada(s).")
            status = st.selectbox("Status comercial", STATUS_COMERCIAL, key=f"status_massa_{pagina}")
            if st.button("Aplicar às selecionadas", key=f"aplicar_massa_{pagina}", type="primary"):
                storage.save_leads_status(list(df.iloc[escolhidas]["chave_unica"]), status)
                st.session_state["_toast"] = f"{len(escolhidas)} registro(s) marcados como {status}."
                st.rerun()


def _val(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or str(valor).strip() == "":
        return NAO_DISPONIVEL
    return html.escape(str(valor))


def _lista(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or not str(valor).strip():
        return NAO_DISPONIVEL
    return "<br>".join(html.escape(p.strip()) for p in str(valor).split(";") if p.strip())


def _site(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or not str(valor).strip():
        return NAO_DISPONIVEL
    texto = str(valor).strip()
    url = texto if texto.lower().startswith(("http://", "https://")) else f"https://{texto}"
    return f"<a href='{html.escape(url)}' target='_blank' rel='noopener'>{html.escape(texto)}</a>"


def _email(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or not str(valor).strip():
        return NAO_DISPONIVEL
    texto = str(valor).strip()
    return f"<a href='mailto:{html.escape(texto)}'>{html.escape(texto)}</a>"


def _linha(rotulo: str, valor_html: str) -> str:
    return f"<div class='m-f'><span>{rotulo}</span><div>{valor_html}</div></div>"


def ficha(r: pd.Series) -> None:
    """Ficha completa: dados oficiais da CVM e, separado, os dados comerciais internos."""
    ativo = bool(r["ativo"])
    with st.container(border=True):
        secao("Ficha da entidade")
        situacao_classe = "ok" if ativo else "warn"
        badges = (f"<span class='m-badge'>{r['tipo']}</span><span class='m-badge'>{r['pessoa']}</span>"
                  f"<span class='m-badge {situacao_classe}'>{html.escape(str(r['situacao'] or 'Situação não informada'))}</span>")
        st.markdown(f"<div style='font-weight:700;font-size:1.02rem;margin-bottom:6px'>{html.escape(r['nome'])}</div>{badges}",
                    unsafe_allow_html=True)

        st.markdown("<div class='m-bloco'>Dados oficiais da CVM</div>", unsafe_allow_html=True)
        linhas = []
        if r["pessoa"] == "PJ":
            linhas += [_linha("CNPJ", _val(r["cnpj"])), _linha("Nome fantasia", _val(r["nome_fantasia"]))]
        linhas += [_linha("Registro", _val(an.fmt_data(r["data_registro_dt"])) if pd.notna(r["data_registro_dt"]) else NAO_DISPONIVEL),
                   _linha("Categoria", _val(r["categoria"]))]
        if pd.notna(r["data_inicio_situacao"]) and r["data_inicio_situacao"]:
            linhas.append(_linha("Situação desde", _val(an.fmt_data(r["data_inicio_situacao"]))))
        if not ativo and r["data_cancelamento"]:
            linhas.append(_linha("Cancelamento", f"{_val(an.fmt_data(r['data_cancelamento']))}. {_val(r['motivo_cancelamento'])}"))
        if r["pessoa"] == "PJ":
            local = ", ".join(p for p in (r["municipio"], r["uf"]) if isinstance(p, str) and p)
            linhas += [
                _linha("Local", _val(local)), _linha("Endereço", _val(r["endereco"])), _linha("Telefone", _val(r["telefone"])),
                _linha("E-mail", _email(r["email"])), _linha("Site", _site(r["site"])),
                _linha("Diretores", _lista(r["diretores"])), _linha("Responsáveis", _lista(r["responsaveis"])),
                _linha("Sócios", _lista(r["socios"])),
                _linha("Controle", _val(r["controle_acionario"])),
            ]
            if pd.notna(r["patrimonio_liquido"]):
                ref_pl = f" (em {an.fmt_data(r['data_patrimonio'])})" if r["data_patrimonio"] else ""
                linhas.append(_linha("Patrimônio líq.", html.escape(an.fmt_moeda_curta(r["patrimonio_liquido"]) + ref_pl)))
        else:
            linhas.append(_linha("Site", _site(r["site"])))
        linhas += [_linha("Origem", _val(r["origem"])),
                   _linha("Detectado em", _val(an.fmt_data(r["detectado_em"])) if pd.notna(r["detectado_em"]) else
                          "<span style='color:#6B7587'>já constava na carga inicial</span>")]
        st.markdown("".join(linhas), unsafe_allow_html=True)
        if r["pessoa"] == "PF":
            st.caption("Pessoa física: a CVM não publica CPF, endereço, telefone nem e-mail nos dados abertos.")

        st.markdown("<div class='m-bloco'>Dados comerciais (internos)</div>", unsafe_allow_html=True)
        formulario_comercial(r)


def formulario_comercial(r: pd.Series) -> None:
    chave = r["chave_unica"]
    sufixo = hashlib.md5(chave.encode()).hexdigest()[:10]
    opcoes = ["Sem tratamento"] + STATUS_COMERCIAL
    atual = r["status_comercial"] if isinstance(r["status_comercial"], str) else "Sem tratamento"

    def texto(campo):
        valor = r[campo]
        return valor if isinstance(valor, str) else ""

    with st.form(f"lead_{sufixo}", border=False):
        status = st.selectbox("Status", opcoes, index=opcoes.index(atual) if atual in opcoes else 0)
        owner = st.text_input("Responsável comercial", value=texto("owner"))
        linkedin = st.text_input("LinkedIn", value=texto("linkedin"), placeholder="https://linkedin.com/...")
        contato = st.text_input("Contato adicional", value=texto("contato_extra"),
                                                                placeholder="E-mail, telefone ou site obtidos fora da CVM")
        obs = st.text_area("Observações", value=texto("observacoes"), height=90)
        if st.form_submit_button("Salvar dados comerciais", type="primary"):
            storage.save_lead(chave, None if status == "Sem tratamento" else status, owner.strip(), linkedin.strip(),
                              contato.strip(), obs.strip())
            st.session_state["_toast"] = "Dados comerciais salvos."
            st.rerun()


# ----------------------------------------------------------------------------
# Páginas
# ----------------------------------------------------------------------------
def _alertas(df: pd.DataFrame, ref: date) -> list[tuple[str, str]]:
    itens: list[tuple[str, str]] = []
    ultima = storage.last_carga()
    if ultima is None:
        itens.append(("erro", "Nenhuma atualização foi executada ainda."))
    elif ultima["status"] == "erro":
        itens.append(("erro", f"A última atualização falhou: {html.escape(ultima['mensagem'] or 'erro não informado')}"))
    else:
        dias = (date.today() - date.fromisoformat(ultima["data_carga"])).days
        if dias >= 2:
            itens.append(("aviso", f"A base está sem atualização há {dias} dias."))
        else:
            itens.append(("ok", f"Base atualizada em {date.fromisoformat(ultima['data_carga']):%d/%m/%Y}."))
    janelas = an.contar_janelas(df, ref)
    if janelas["sem_tratamento"]:
        itens.append(("aviso", f"{an.fmt_int(janelas['sem_tratamento'])} registros ativos dos últimos 30 dias ainda "
                               "não receberam tratamento comercial."))
    else:
        itens.append(("ok", "Nenhum registro ativo dos últimos 30 dias aguarda tratamento comercial."))
    return itens


def pagina_dashboard() -> None:
    df = dados()
    if df.empty:
        return estado_vazio()
    ref = an.data_referencia(df)
    cabecalho("Monitor de Gestores e Consultores — CVM", chips_padrao(ref))
    f = filtros_globais(df, ref, "dash")
    base = aplicar(df, f, ref, com_periodo=False)     # indicadores e cards respeitam tipo/pessoa/UF/busca
    janela = aplicar(df, f, ref)                      # gráficos e tabela respeitam também o período

    ultima = storage.last_ok_carga()
    totais = an.totais_ativos(base)
    hoje_detectados = an.detectados_hoje(base)
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        kpi("Última atualização da base", an.fmt_data(ultima["data_carga"]) if ultima else "—",
            f"Dados da CVM até {ref:%d/%m/%Y}")
    with k2:
        kpi("Total de gestores ativos", an.fmt_int(totais["Gestor"]["total"]),
            f"PJ {an.fmt_int(totais['Gestor']['PJ'])}, PF {an.fmt_int(totais['Gestor']['PF'])}")
    with k3:
        kpi("Total de consultores ativos", an.fmt_int(totais["Consultor"]["total"]),
            f"PJ {an.fmt_int(totais['Consultor']['PJ'])}, PF {an.fmt_int(totais['Consultor']['PF'])}")
    with k4:
        nunca_detectou = bool((df["baseline"] == 0).sum() == 0)
        kpi("Novos detectados hoje", an.fmt_int(hoje_detectados),
            "Base inicial carregada; novos aparecem na próxima atualização" if nunca_detectou else "Registros que o monitor viu pela 1ª vez hoje",
            cor=AZUL)

    st.write("")
    cartoes = an.cards_credenciamento(base, ref)
    titulos = {("Gestor", "PF"): "Novos gestores PF", ("Gestor", "PJ"): "Novos gestores PJ",
               ("Consultor", "PF"): "Novos consultores PF", ("Consultor", "PJ"): "Novos consultores PJ"}
    linha1, linha2 = st.columns(2), st.columns(2)
    for coluna, seg in zip(linha1 + linha2, an.SEGMENTOS):
        with coluna:
            card_segmento(titulos[seg], cartoes[seg], CORES[f"{seg[0]} {seg[1]}"])
    st.caption(f"Dia, mês e ano contam a data de registro na CVM, até {ref:%d/%m/%Y} (último dia com registros na base).")

    st.write("")
    ini, fim = limites(f, ref)
    if ini is None:
        ini = ref - timedelta(days=364)
    fim = fim or ref
    ini = max(ini, fim - timedelta(days=400))
    esq, dir_ = st.columns([1.15, 1])
    with esq, st.container(border=True):
        secao("Evolução diária de novos registros")
        st.altair_chart(grafico_linha(an.serie_diaria(base, ini, fim)), width="stretch")
    with dir_, st.container(border=True):
        secao("Últimos registros detectados")
        ultimos = janela.sort_values(["data_registro_dt", "nome"], ascending=[False, True]).head(10)
        if ultimos.empty:
            st.caption("Nenhum registro no período e filtros escolhidos.")
        else:
            st.dataframe(
                pd.DataFrame({"Tipo": ultimos["tipo"], "Pessoa": ultimos["pessoa"], "Nome": ultimos["nome"],
                              "Data": ultimos["data_registro_dt"]}),
                hide_index=True, width="stretch", height=280,
                column_config={"Data": st.column_config.DateColumn(format="DD/MM/YYYY")})

    esq2, dir2 = st.columns([1.15, 1])
    with esq2, st.container(border=True):
        secao(f"Novos registros por mês em {ref.year}")
        st.altair_chart(grafico_barras(an.serie_mensal(base, ref.year), "mes", an.MESES), width="stretch")
    with dir2, st.container(border=True):
        secao("Alertas e atalhos")
        st.markdown("".join(f"<div class='m-alerta'><span class='m-ponto {n}'></span><span>{t}</span></div>"
                            for n, t in _alertas(df, ref)), unsafe_allow_html=True)
        exportacao = an.preparar_exportacao(janela, an.COLUNAS_EXPORT_PADRAO)
        st.download_button(f"Exportar lista do período ({an.fmt_int(len(janela))} registros)", an.para_csv(exportacao),
                           file_name=f"registros_{date.today():%Y%m%d}.csv", mime="text/csv", key="csv_dash")


def pagina_novos() -> None:
    df = dados()
    if df.empty:
        return estado_vazio()
    ref = an.data_referencia(df)
    cabecalho("Novos Registros", chips_padrao(ref))
    f = filtros_globais(df, ref, "novos")

    with st.container(border=True):
        secao("Novos registros: consulta inteligente")
        c1, c2 = st.columns([1.6, 1])
        criterio = c1.radio("Contar por", ["Data do registro (CVM)", "Data de detecção (monitor)"], horizontal=True,
                            key="novos_criterio", help="A data de detecção só existe para registros que o monitor viu depois da carga inicial.")
        situacao = c2.selectbox("Situação cadastral", SITUACOES, key="novos_situacao")
        por_deteccao = criterio.startswith("Data de detecção")
        campo = "detectado_em" if por_deteccao else "data_registro_dt"
        # Detecção acontece "hoje"; registro na CVM é medido a partir do último dia com registros.
        ref_c = date.today() if por_deteccao else ref

        base = aplicar(df, f, ref_c, com_periodo=False, situacao=situacao, so_detectados=por_deteccao)
        base_ativa = aplicar(df, f, ref_c, com_periodo=False, so_detectados=por_deteccao)
        janelas = an.contar_janelas(base_ativa, ref_c, campo)
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            tile("Hoje" if ref_c == date.today() else f"Em {ref_c:%d/%m}", janelas["hoje"])
        with t2:
            tile("7 dias", janelas["7d"], "#F59E0B")
        with t3:
            tile("30 dias", janelas["30d"], "#F59E0B")
        with t4:
            tile("Sem tratamento", janelas["sem_tratamento"], "#F59E0B")
        st.caption("Sem tratamento: registros ativos dos últimos 30 dias que ainda não têm status comercial.")

        lista = aplicar(df, f, ref_c, campo_data=campo, situacao=situacao, so_detectados=por_deteccao)
        if por_deteccao and base.empty:
            st.info("O monitor ainda não detectou registros novos. Eles aparecem depois da segunda atualização da base.")
        else:
            tabela_com_ficha(lista, "novos", acoes=True)


def pagina_consulta() -> None:
    df = dados()
    if df.empty:
        return estado_vazio()
    ref = an.data_referencia(df)
    cabecalho("Consulta", ["Toda a base da CVM", "Busca por nome ou CNPJ", "Inclui registros cancelados"])
    f = filtros_globais(df, ref, "consulta", com_periodo=False)
    with st.container(border=True):
        secao("Consulta à base completa")
        situacao = st.selectbox("Situação cadastral", SITUACOES, index=1, key="consulta_situacao")
        lista = aplicar(df, f, ref, com_periodo=False, situacao=situacao)
        tabela_com_ficha(lista, "consulta")


def pagina_relatorios() -> None:
    df = dados()
    if df.empty:
        return estado_vazio()
    ref = an.data_referencia(df)
    cabecalho("Relatórios", chips_padrao(ref))
    t_dia, t_mes, t_ano, t_leads, t_hist = st.tabs(
        ["Relatório do dia", "Mensal", "Comparativo anual", "Leads sem tratamento", "Histórico e alterações"])

    with t_dia:
        arquivos = sorted(REPORTS_DIR.glob("relatorio_*.md"), reverse=True)
        if not arquivos:
            st.info("Ainda não há relatório gerado. Clique em Atualizar base agora.")
        else:
            escolhido = st.selectbox("Data do relatório", arquivos, format_func=lambda p: p.stem.replace("relatorio_", ""))
            with st.container(border=True):
                st.markdown(escolhido.read_text(encoding="utf-8"))

    with t_mes:
        anos = sorted(df["data_registro_dt"].dt.year.dropna().astype(int).unique(), reverse=True)
        ano = st.selectbox("Ano", anos, index=anos.index(ref.year) if ref.year in anos else 0, key="rel_ano")
        tabela = an.tabela_mensal(df, ano)
        esq, dir_ = st.columns([1, 1.3])
        with esq:
            st.dataframe(tabela, width="stretch", height=480)
            st.download_button("Baixar tabela (CSV)", an.para_csv(tabela.reset_index()), file_name=f"mensal_{ano}.csv",
                               mime="text/csv", key="csv_mensal")
        with dir_, st.container(border=True):
            secao(f"Novos registros por mês em {ano}")
            st.altair_chart(grafico_barras(an.serie_mensal(df, ano), "mes", an.MESES, 400), width="stretch")

    with t_ano:
        comp = an.comparativo_anual(df)
        esq, dir_ = st.columns([1, 1.3])
        with esq:
            st.dataframe(comp, width="stretch", height=480)
            st.download_button("Baixar comparativo (CSV)", an.para_csv(comp.reset_index()), file_name="comparativo_anual.csv",
                               mime="text/csv", key="csv_anual")
        with dir_, st.container(border=True):
            secao("Novos registros por ano")
            longo = (comp.drop(columns="Total").head(15).reset_index()
                     .melt(id_vars="Ano", var_name="segmento", value_name="novos"))
            longo["Ano"] = longo["Ano"].astype(str)
            st.altair_chart(grafico_barras(longo, "Ano", sorted(longo["Ano"].unique()), 400), width="stretch")
        st.caption("Contagem por data de registro na CVM, incluindo quem já cancelou. Mostra os 15 anos mais recentes no gráfico.")

    with t_leads:
        limite = ref - timedelta(days=89)
        pendentes = df[df["ativo"] & df["sem_tratamento"] & (df["data_registro_dt"] >= pd.Timestamp(limite))]
        st.write(f"**{an.fmt_int(len(pendentes))}** registros ativos dos últimos 90 dias ainda sem status comercial.")
        tabela_com_ficha(pendentes, "leads", acoes=True, altura=480)

    with t_hist:
        st.markdown("**Atualizações da base**")
        cargas = storage.get_cargas(30)
        if cargas.empty:
            st.caption("Nenhuma atualização registrada.")
        else:
            cargas["baseline"] = cargas["baseline"].map({1: "Carga inicial", 0: "Atualização"})
            st.dataframe(cargas[["data_carga", "iniciada_em", "baseline", "total", "novos", "alterados", "removidos", "status", "mensagem"]]
                         .rename(columns={"data_carga": "Data", "iniciada_em": "Início", "baseline": "Tipo", "total": "Registros",
                                          "novos": "Novos", "alterados": "Alterados", "removidos": "Saíram da fonte",
                                          "status": "Status", "mensagem": "Mensagem"}),
                         hide_index=True, width="stretch")
        st.markdown("**Alterações cadastrais recentes**")
        alteracoes = storage.get_alteracoes(200)
        if alteracoes.empty:
            st.caption("Nenhuma alteração de nome, situação ou contato detectada até agora.")
        else:
            st.dataframe(alteracoes.rename(columns={"data": "Data", "tipo": "Tipo", "pessoa": "Pessoa", "nome": "Nome",
                                                    "campo": "Campo", "valor_anterior": "Antes", "valor_novo": "Depois"}),
                         hide_index=True, width="stretch")


def pagina_exportacoes() -> None:
    df = dados()
    if df.empty:
        return estado_vazio()
    ref = an.data_referencia(df)
    cabecalho("Exportações", chips_padrao(ref))
    f = filtros_globais(df, ref, "export")

    with st.container(border=True):
        secao("Montar arquivo")
        c1, c2 = st.columns([1.2, 1])
        origem = c1.radio("Lista", ["Registros do período e filtros", "Leads sem tratamento (ativos, últimos 90 dias)",
                                    "Base completa com os filtros (sem período)"], key="export_origem")
        situacao = c2.selectbox("Situação cadastral", SITUACOES, key="export_situacao")
        if origem.startswith("Registros"):
            lista = aplicar(df, f, ref, situacao=situacao)
        elif origem.startswith("Leads"):
            lista = aplicar(df, f, ref, com_periodo=False, situacao="Em funcionamento")
            lista = lista[lista["sem_tratamento"] & (lista["data_registro_dt"] >= pd.Timestamp(ref - timedelta(days=89)))]
        else:
            lista = aplicar(df, f, ref, com_periodo=False, situacao=situacao)

        escolhidas = st.multiselect(
            "Colunas", list(an.COLUNAS_EXPORT), default=an.COLUNAS_EXPORT_PADRAO, format_func=lambda c: an.COLUNAS_EXPORT[c],
            help="Dados da CVM e dados comerciais internos podem ser misturados no arquivo; os nomes das colunas indicam a origem.")
        st.write(f"**{an.fmt_int(len(lista))}** registros no arquivo.")
        if lista.empty or not escolhidas:
            st.info("Nada para exportar. Ajuste os filtros ou escolha ao menos uma coluna.")
        else:
            saida = an.preparar_exportacao(lista.sort_values("data_registro_dt", ascending=False), escolhidas)
            st.dataframe(saida.head(15), hide_index=True, width="stretch")
            st.caption("Prévia das 15 primeiras linhas.")
            b1, b2, _ = st.columns([1, 1, 3])
            carimbo = f"{date.today():%Y%m%d}"
            b1.download_button("Baixar CSV", an.para_csv(saida), file_name=f"monitor_cvm_{carimbo}.csv", mime="text/csv",
                               key="dl_csv", width="stretch")
            b2.download_button("Baixar Excel", an.para_xlsx(saida), file_name=f"monitor_cvm_{carimbo}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_xlsx",
                               type="primary", width="stretch")