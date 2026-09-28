"""
Coletor de dados REAIS da CVM — Portal de Dados Abertos.

Fontes oficiais (validadas manualmente em 08/09/2026, baixando e inspecionando
o conteúdo real dos arquivos antes de escrever este código):

  Consultores de Valores Mobiliários:
    https://dados.cvm.gov.br/dados/CONSULTOR_VLMOB/CAD/DADOS/cad_consultor_vlmob.zip

  Administradores de Carteira (inclui Gestores de Recursos):
    https://dados.cvm.gov.br/dados/ADM_CART/CAD/DADOS/cad_adm_cart.zip

Formato: ZIP contendo vários CSVs, separador ";", encoding ISO-8859-1.
Usamos apenas os arquivos "_pf.csv" (pessoa física) e "_pj.csv" (pessoa
jurídica) de cada ZIP — os demais (_diretor, _resp, _socios) são tabelas
relacionais auxiliares, fora do escopo deste MVP.

--- SOBRE A CHAVE ÚNICA ---
A CVM NÃO disponibiliza um "código CVM" numérico nesses arquivos abertos.
- Pessoa jurídica: o identificador é o CNPJ.
- Pessoa física: não há CPF disponível publicamente — o único identificador
  é o NOME (campo "ADMIN" no arquivo de administradores, "NOME" no de
  consultores).

Além disso, o arquivo é um HISTÓRICO completo (inclui registros já
cancelados), não uma fotografia só do que está ativo hoje. Uma mesma empresa
pode aparecer mais de uma vez com o mesmo CNPJ, se ela cancelou o registro e
se recadastrou depois (confirmado com um caso real: "Spinnaker Capital",
registro original em 2008 cancelado em 2021, novo registro em 2022).

Por isso a chave de identidade usada em todo o sistema é composta:
    chave_unica = f"{identificador}|{data_registro}|{tipo}"
onde identificador é o CNPJ (PJ) ou o NOME (PF), data_registro é DT_REG, e
tipo é "Gestor" ou "Consultoria". Isso preserva a regra de ouro do projeto
(mudança de nome não gera falso "novo") e, como efeito colateral desejável,
trata um recadastramento como um evento novo de verdade — que é justamente
o que se quer monitorar.

IMPORTANTE — por que o "tipo" faz parte da chave: uma mesma empresa pode
estar registrada simultaneamente como Gestora de Carteira E como Consultora
de Valores Mobiliários (são papéis regulatórios diferentes, ambos comuns no
mercado). Encontramos casos reais em que o mesmo CNPJ com a mesma
data_registro aparece nos dois arquivos, inclusive com situação diferente
em cada papel (ex: cancelada como consultoria, mas ativa como gestora).
Sem o "tipo" na chave, esses dois cadastros colidiam e um "mascarava" o
outro na comparação.

--- SOBRE O FILTRO DE CATEGORIA ---
O arquivo de administradores de carteira mistura duas categorias na mesma
base: "Gestor de Carteira" e "Administrador Fiduciário" (papéis
regulatórios diferentes). Só nos interessa gestor, então filtramos pela
coluna CATEG_REG contendo "Gestor de Carteira" (isso também cobre a
categoria combinada "Administrador Fiduciário e Gestor de Carteira").
"""
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import requests

from src.config import DATA_DIR
from src.logger_config import get_logger

logger = get_logger(__name__)

CONSULTOR_URL = "https://dados.cvm.gov.br/dados/CONSULTOR_VLMOB/CAD/DADOS/cad_consultor_vlmob.zip"
ADM_CART_URL = "https://dados.cvm.gov.br/dados/ADM_CART/CAD/DADOS/cad_adm_cart.zip"

RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(exist_ok=True, parents=True)

REQUEST_TIMEOUT = 60  # a CVM pode ser lenta às vezes; melhor tolerar

CATEG_GESTOR = "Gestor de Carteira"

REQUIRED_FIELDS = ["chave_unica", "tipo", "pessoa", "nome", "cnpj", "situacao", "data_registro"]


class FonteCVMError(Exception):
    """Erro ao baixar ou interpretar um arquivo da CVM."""


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
    """
    Retorna o caminho de um ZIP da CVM.

    Se a variável de ambiente `env_override` estiver definida, usa o arquivo
    local apontado por ela em vez de baixar — útil para testes offline ou
    para reprocessar um arquivo já baixado manualmente.
    """
    override = os.getenv(env_override)
    if override:
        path = Path(override)
        if not path.exists():
            raise FonteCVMError(f"Arquivo local indicado em {env_override} não existe: {path}")
        logger.info("Usando arquivo local (override via %s): %s", env_override, path)
        return path

    dest = RAW_DIR / filename
    return _download(url, dest)


def _extract(zip_path: Path, member: str, extract_to: Path) -> Path:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if member not in names:
                raise FonteCVMError(
                    f"Arquivo '{member}' não encontrado dentro de {zip_path.name}. "
                    f"Conteúdo do zip: {names}. A CVM pode ter mudado a estrutura "
                    f"— revisar collector.py."
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
            f"Colunas encontradas: {list(df.columns)}. "
            f"A CVM pode ter alterado a estrutura do arquivo — revisar collector.py."
        )
    return df


def _dedupe_records(records: list[dict]) -> list[dict]:
    """
    Colapsa duplicatas de chave_unica encontradas DENTRO da própria base da
    CVM (não é um bug nosso — a fonte oficial ocasionalmente tem duas linhas
    para a mesma empresa/pessoa, mesma data de registro e mesmo tipo, às
    vezes até com situação ou nome diferente entre as duas). Observado em
    ~0,08% dos registros na validação inicial deste projeto (9 de 11.572).

    Regra: se qualquer uma das linhas duplicadas estiver "EM FUNCIONAMENTO
    NORMAL", mantém essa (é a mais provável de refletir o estado real);
    caso contrário, mantém a última encontrada. Cada ocorrência gera um
    aviso no log para rastreabilidade.
    """
    by_key: dict[str, dict] = {}
    for r in records:
        key = r["chave_unica"]
        if key not in by_key:
            by_key[key] = r
            continue

        logger.warning(
            "Chave duplicada na fonte da CVM (inconsistência da própria base, "
            "não é erro do coletor): '%s'. Mantendo a versão mais confiável.",
            key,
        )
        existing = by_key[key]
        if r.get("situacao") == "EM FUNCIONAMENTO NORMAL":
            by_key[key] = r
        elif existing.get("situacao") == "EM FUNCIONAMENTO NORMAL":
            pass  # mantém a que já estava
        else:
            by_key[key] = r

    return list(by_key.values())


def _normalize_pj(df: pd.DataFrame, tipo: str) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        cnpj = row["CNPJ"].strip()
        data_registro = row["DT_REG"].strip()
        if not cnpj or not data_registro:
            continue  # linha malformada — pula em vez de quebrar o pipeline
        records.append(
            {
                "chave_unica": f"{cnpj}|{data_registro}|{tipo}",
                "tipo": tipo,
                "pessoa": "PJ",
                "nome": row["DENOM_SOCIAL"].strip(),
                "cnpj": cnpj,
                "situacao": row["SIT"].strip(),
                "data_registro": data_registro,
            }
        )
    return records


def _normalize_pf(df: pd.DataFrame, tipo: str, nome_col: str) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        nome = row[nome_col].strip()
        data_registro = row["DT_REG"].strip()
        if not nome or not data_registro:
            continue
        records.append(
            {
                "chave_unica": f"{nome}|{data_registro}|{tipo}",
                "tipo": tipo,
                "pessoa": "PF",
                "nome": nome,
                "cnpj": None,
                "situacao": row["SIT"].strip(),
                "data_registro": data_registro,
            }
        )
    return records


def collect_consultorias() -> list[dict]:
    """Coleta consultores de valores mobiliários (PF + PJ) da fonte real da CVM."""
    zip_path = _get_zip_path(CONSULTOR_URL, "CVM_CONSULTOR_ZIP_PATH", "cad_consultor_vlmob.zip")

    tmp = Path(tempfile.mkdtemp(prefix="cvm_consultor_"))
    try:
        pj_path = _extract(zip_path, "cad_consultor_vlmob_pj.csv", tmp)
        pf_path = _extract(zip_path, "cad_consultor_vlmob_pf.csv", tmp)

        df_pj = _read_csv(pj_path, required_cols=["CNPJ", "DENOM_SOCIAL", "DT_REG", "SIT"])
        df_pf = _read_csv(pf_path, required_cols=["NOME", "DT_REG", "SIT"])

        records = _normalize_pj(df_pj, "Consultoria") + _normalize_pf(df_pf, "Consultoria", nome_col="NOME")
        records = _dedupe_records(records)
        logger.info(
            "Consultorias coletadas: %d PJ + %d PF = %d total (após deduplicação).",
            len(df_pj), len(df_pf), len(records),
        )
        return records
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def collect_gestores() -> list[dict]:
    """
    Coleta gestores de carteira (PF + PJ) da fonte real da CVM.

    Filtra explicitamente por CATEG_REG contendo "Gestor de Carteira", já
    que o arquivo de administradores de carteira também inclui
    Administradores Fiduciários (papel diferente, fora do escopo).
    """
    zip_path = _get_zip_path(ADM_CART_URL, "CVM_ADM_CART_ZIP_PATH", "cad_adm_cart.zip")

    tmp = Path(tempfile.mkdtemp(prefix="cvm_adm_cart_"))
    try:
        pj_path = _extract(zip_path, "cad_adm_cart_pj.csv", tmp)
        pf_path = _extract(zip_path, "cad_adm_cart_pf.csv", tmp)

        df_pj = _read_csv(
            pj_path, required_cols=["CNPJ", "DENOM_SOCIAL", "DT_REG", "SIT", "CATEG_REG"]
        )
        df_pf = _read_csv(
            pf_path, required_cols=["ADMIN", "DT_REG", "SIT", "CATEG_REG"]
        )

        df_pj_gestores = df_pj[df_pj["CATEG_REG"].str.contains(CATEG_GESTOR, na=False)]
        df_pf_gestores = df_pf[df_pf["CATEG_REG"].str.contains(CATEG_GESTOR, na=False)]

        records = _normalize_pj(df_pj_gestores, "Gestor") + _normalize_pf(
            df_pf_gestores, "Gestor", nome_col="ADMIN"
        )
        records = _dedupe_records(records)
        logger.info(
            "Gestores coletados (filtrado por '%s'): %d PJ + %d PF = %d total "
            "(de %d PJ e %d PF no arquivo original, após deduplicação).",
            CATEG_GESTOR, len(df_pj_gestores), len(df_pf_gestores), len(records),
            len(df_pj), len(df_pf),
        )
        return records
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def collect_all() -> list[dict]:
    """Coleta gestores + consultorias em uma única lista normalizada."""
    return collect_gestores() + collect_consultorias()
