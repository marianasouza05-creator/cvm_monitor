"""
Pipeline de atualização: coleta -> compara -> grava -> relatório.

Usado pelo botão "Atualizar base" do painel e pelo run_daily.py (agendamento).
"""
from datetime import date, datetime

from src import storage
from src.collector import FonteCVMError, collect_all
from src.comparator import compare_snapshot
from src.logger_config import get_logger
from src.report import build_report

logger = get_logger(__name__)

# Se a carga nova tiver menos da metade das entidades conhecidas, o arquivo da
# CVM provavelmente veio truncado: aborta em vez de marcar tudo como "removido".
LIMITE_QUEDA = 0.5


def run_update(use_ai: bool = True, hoje: date | None = None):
    """Executa uma atualização completa. Devolve (resultado_da_comparacao, relatorio)."""
    data_carga = (hoje or date.today()).isoformat()
    iniciada_em = datetime.now().isoformat(timespec="seconds")
    storage.init_db()

    try:
        records = collect_all()
        if not records:
            raise FonteCVMError("A coleta não retornou nenhum registro.")

        existing = storage.load_existing()
        if existing and len(records) < LIMITE_QUEDA * len(existing):
            raise FonteCVMError(
                f"Arquivo suspeito: {len(records)} registros contra {len(existing)} já conhecidos. "
                "Nada foi gravado."
            )

        baseline = not storage.has_baseline()
        result = compare_snapshot(records, existing, baseline=baseline)
        storage.apply_carga(result, data_carga, iniciada_em)
        report = build_report(result, data_carga, use_ai=use_ai)
        return result, report
    except Exception as exc:
        logger.exception("Falha na atualização.")
        storage.log_carga_erro(data_carga, iniciada_em, str(exc))
        raise