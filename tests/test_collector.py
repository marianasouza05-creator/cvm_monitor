"""
Testes do coletor real (src/collector.py).

Não dependem de rede: testam a lógica de normalização e deduplicação
usando DataFrames sintéticos, isolando o comportamento que importa.

Roda com:
    pytest tests/test_collector.py -v
"""
import pandas as pd

from src.collector import _dedupe_records, _normalize_pf, _normalize_pj


def test_normalize_pj_gera_chave_com_tipo():
    df = pd.DataFrame(
        [{"CNPJ": "11.111.111/0001-11", "DENOM_SOCIAL": "Empresa A", "DT_REG": "2020-01-01", "SIT": "EM FUNCIONAMENTO NORMAL"}]
    )
    records = _normalize_pj(df, "Gestor")
    assert records[0]["chave_unica"] == "11.111.111/0001-11|2020-01-01|Gestor"
    assert records[0]["pessoa"] == "PJ"


def test_normalize_pf_sem_cnpj():
    df = pd.DataFrame(
        [{"NOME": "Fulano de Tal", "DT_REG": "2020-01-01", "SIT": "EM FUNCIONAMENTO NORMAL"}]
    )
    records = _normalize_pf(df, "Consultoria", nome_col="NOME")
    assert records[0]["chave_unica"] == "Fulano de Tal|2020-01-01|Consultoria"
    assert records[0]["cnpj"] is None
    assert records[0]["pessoa"] == "PF"


def test_normalize_pula_linha_sem_data_registro():
    """Linha malformada (sem DT_REG) não deve quebrar o pipeline nem virar
    um registro fantasma."""
    df = pd.DataFrame(
        [
            {"CNPJ": "11.111.111/0001-11", "DENOM_SOCIAL": "Empresa A", "DT_REG": "", "SIT": "ATIVO"},
            {"CNPJ": "22.222.222/0001-22", "DENOM_SOCIAL": "Empresa B", "DT_REG": "2020-01-01", "SIT": "ATIVO"},
        ]
    )
    records = _normalize_pj(df, "Gestor")
    assert len(records) == 1
    assert records[0]["cnpj"] == "22.222.222/0001-22"


def test_dedupe_mantem_em_funcionamento_normal_sobre_cancelada():
    """Caso real encontrado na base da CVM: mesma chave aparece duas vezes
    com situações conflitantes. Deve prevalecer 'EM FUNCIONAMENTO NORMAL'."""
    records = [
        {"chave_unica": "K1", "situacao": "CANCELADA", "nome": "A"},
        {"chave_unica": "K1", "situacao": "EM FUNCIONAMENTO NORMAL", "nome": "A"},
    ]
    result = _dedupe_records(records)
    assert len(result) == 1
    assert result[0]["situacao"] == "EM FUNCIONAMENTO NORMAL"


def test_dedupe_nao_afeta_chaves_unicas():
    records = [
        {"chave_unica": "K1", "situacao": "ATIVO", "nome": "A"},
        {"chave_unica": "K2", "situacao": "ATIVO", "nome": "B"},
    ]
    result = _dedupe_records(records)
    assert len(result) == 2