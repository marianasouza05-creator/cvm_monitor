"""
Coletor de dados REAIS da CVM — Portal de Dados Abertos.

Fontes oficiais (sem login, sem scraping):

  Consultores de Valores Mobiliários:
    https://dados.cvm.gov.br/dados/CONSULTOR_VLMOB/CAD/DADOS/cad_consultor_vlmob.zip

  Administradores de Carteira (inclui Gestores de Recursos):
    https://dados.cvm.gov.br/dados/ADM_CART/CAD/DADOS/cad_adm_cart.zip

Formato: ZIP com vários CSVs, separador ";", encoding ISO-8859-1.

Arquivos usados em cada ZIP:
  _pj.csv      pessoa jurídica (CNPJ, razão social, endereço, e-mail, site...)
  _pf.csv      pessoa física (só nome, datas e situação — a CVM NÃO publica CPF)
  _diretor.csv / _resp.csv / _socios.csv   pessoas ligadas ao CNPJ (opcionais)

--- CHAVE ÚNICA ---
O arquivo é um HISTÓRICO (inclui cancelados) e a CVM não publica um código
numérico por entidade. A chave de identidade é composta:

    chave_unica = f"{identificador}|{data_registro}|{tipo}"

onde identificador é o CNPJ (PJ) ou o NOME (PF). Assim, mudar a razão social
não gera "novo cadastro", mas um recadastramento (nova data de registro após
cancelamento) conta como novo. O tipo entra na chave porque a mesma empresa
pode ser Gestora e Consultora ao mesmo tempo.

--- FILTRO DE GESTORES ---
O arquivo de administradores mistura "Gestor de Carteira" com "Administrador
Fiduciário". Só interessa gestor: filtra CATEG_REG contendo "Gestor de Carteira".

--- DADOS FALTANTES ---
Campo vazio na fonte vira None (a interface mostra "não disponível na fonte").
"""
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import requests

from src.config import RAW_DIR, SITUACAO_ATIVA
from src.logger_config import get_logger

logger = get_logger(__name__)

CONSULTOR_URL = "https://dados.cvm.gov.br/dados/CONSULTOR_VLMOB/CAD/DADOS/cad_consultor_vlmob.zip"
ADM_CART_URL = "https://dados.cvm.gov.br/dados/ADM_CART/CAD/DADOS/cad_adm_cart.zip"

REQUEST_TIMEOUT = 60
CATEG_GESTOR = "Gestor de Carteira"
SEM_DIRETOR = "-- SEM DIRETOR RESPONSÁVEL --"

# Campos de cada registro normalizado (ordem usada em todo o sistema).
CAMPOS = [
    "chave_unica", "tipo", "pessoa", "nome", "nome_fantasia", "cnpj",
    "situacao", "data_registro", "data_cancelamento", "motivo_cancelamento",
    "data_inicio_situacao", "categoria", "subcategoria", "controle_acionario",
    "uf", "municipio", "endereco", "cep", "telefone", "email", "site",
    "patrimonio_liquido", "data_patrimonio", "diretores", "responsaveis",
    "socios", "origem",
]
REQUIRED_FIELDS = CAMPOS

DATASETS = {
    "Consultor": {
        "url": CONSULTOR_URL,
        "env": "CVM_CONSULTOR_ZIP_PATH",
        "zip": "cad_consultor_vlmob.zip",
        "prefix": "cad_consultor_vlmob",
        "pf_nome": "NOME",
        "filtrar_gestor": False,
        "origem": "Consultores de Valores Mobiliários",
    },
    "Gestor": {
        "url": ADM_CART_URL,
        "env": "CVM_ADM_CART_ZIP_PATH",
        "zip": "cad_adm_cart.zip",
        "prefix": "cad_adm_cart",
        "pf_nome": "ADMIN",
        "filtrar_gestor": True,
        "origem": "Administradores de Carteira",
    },
}


class FonteCVMError(Exception):
    """Erro ao baixar ou interpretar um arquivo da CVM."""


# ----------------------------------------------------------------------------
# Download / leitura
# ----------------------------------------------------------------------------
def _download(url: str, dest: Path) -> Path:
    logger.info("Baixando %s", url)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise FonteCVMError(f"Falha ao baixar {url}: {exc}") from exc

    dest.write_bytes(resp.content)
    logger.info("Download concluído: %s (%d bytes)", dest.name, len(resp.content))
    return dest


def _get_zip_path(url: str, env_override: str, filename: str) -> Path:
    """Usa o ZIP local apontado por `env_override` (testes/offline) ou baixa da CVM."""
    override = os.getenv(env_override)
    if override:
        path = Path(override)
        if not path.exists():
            raise FonteCVMError(f"Arquivo local indicado em {env_override} não existe: {path}")
        logger.info("Usando arquivo local (override via %s): %s", env_override, path)
        return path
    return _download(url, RAW_DIR / filename)


def _extract(zip_path: Path, member: str, extract_to: Path) -> Path:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if member not in names:
                raise FonteCVMError(
                    f"Arquivo '{member}' não encontrado dentro de {zip_path.name}. "
                    f"Conteúdo do zip: {names}. A CVM pode ter mudado a estrutura."
                )
            zf.extract(member, extract_to)
    except zipfile.BadZipFile as exc:
        raise FonteCVMError(f"{zip_path.name} não é um ZIP válido: {exc}") from exc
    return extract_to / member


def _read_csv(path: Path, required_cols: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="ISO-8859-1", dtype=str, keep_default_na=False)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise FonteCVMError(
            f"Formato inesperado em {path.name}: colunas ausentes {missing}. "
            f"Colunas encontradas: {list(df.columns)}. A CVM pode ter alterado o arquivo."
        )
    return df


def _ler_opcional(zip_path: Path, member: str, tmp: Path, required: list[str]) -> pd.DataFrame | None:
    """Tabelas auxiliares (diretores etc.) não derrubam a coleta se faltarem."""
    try:
        return _read_csv(_extract(zip_path, member, tmp), required)
    except FonteCVMError as exc:
        logger.warning("Arquivo auxiliar indisponível, seguindo sem ele: %s", exc)
        return None


# ----------------------------------------------------------------------------
# Normalização
# ----------------------------------------------------------------------------
def _col(df: pd.DataFrame, nome: str) -> pd.Series:
    """Coluna como texto sem espaços; série vazia se a coluna não existir."""
    if nome in df.columns:
        return df[nome].fillna("").astype(str).str.strip()
    return pd.Series([""] * len(df), index=df.index, dtype="object")


def _mapa_por_cnpj(df: pd.DataFrame | None, col_valor: str) -> dict[str, str]:
    """Agrupa valores por CNPJ: {cnpj: 'A; B; C'} (sem repetir, sem 'sem diretor')."""
    if df is None or df.empty:
        return {}
    agrupado: dict[str, list[str]] = {}
    for cnpj, valor in zip(_col(df, "CNPJ"), _col(df, col_valor)):
        if not cnpj or not valor or valor == SEM_DIRETOR:
            continue
        lista = agrupado.setdefault(cnpj, [])
        if valor not in lista:
            lista.append(valor)
    return {cnpj: "; ".join(itens) for cnpj, itens in agrupado.items()}


def _resumir_cargo(cargo: str) -> str:
    """'DIRETOR RESPONSÁVEL PELA GESTÃO DE RISCO' -> 'Gestão de risco'."""
    texto = re.sub(r"^DIRETOR(A)? (RESPONSÁVEL )?(PELA|PELO|PELAS|PELOS|DE|DA|DO)\s+", "", cargo.strip(), flags=re.I)
    texto = texto.strip()
    if texto.isupper():
        texto = texto[:1] + texto[1:].lower()
        for sigla in ("PLDFT", "FI", "SIEM", "CVM"):  # siglas voltam para maiúsculas
            texto = re.sub(rf"\b{sigla.lower()}\b", sigla, texto)
    return texto


def _mapa_responsaveis(df: pd.DataFrame | None) -> dict[str, str]:
    """{cnpj: 'NOME: cargo1, cargo2; OUTRO NOME: cargo'} — uma entrada por pessoa."""
    if df is None or df.empty:
        return {}
    por_cnpj: dict[str, dict[str, list[str]]] = {}
    for cnpj, nome, cargo in zip(_col(df, "CNPJ"), _col(df, "RESP"), _col(df, "TP_RESP")):
        if not cnpj or not nome or nome == SEM_DIRETOR:
            continue
        cargos = por_cnpj.setdefault(cnpj, {}).setdefault(nome, [])
        resumo = _resumir_cargo(cargo) if cargo else ""
        if resumo and resumo not in cargos:
            cargos.append(resumo)
    return {
        cnpj: "; ".join(f"{nome}: {', '.join(cargos)}" if cargos else nome for nome, cargos in pessoas.items())
        for cnpj, pessoas in por_cnpj.items()
    }


def _normalizar_pj(df, tipo, origem, diretores, responsaveis, socios) -> pd.DataFrame:
    cnpj = _col(df, "CNPJ")
    registro = _col(df, "DT_REG")
    pedacos = [_col(df, c) for c in ("LOGRADOURO", "COMPL", "BAIRRO")]
    telefones = [
        (f"({ddd}) {tel}" if ddd and tel else tel)
        for ddd, tel in zip(_col(df, "DDD"), _col(df, "TEL"))
    ]
    out = pd.DataFrame(
        {
            "tipo": tipo,
            "pessoa": "PJ",
            "nome": _col(df, "DENOM_SOCIAL"),
            "nome_fantasia": _col(df, "DENOM_COMERC"),
            "cnpj": cnpj,
            "situacao": _col(df, "SIT"),
            "data_registro": registro,
            "data_cancelamento": _col(df, "DT_CANCEL"),
            "motivo_cancelamento": _col(df, "MOTIVO_CANCEL"),
            "data_inicio_situacao": _col(df, "DT_INI_SIT"),
            "categoria": _col(df, "CATEG_REG"),
            "subcategoria": _col(df, "SUBCATEG_REG"),
            "controle_acionario": _col(df, "CONTROLE_ACIONARIO"),
            "uf": _col(df, "UF").str.upper(),
            "municipio": _col(df, "MUN"),
            "endereco": [", ".join(p for p in tup if p) for tup in zip(*pedacos)],
            "cep": _col(df, "CEP"),
            "telefone": telefones,
            "email": _col(df, "EMAIL").str.lower(),
            "site": _col(df, "SITE_ADMIN"),
            "patrimonio_liquido": pd.to_numeric(_col(df, "VL_PATRIM_LIQ"), errors="coerce"),
            "data_patrimonio": _col(df, "DT_PATRIM_LIQ"),
            "diretores": cnpj.map(diretores),
            "responsaveis": cnpj.map(responsaveis),
            "socios": cnpj.map(socios),
            "origem": origem,
        },
        index=df.index,
    )
    out = out[(cnpj != "") & (registro != "")]
    out["chave_unica"] = out["cnpj"] + "|" + out["data_registro"] + "|" + tipo
    return out


def _normalizar_pf(df, tipo, origem, nome_col) -> pd.DataFrame:
    nome = _col(df, nome_col)
    registro = _col(df, "DT_REG")
    out = pd.DataFrame(
        {
            "tipo": tipo,
            "pessoa": "PF",
            "nome": nome,
            "situacao": _col(df, "SIT"),
            "data_registro": registro,
            "data_cancelamento": _col(df, "DT_CANCEL"),
            "motivo_cancelamento": _col(df, "MOTIVO_CANCEL"),
            "data_inicio_situacao": _col(df, "DT_INI_SIT"),
            "categoria": _col(df, "CATEG_REG"),
            "site": _col(df, "SITE_ADMIN"),
            "origem": origem,
        },
        index=df.index,
    )
    out = out[(nome != "") & (registro != "")]
    out["chave_unica"] = out["nome"] + "|" + out["data_registro"] + "|" + tipo
    return out


def _para_registros(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> lista de dicts com todos os CAMPOS; vazio vira None."""
    df = df.reindex(columns=CAMPOS)
    registros = []
    for rec in df.to_dict("records"):
        limpo = {}
        for campo, valor in rec.items():
            if valor is None or (isinstance(valor, float) and valor != valor):
                limpo[campo] = None
            elif campo == "patrimonio_liquido":
                limpo[campo] = float(valor)
            else:
                texto = str(valor).strip()
                limpo[campo] = texto or None
        registros.append(limpo)
    return registros


def _dedupe_records(records: list[dict]) -> list[dict]:
    """
    Colapsa chaves duplicadas dentro da própria base da CVM (inconsistência da
    fonte, ~0,08% dos registros). Se alguma das linhas estiver em funcionamento
    normal, mantém essa; senão, mantém a última. Cada caso gera um aviso no log.
    """
    por_chave: dict[str, dict] = {}
    for r in records:
        chave = r["chave_unica"]
        if chave not in por_chave:
            por_chave[chave] = r
            continue
        logger.warning("Chave duplicada na fonte da CVM: '%s'. Mantendo a versão mais confiável.", chave)
        if r.get("situacao") == SITUACAO_ATIVA or por_chave[chave].get("situacao") != SITUACAO_ATIVA:
            por_chave[chave] = r
    return list(por_chave.values())


# ----------------------------------------------------------------------------
# Coleta
# ----------------------------------------------------------------------------
def _coletar(tipo: str) -> list[dict]:
    spec = DATASETS[tipo]
    prefix = spec["prefix"]
    zip_path = _get_zip_path(spec["url"], spec["env"], spec["zip"])

    tmp = Path(tempfile.mkdtemp(prefix=f"cvm_{prefix}_"))
    try:
        pj_req = ["CNPJ", "DENOM_SOCIAL", "DT_REG", "SIT"]
        pf_req = [spec["pf_nome"], "DT_REG", "SIT"]
        if spec["filtrar_gestor"]:
            pj_req.append("CATEG_REG")
            pf_req.append("CATEG_REG")

        df_pj = _read_csv(_extract(zip_path, f"{prefix}_pj.csv", tmp), pj_req)
        df_pf = _read_csv(_extract(zip_path, f"{prefix}_pf.csv", tmp), pf_req)
        total_pj, total_pf = len(df_pj), len(df_pf)

        if spec["filtrar_gestor"]:
            df_pj = df_pj[df_pj["CATEG_REG"].str.contains(CATEG_GESTOR, na=False)]
            df_pf = df_pf[df_pf["CATEG_REG"].str.contains(CATEG_GESTOR, na=False)]

        diretores = _mapa_por_cnpj(
            _ler_opcional(zip_path, f"{prefix}_diretor.csv", tmp, ["CNPJ", "DIRETOR"]), "DIRETOR")
        responsaveis = _mapa_responsaveis(
            _ler_opcional(zip_path, f"{prefix}_resp.csv", tmp, ["CNPJ", "RESP"]))
        socios = _mapa_por_cnpj(
            _ler_opcional(zip_path, f"{prefix}_socios.csv", tmp, ["CNPJ", "SOCIOS"]), "SOCIOS")

        pj = _normalizar_pj(df_pj, tipo, spec["origem"], diretores, responsaveis, socios)
        pf = _normalizar_pf(df_pf, tipo, spec["origem"], spec["pf_nome"])
        records = _dedupe_records(_para_registros(pj) + _para_registros(pf))

        logger.info(
            "%s coletados: %d PJ + %d PF = %d registros (arquivo original: %d PJ e %d PF).",
            tipo, len(pj), len(pf), len(records), total_pj, total_pf,
        )
        return records
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def collect_gestores() -> list[dict]:
    """Gestores de carteira (PF + PJ), já filtrados por CATEG_REG."""
    return _coletar("Gestor")


def collect_consultores() -> list[dict]:
    """Consultores de valores mobiliários (PF + PJ)."""
    return _coletar("Consultor")


collect_consultorias = collect_consultores  # nome antigo, mantido por compatibilidade


def collect_all() -> list[dict]:
    """Gestores + consultores em uma única lista normalizada."""
    return collect_gestores() + collect_consultores()