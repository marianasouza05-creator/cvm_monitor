"""
Coletor MOCK (dados fictícios) — mantido como MODO DEMO OFFLINE.

*** A fonte real da CVM já foi validada e está implementada em src/collector.py ***
Este módulo continua existindo só para permitir demonstrar a interface sem
depender de internet (ex: apresentação em sala sem rede, ou se o site da
CVM estiver fora do ar). O app.py deixa escolher entre os dois.

Padrão de campos (alinhado ao schema real usado por collector.py):
    - chave_unica  -> identificador + "|" + data_registro (chave de diff)
    - tipo         -> "Gestor" ou "Consultoria"
    - pessoa       -> "PF" ou "PJ"
    - nome         -> razão social / nome da pessoa física
    - cnpj         -> CNPJ, apenas para PJ (None para PF)
    - situacao     -> situação cadastral
    - data_registro-> data do registro/cadastro na CVM
"""
import random
from datetime import datetime, timedelta

from src.logger_config import get_logger

logger = get_logger(__name__)

REQUIRED_FIELDS = ["chave_unica", "tipo", "pessoa", "nome", "cnpj", "situacao", "data_registro"]

_NOMES_GESTORAS = [
    "Atlas Capital Gestão de Recursos Ltda",
    "Boreal Investimentos Ltda",
    "Cedro Asset Management S.A.",
    "Dínamo Gestão de Patrimônio Ltda",
    "Elipse Capital Gestora de Recursos Ltda",
    "Fronteira Asset Ltda",
    "Girassol Gestão de Investimentos S.A.",
    "Horizonte Capital Ltda",
    "Ipê Asset Management Ltda",
    "Jaguar Gestora de Recursos S.A.",
]

_NOMES_CONSULTORIAS = [
    "Vetor Consultoria de Valores Mobiliários Ltda",
    "Alpha Wealth Consultoria Ltda",
    "Bússola Consultoria Financeira S.A.",
    "Cristal Consultoria de Investimentos Ltda",
    "Delta Prime Consultoria Ltda",
    "Everest Consultoria de Valores Mobiliários S.A.",
]


def _mock_cnpj(seed: int) -> str:
    rnd = random.Random(seed)
    return (
        f"{rnd.randint(10, 99)}.{rnd.randint(100, 999)}."
        f"{rnd.randint(100, 999)}/0001-{rnd.randint(10, 99)}"
    )


def _base_records(nomes: list[str], tipo: str, seed_start: int) -> list[dict]:
    records = []
    base_date = datetime(2019, 1, 1)
    for i, nome in enumerate(nomes):
        seed = seed_start + i
        cnpj = _mock_cnpj(seed)
        data_registro = (base_date + timedelta(days=i * 47)).strftime("%Y-%m-%d")
        records.append(
            {
                "chave_unica": f"{cnpj}|{data_registro}|{tipo}",
                "tipo": tipo,
                "pessoa": "PJ",
                "nome": nome,
                "cnpj": cnpj,
                "situacao": "EM FUNCIONAMENTO NORMAL",
                "data_registro": data_registro,
            }
        )
    return records


def _load_injected_new_records() -> list[dict]:
    """Lê registros 'novos' injetados manualmente para fins de demonstração
    (botão do Streamlit). Não faz parte da lógica real de coleta."""
    from src.storage import get_injected_records
    return get_injected_records()


def collect_gestores() -> list[dict]:
    logger.info("[MOCK] Coletando gestores (dados fictícios)...")
    records = _base_records(_NOMES_GESTORAS, "Gestor", seed_start=1000)
    records += [r for r in _load_injected_new_records() if r["tipo"] == "Gestor"]
    logger.info("[MOCK] Coleta concluída: %d gestores.", len(records))
    return records


def collect_consultorias() -> list[dict]:
    logger.info("[MOCK] Coletando consultorias (dados fictícios)...")
    records = _base_records(_NOMES_CONSULTORIAS, "Consultoria", seed_start=2000)
    records += [r for r in _load_injected_new_records() if r["tipo"] == "Consultoria"]
    logger.info("[MOCK] Coleta concluída: %d consultorias.", len(records))
    return records


def collect_all() -> list[dict]:
    return collect_gestores() + collect_consultorias()
