"""
Lógica de comparação entre a carga atual e o que já está no banco.

REGRA DE OURO: a identidade de uma entidade é a `chave_unica`
(identificador + data de registro + tipo), nunca o nome. Um registro só é
"novo" se a chave nunca apareceu antes. Se a chave existe mas nome, situação
ou dados de contato mudaram, é "alteração", não novo cadastro.

CARGA INICIAL (baseline): na primeira execução, nada é "novo" — todos os
registros viram a base de comparação. Sem isso, o primeiro relatório diria
que 11 mil entidades acabaram de se cadastrar.

100% determinístico, sem IA. É a fonte de verdade do relatório.
"""
from dataclasses import dataclass, field

from src.logger_config import get_logger

logger = get_logger(__name__)

# Campos cuja mudança é registrada no histórico de alterações.
CAMPOS_RASTREADOS = ["nome", "situacao", "uf", "municipio", "email", "site", "telefone"]


@dataclass
class ComparisonResult:
    registros: list[dict] = field(default_factory=list)   # toda a carga atual
    baseline: bool = False
    novos: list[dict] = field(default_factory=list)
    alterados: list[dict] = field(default_factory=list)   # registro + "mudancas"
    removidos: list[str] = field(default_factory=list)    # chaves que sumiram da fonte
    inalterados_count: int = 0


def _norm(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def compare_snapshot(
    current_records: list[dict],
    existing: dict[str, dict] | None = None,
    baseline: bool | None = None,
) -> ComparisonResult:
    """
    Compara a carga atual com as entidades já conhecidas.

    existing: {chave_unica: {campo: valor, ..., "ativo_na_fonte": 0/1}}
    baseline: força carga inicial; se None, é inferido (sem histórico = baseline).
    """
    existing = existing or {}
    if baseline is None:
        baseline = not existing

    result = ComparisonResult(registros=current_records, baseline=baseline)
    atuais = set()

    for rec in current_records:
        chave = rec["chave_unica"]
        atuais.add(chave)

        if baseline:
            continue

        anterior = existing.get(chave)
        if anterior is None:
            result.novos.append(rec)
            continue

        mudancas = [
            (campo, _norm(anterior.get(campo)), _norm(rec.get(campo)))
            for campo in CAMPOS_RASTREADOS
            if _norm(anterior.get(campo)) != _norm(rec.get(campo))
        ]
        if mudancas:
            result.alterados.append({**rec, "mudancas": mudancas})
        else:
            result.inalterados_count += 1

    if not baseline:
        result.removidos = [
            chave for chave, dados in existing.items()
            if chave not in atuais and dados.get("ativo_na_fonte", 1)
        ]

    logger.info(
        "Comparação concluída%s: %d registros, %d novos, %d alterados, %d inalterados, %d removidos da fonte.",
        " (carga inicial)" if baseline else "",
        len(current_records), len(result.novos), len(result.alterados),
        result.inalterados_count, len(result.removidos),
    )
    return result