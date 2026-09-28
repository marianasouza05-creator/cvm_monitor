"""
Lógica de comparação entre o snapshot atual e o histórico.

REGRA DE OURO: a identidade de uma entidade é a `chave_unica`
(identificador + data de registro), nunca o nome sozinho. Um registro só é
considerado "novo" se sua chave nunca apareceu em nenhum snapshot anterior.
Se a chave já existe mas o nome ou a situação mudaram, isso é tratado como
"alteração", não como novo cadastro.

Esta função é 100% determinística (sem IA) — é a fonte de verdade do
relatório. A IA (src/ai_summary.py) só entra depois, para comentar sobre os
resultados já calculados aqui.
"""
from dataclasses import dataclass, field

from src.logger_config import get_logger
from src.storage import get_all_known_chaves, get_latest_snapshot_by_chave

logger = get_logger(__name__)


@dataclass
class ComparisonResult:
    novos: list[dict] = field(default_factory=list)
    alterados: list[dict] = field(default_factory=list)  # mudança de nome/situação
    inalterados_count: int = 0


def compare_snapshot(current_records: list[dict]) -> ComparisonResult:
    """
    Compara os registros coletados hoje com todo o histórico já salvo.

    Retorna um ComparisonResult com:
      - novos: registros cuja chave_unica nunca foi vista antes
      - alterados: registros existentes cujo nome ou situação mudou
      - inalterados_count: quantos registros não mudaram nada
    """
    known_chaves = get_all_known_chaves()
    result = ComparisonResult()

    for record in current_records:
        chave = record["chave_unica"]

        if chave not in known_chaves:
            result.novos.append(record)
            continue

        anterior = get_latest_snapshot_by_chave(chave)
        if anterior is None:
            # Segurança: não deveria acontecer já que chave está em known_chaves,
            # mas por robustez tratamos como novo em vez de quebrar.
            result.novos.append(record)
            continue

        mudou_nome = anterior["nome"] != record["nome"]
        mudou_situacao = anterior["situacao"] != record.get("situacao")

        if mudou_nome or mudou_situacao:
            result.alterados.append(
                {
                    **record,
                    "nome_anterior": anterior["nome"] if mudou_nome else None,
                    "situacao_anterior": anterior["situacao"] if mudou_situacao else None,
                }
            )
        else:
            result.inalterados_count += 1

    logger.info(
        "Comparação concluída: %d novos, %d alterados, %d inalterados.",
        len(result.novos),
        len(result.alterados),
        result.inalterados_count,
    )
    return result