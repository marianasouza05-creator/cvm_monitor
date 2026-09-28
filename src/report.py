"""
Geração do relatório diário.

Produz:
  - um objeto estruturado (dict) fácil de consumir no Streamlit
  - um arquivo Markdown salvo em data/reports/relatorio_AAAA-MM-DD.md
"""
from datetime import date

import pandas as pd

from src.ai_summary import get_provider
from src.comparator import ComparisonResult
from src.config import REPORTS_DIR
from src.logger_config import get_logger

logger = get_logger(__name__)

COLUNAS_RELATORIO = [
    "tipo",
    "pessoa",
    "nome",
    "cnpj",
    "situacao",
    "data_registro",
]


def build_report(comparison: ComparisonResult, data_coleta: str | None = None, use_ai: bool = True) -> dict:
    data_coleta = data_coleta or date.today().isoformat()

    novos_gestores = [r for r in comparison.novos if r["tipo"] == "Gestor"]
    novas_consultorias = [r for r in comparison.novos if r["tipo"] == "Consultoria"]

    resumo_ia = None
    if use_ai:
        provider = get_provider()
        resumo_ia = provider.summarize(comparison.novos, comparison.alterados)

    df_novos = pd.DataFrame(comparison.novos, columns=COLUNAS_RELATORIO) if comparison.novos else pd.DataFrame(columns=COLUNAS_RELATORIO)
    df_novos = df_novos.fillna("—")  # pessoa física não tem CNPJ; mais legível que "nan"
    df_alterados = pd.DataFrame(comparison.alterados) if comparison.alterados else pd.DataFrame()
    if not df_alterados.empty:
        df_alterados = df_alterados.fillna("—")

    report = {
        "data_coleta": data_coleta,
        "total_novos_gestores": len(novos_gestores),
        "total_novas_consultorias": len(novas_consultorias),
        "total_alterados": len(comparison.alterados),
        "total_inalterados": comparison.inalterados_count,
        "df_novos": df_novos,
        "df_alterados": df_alterados,
        "resumo_ia": resumo_ia,
    }

    _save_markdown(report)
    return report


def _save_markdown(report: dict) -> None:
    path = REPORTS_DIR / f"relatorio_{report['data_coleta']}.md"
    linhas = [
        f"# Relatório CVM — {report['data_coleta']}",
        "",
        f"Hoje foram identificados **{report['total_novos_gestores']} novos gestores** "
        f"e **{report['total_novas_consultorias']} novas consultorias**.",
        "",
    ]

    if report["resumo_ia"]:
        linhas += ["## Resumo executivo (IA)", "", report["resumo_ia"], ""]

    linhas += ["## Novos registros", ""]
    if report["df_novos"].empty:
        linhas.append("_Nenhum novo registro identificado hoje._")
    else:
        linhas.append(report["df_novos"].to_markdown(index=False))

    if not report["df_alterados"].empty:
        linhas += ["", "## Alterações cadastrais (não contam como novos)", ""]
        linhas.append(report["df_alterados"].to_markdown(index=False))

    path.write_text("\n".join(linhas), encoding="utf-8")
    logger.info("Relatório salvo em %s", path)