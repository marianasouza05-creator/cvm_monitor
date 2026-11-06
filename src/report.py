"""
Relatório diário em Markdown (data/reports/relatorio_AAAA-MM-DD.md).

Na carga inicial (baseline) o relatório só informa que a base foi montada;
os "novos" começam a aparecer a partir da execução seguinte.
"""
from datetime import date

import pandas as pd

from src.ai_summary import get_provider
from src.comparator import ComparisonResult
from src.config import REPORTS_DIR
from src.logger_config import get_logger

logger = get_logger(__name__)

COLUNAS_NOVOS = ["tipo", "pessoa", "nome", "cnpj", "uf", "email", "site", "situacao", "data_registro"]


def _contar(registros: list[dict], tipo: str, pessoa: str | None = None) -> int:
    return sum(1 for r in registros if r["tipo"] == tipo and (pessoa is None or r["pessoa"] == pessoa))


def build_report(result: ComparisonResult, data_carga: str | None = None, use_ai: bool = True) -> dict:
    data_carga = data_carga or date.today().isoformat()
    novos = result.novos

    contagens = {
        "gestores": _contar(novos, "Gestor"),
        "gestores_pf": _contar(novos, "Gestor", "PF"),
        "gestores_pj": _contar(novos, "Gestor", "PJ"),
        "consultores": _contar(novos, "Consultor"),
        "consultores_pf": _contar(novos, "Consultor", "PF"),
        "consultores_pj": _contar(novos, "Consultor", "PJ"),
    }

    resumo_ia = None
    if use_ai and not result.baseline:
        resumo_ia = get_provider().summarize(novos, result.alterados)

    df_novos = pd.DataFrame(novos, columns=COLUNAS_NOVOS).fillna("—")
    linhas_alt = [
        {"tipo": r["tipo"], "nome": r["nome"], "campo": campo, "anterior": antes or "—", "novo": depois or "—"}
        for r in result.alterados for campo, antes, depois in r["mudancas"]
    ]
    df_alterados = pd.DataFrame(linhas_alt)

    report = {
        "data_carga": data_carga,
        "baseline": result.baseline,
        "total_registros": len(result.registros),
        "total_alterados": len(result.alterados),
        "total_removidos": len(result.removidos),
        "total_inalterados": result.inalterados_count,
        "novos": contagens,
        "df_novos": df_novos,
        "df_alterados": df_alterados,
        "resumo_ia": resumo_ia,
    }
    report["arquivo"] = str(_salvar_markdown(report))
    return report


def _frase_resumo(report: dict) -> str:
    n = report["novos"]
    if report["baseline"]:
        return (
            f"Carga inicial: {report['total_registros']:,} registros da CVM foram carregados como base de "
            "comparação. Nenhum deles é contado como novo; os novos registros aparecem a partir da próxima atualização."
        ).replace(",", ".")
    if n["gestores"] == 0 and n["consultores"] == 0:
        return "Nenhum novo registro identificado hoje."
    return (
        f"Hoje foram identificados **{n['gestores']} novos gestores** (PF {n['gestores_pf']}, PJ {n['gestores_pj']}) "
        f"e **{n['consultores']} novos consultores** (PF {n['consultores_pf']}, PJ {n['consultores_pj']})."
    )


def _salvar_markdown(report: dict):
    path = REPORTS_DIR / f"relatorio_{report['data_carga']}.md"
    linhas = [f"# Relatório CVM — {report['data_carga']}", "", _frase_resumo(report), ""]

    if report["resumo_ia"]:
        linhas += ["## Resumo executivo (IA)", "", report["resumo_ia"], ""]

    if not report["baseline"]:
        linhas += ["## Novos registros", ""]
        if report["df_novos"].empty:
            linhas.append("_Nenhum novo registro identificado hoje._")
        else:
            linhas.append(report["df_novos"].to_markdown(index=False))

    if not report["df_alterados"].empty:
        linhas += ["", "## Alterações cadastrais (não contam como novos)", "", report["df_alterados"].to_markdown(index=False)]
    if report["total_removidos"]:
        linhas += ["", f"_{report['total_removidos']} registro(s) deixaram de constar na base da CVM._"]

    path.write_text("\n".join(linhas), encoding="utf-8")
    logger.info("Relatório salvo em %s", path)
    return path