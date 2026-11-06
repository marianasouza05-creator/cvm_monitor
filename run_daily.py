"""
Ponto de entrada da execução diária (manual, cron, Agendador de Tarefas ou CI).

Uso:
    python run_daily.py

Faz uma atualização completa: coleta na CVM, compara com a base, grava as
entidades novas/alteradas e gera o relatório em data/reports/.
"""
import sys

from src.logger_config import get_logger
from src.pipeline import run_update

logger = get_logger(__name__)


def main() -> int:
    logger.info("=== Iniciando atualização diária ===")
    try:
        result, report = run_update(use_ai=True)
    except Exception:
        logger.error("=== Atualização falhou (detalhes acima) ===")
        return 1

    if report["baseline"]:
        logger.info("Carga inicial concluída: %d registros viraram a base de comparação.", report["total_registros"])
    else:
        n = report["novos"]
        logger.info(
            "Resumo: %d novos gestores, %d novos consultores, %d alterações.",
            n["gestores"], n["consultores"], report["total_alterados"],
        )
    logger.info("=== Atualização concluída com sucesso ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())