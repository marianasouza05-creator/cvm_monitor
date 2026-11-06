"""
Cálculos do painel — funções puras sobre um DataFrame de entidades.
Nada aqui depende do Streamlit, então tudo é testável.

Duas datas, como no briefing:
  data_registro_dt  -> data do registro na CVM (fonte)
  detectado_em      -> data em que o monitor detectou a entidade
                       (vazio para quem já estava na carga inicial)

Os cards Dia / Mês / Ano usam a DATA DE REGISTRO. Assim funcionam desde a
primeira carga, sem esperar o histórico de detecção se formar.
"""
import io
import re
import unicodedata
from datetime import date, timedelta

import pandas as pd

from src.config import SITUACAO_ATIVA

SEGMENTOS = [("Gestor", "PF"), ("Gestor", "PJ"), ("Consultor", "PF"), ("Consultor", "PJ")]
NOMES_SEGMENTOS = [f"{t} {p}" for t, p in SEGMENTOS]
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

COLUNAS_EXPORT = {
    "tipo": "Tipo",
    "pessoa": "Pessoa",
    "nome": "Nome / Razão social",
    "nome_fantasia": "Nome fantasia",
    "cnpj": "CNPJ",
    "situacao": "Situação",
    "data_registro_dt": "Data de registro (CVM)",
    "detectado_em": "Detectado em (monitor)",
    "uf": "UF",
    "municipio": "Município",
    "telefone": "Telefone",
    "email": "E-mail",
    "site": "Site",
    "diretores": "Diretores (CVM)",
    "responsaveis": "Responsáveis (CVM)",
    "socios": "Sócios (CVM)",
    "categoria": "Categoria",
    "patrimonio_liquido": "Patrimônio líquido (R$)",
    "origem": "Origem (dataset)",
    "status_comercial": "Status comercial",
    "owner": "Responsável comercial",
    "observacoes": "Observações",
}
COLUNAS_EXPORT_PADRAO = [
    "tipo", "pessoa", "nome", "cnpj", "situacao", "data_registro_dt", "uf", "municipio",
    "telefone", "email", "site", "diretores", "status_comercial",
]


# ----------------------------------------------------------------------------
# Preparação e filtros
# ----------------------------------------------------------------------------
def fold(texto) -> str:
    """Minúsculas e sem acentos, para busca tolerante."""
    if texto is None or (isinstance(texto, float) and texto != texto):
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta colunas derivadas usadas por todo o painel."""
    df = df.copy()
    df["data_registro_dt"] = pd.to_datetime(df["data_registro"], errors="coerce")
    df["primeira_deteccao_dt"] = pd.to_datetime(df["primeira_deteccao"], errors="coerce")
    df["detectado_em"] = df["primeira_deteccao_dt"].where(df["baseline"] == 0)
    df["ativo"] = df["situacao"] == SITUACAO_ATIVA
    df["segmento"] = df["tipo"] + " " + df["pessoa"]
    df["sem_tratamento"] = df["status_comercial"].isna()

    cnpj = df["cnpj"].fillna("").astype(str)
    texto = df["nome"].fillna("").astype(str) + " " + df["nome_fantasia"].fillna("").astype(str) + " " \
        + cnpj + " " + cnpj.str.replace(r"\D", "", regex=True)
    df["busca_txt"] = texto.map(fold)
    return df


def data_referencia(df: pd.DataFrame, hoje: date | None = None) -> date:
    """Último dia (até hoje) com registros na base. Se não há dados, hoje."""
    hoje = hoje or date.today()
    if df.empty:
        return hoje
    datas = df["data_registro_dt"].dropna()
    datas = datas[datas <= pd.Timestamp(hoje)]
    return datas.max().date() if not datas.empty else hoje


def limites_periodo(nome: str, ref: date, inicio: date | None = None, fim: date | None = None):
    """(inicio, fim) de um período nomeado, relativo à data de referência. (None, None) = sem limite."""
    if nome == "Últimos 7 dias":
        return ref - timedelta(days=6), ref
    if nome == "Últimos 30 dias":
        return ref - timedelta(days=29), ref
    if nome == "Mês atual":
        return ref.replace(day=1), ref
    if nome == "Ano atual":
        return date(ref.year, 1, 1), ref
    if nome == "Personalizado":
        return inicio, fim
    return None, None


def filtrar(
    df: pd.DataFrame,
    *,
    tipo: str = "Todos",
    pessoa: str = "Todas",
    ufs: list[str] | None = None,
    busca: str = "",
    periodo: tuple | None = None,
    campo_data: str = "data_registro_dt",
    situacao: str = "Todas",
    so_detectados: bool = False,
) -> pd.DataFrame:
    """
    Aplica os filtros globais. UF só existe para PJ: filtrar por UF esconde PF.
    situacao: 'Todas' | 'Em funcionamento' | 'Outras situações'.
    so_detectados: só entidades detectadas pelo monitor (exclui a carga inicial).
    """
    mascara = pd.Series(True, index=df.index)
    if tipo != "Todos":
        mascara &= df["tipo"] == tipo
    if pessoa != "Todas":
        mascara &= df["pessoa"] == pessoa
    if ufs:
        mascara &= df["uf"].isin(ufs)
    if busca and busca.strip():
        mascara &= df["busca_txt"].str.contains(re.escape(fold(busca.strip())), regex=True)
    if situacao == "Em funcionamento":
        mascara &= df["ativo"]
    elif situacao == "Outras situações":
        mascara &= ~df["ativo"]
    if so_detectados:
        mascara &= df["baseline"] == 0
    if periodo:
        inicio, fim = periodo
        coluna = df[campo_data]
        if inicio is not None:
            mascara &= coluna >= pd.Timestamp(inicio)
        if fim is not None:
            mascara &= coluna <= pd.Timestamp(fim)
    return df[mascara]


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------
def totais_ativos(df: pd.DataFrame) -> dict:
    """{'Gestor': {'PF': n, 'PJ': n, 'total': n}, 'Consultor': {...}} só de ativos."""
    ativos = df[df["ativo"]]
    saida = {}
    for tipo in ("Gestor", "Consultor"):
        sub = ativos[ativos["tipo"] == tipo]
        pf, pj = int((sub["pessoa"] == "PF").sum()), int((sub["pessoa"] == "PJ").sum())
        saida[tipo] = {"PF": pf, "PJ": pj, "total": pf + pj}
    return saida


def cards_credenciamento(df: pd.DataFrame, ref: date) -> dict:
    """
    Novos credenciamentos por segmento: {('Gestor','PF'): {'dia': n, 'mes': n, 'ano': n}, ...}
    'dia' = registrados na data de referência; 'mes'/'ano' = do início do mês/ano até ela.
    """
    d = df["data_registro_dt"]
    ref_ts = pd.Timestamp(ref)
    no_dia = d == ref_ts
    no_mes = (d.dt.year == ref.year) & (d.dt.month == ref.month) & (d <= ref_ts)
    no_ano = (d.dt.year == ref.year) & (d <= ref_ts)

    saida = {}
    for tipo, pessoa in SEGMENTOS:
        seg = (df["tipo"] == tipo) & (df["pessoa"] == pessoa)
        saida[(tipo, pessoa)] = {
            "dia": int((seg & no_dia).sum()),
            "mes": int((seg & no_mes).sum()),
            "ano": int((seg & no_ano).sum()),
        }
    return saida


def contar_janelas(df: pd.DataFrame, ref: date, campo: str = "data_registro_dt") -> dict:
    """Contagens para os indicadores 'Hoje / 7 dias / 30 dias' e 'Sem tratamento' (ativos, 30 dias)."""
    d = df[campo]
    ref_ts = pd.Timestamp(ref)
    na_janela = lambda dias: (d >= ref_ts - pd.Timedelta(days=dias - 1)) & (d <= ref_ts)  # noqa: E731
    return {
        "hoje": int((d == ref_ts).sum()),
        "7d": int(na_janela(7).sum()),
        "30d": int(na_janela(30).sum()),
        "sem_tratamento": int((na_janela(30) & df["ativo"] & df["sem_tratamento"]).sum()),
    }


def detectados_hoje(df: pd.DataFrame, hoje: date | None = None) -> int:
    """Entidades que o monitor detectou hoje (não conta a carga inicial)."""
    hoje = hoje or date.today()
    return int((df["detectado_em"].dt.date == hoje).sum()) if not df.empty else 0


# ----------------------------------------------------------------------------
# Séries para gráficos (formato longo: data/mês, segmento, novos)
# ----------------------------------------------------------------------------
def serie_diaria(df: pd.DataFrame, inicio: date, fim: date) -> pd.DataFrame:
    """Novos registros por dia e segmento entre inicio e fim, com zeros nos dias vazios."""
    datas = pd.date_range(inicio, fim, freq="D")
    base = pd.MultiIndex.from_product([datas, NOMES_SEGMENTOS], names=["data", "segmento"])
    janela = df[(df["data_registro_dt"] >= pd.Timestamp(inicio)) & (df["data_registro_dt"] <= pd.Timestamp(fim))]
    if janela.empty:
        return pd.Series(0, index=base, name="novos").reset_index()
    cont = janela.groupby([janela["data_registro_dt"].dt.normalize(), "segmento"]).size()
    cont.index.names = ["data", "segmento"]
    return cont.reindex(base, fill_value=0).rename("novos").reset_index()


def serie_mensal(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Novos registros por mês (Jan..Dez) e segmento no ano indicado."""
    base = pd.MultiIndex.from_product([range(1, 13), NOMES_SEGMENTOS], names=["mes_num", "segmento"])
    do_ano = df[df["data_registro_dt"].dt.year == ano]
    if do_ano.empty:
        out = pd.Series(0, index=base, name="novos").reset_index()
    else:
        cont = do_ano.groupby([do_ano["data_registro_dt"].dt.month, "segmento"]).size()
        cont.index.names = ["mes_num", "segmento"]
        out = cont.reindex(base, fill_value=0).rename("novos").reset_index()
    out["mes"] = out["mes_num"].map(lambda m: MESES[m - 1])
    return out


def tabela_mensal(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Linhas = meses, colunas = segmentos + Total."""
    longo = serie_mensal(df, ano)
    tabela = longo.pivot(index="mes_num", columns="segmento", values="novos")[NOMES_SEGMENTOS]
    tabela.index = [MESES[m - 1] for m in tabela.index]
    tabela.index.name = "Mês"
    tabela["Total"] = tabela.sum(axis=1)
    return tabela


def comparativo_anual(df: pd.DataFrame) -> pd.DataFrame:
    """Linhas = anos, colunas = segmentos + Total (por data de registro)."""
    com_data = df.dropna(subset=["data_registro_dt"])
    if com_data.empty:
        return pd.DataFrame(columns=NOMES_SEGMENTOS + ["Total"])
    tabela = (
        com_data.groupby([com_data["data_registro_dt"].dt.year, "segmento"]).size()
        .unstack(fill_value=0).reindex(columns=NOMES_SEGMENTOS, fill_value=0)
    )
    tabela["Total"] = tabela.sum(axis=1)
    tabela.index = tabela.index.astype(int)
    tabela.index.name = "Ano"
    return tabela.sort_index(ascending=False)


# ----------------------------------------------------------------------------
# Formatação (pt-BR) e exportação
# ----------------------------------------------------------------------------
def fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def fmt_data(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return pd.Timestamp(valor).strftime("%d/%m/%Y")


def fmt_moeda_curta(valor) -> str:
    """12637515.26 -> 'R$ 12,6 mi'."""
    if valor is None or pd.isna(valor):
        return "—"
    v = float(valor)
    if v >= 1e9:
        return f"R$ {v / 1e9:.1f} bi".replace(".", ",")
    if v >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    return f"R$ {v:,.0f}".replace(",", ".")


def preparar_exportacao(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Seleciona e renomeia colunas para o arquivo exportado."""
    colunas = [c for c in colunas if c in COLUNAS_EXPORT]
    out = df[colunas].copy()
    for c in ("data_registro_dt", "detectado_em"):
        if c in out:
            out[c] = pd.to_datetime(out[c]).dt.normalize()
    return out.rename(columns=COLUNAS_EXPORT)


def para_csv(df: pd.DataFrame) -> bytes:
    """CSV para Excel brasileiro: separador ';', vírgula decimal, UTF-8 com BOM."""
    return df.to_csv(index=False, sep=";", decimal=",", date_format="%d/%m/%Y").encode("utf-8-sig")


def para_xlsx(df: pd.DataFrame, nome_aba: str = "Registros") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl", datetime_format="DD/MM/YYYY") as escritor:
        df.to_excel(escritor, index=False, sheet_name=nome_aba)
        planilha = escritor.sheets[nome_aba]
        planilha.freeze_panes = "A2"
        for coluna in planilha.columns:  # largura aproximada pelo conteúdo
            maior = max((len(str(c.value)) for c in coluna[:200] if c.value is not None), default=8)
            planilha.column_dimensions[coluna[0].column_letter].width = min(max(maior + 2, 10), 60)
    return buffer.getvalue()