"""
Ponto de entrada para a execução diária da automação.

Uso:
    python run_daily.py

Faz, nesta ordem:
    1. Inicializa o banco (se ainda não existir)
    2. Coleta os dados atuais (gestores + consultorias)
    3. Salva o snapshot do dia
    4. Compara com o histórico para achar novos registros / alterações
    5. Persiste os novos registros encontrados
    6. Gera o relatório (markdown) com resumo opcional por IA

Pensado para ser chamado por cron, GitHub Actions, ou manualmente.
Todo o log da execução vai também para data/execucao.log.
"""
import sys
from datetime import date

from src.collector import collect_all
from src.comparator import compare_snapshot
from src.logger_config import get_logger
from src.report import build_report
from src.storage import init_db, save_new_records, save_snapshot

logger = get_logger(__name__)


def main() -> int:
    today = date.today().isoformat()
    logger.info("=== Iniciando execução diária (%s) ===", today)

    try:
        init_db()

        records = collect_all()
        if not records:
            logger.warning("Coleta retornou 0 registros. Abortando comparação.")
            return 1

        comparison = compare_snapshot(records)

        # Salva o snapshot DEPOIS de comparar, para não contaminar a
        # comparação de hoje com os próprios dados de hoje.
        save_snapshot(records, data_coleta=today)

        if comparison.novos:
            save_new_records(comparison.novos, data_deteccao=today)

        report = build_report(comparison, data_coleta=today, use_ai=True)

        logger.info(
            "Resumo do dia: %d novos gestores, %d novas consultorias, %d alterações.",
            report["total_novos_gestores"],
            report["total_novas_consultorias"],
            report["total_alterados"],
        )
        logger.info("=== Execução diária concluída com sucesso ===")
        return 0

    except Exception:
        logger.exception("Falha não tratada durante a execução diária.")
        return 1


if __name__ == "__main__":
    sys.exit(main())