"""
Testes básicos da camada de storage (SQLite).

Roda com:
    pytest tests/test_storage.py -v
"""
import os
import tempfile

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    tmp_db_path = os.path.join(tmp_dir, "test.db")

    import src.config as config_module
    monkeypatch.setattr(config_module, "DB_PATH", tmp_db_path)

    import src.storage as storage_module
    monkeypatch.setattr(storage_module, "DB_PATH", tmp_db_path)

    storage_module.init_db()
    yield storage_module


def _registro(cnpj, nome="Empresa Teste", tipo="Gestor", data_registro="2020-01-01"):
    return {
        "chave_unica": f"{cnpj}|{data_registro}|{tipo}",
        "tipo": tipo,
        "pessoa": "PJ",
        "nome": nome,
        "cnpj": cnpj,
        "situacao": "EM FUNCIONAMENTO NORMAL",
        "data_registro": data_registro,
    }


def test_save_snapshot_nao_duplica_no_mesmo_dia(temp_db):
    temp_db.save_snapshot([_registro("11.111.111/0001-11")], data_coleta="2024-01-01")
    temp_db.save_snapshot([_registro("11.111.111/0001-11")], data_coleta="2024-01-01")  # roda 2x no mesmo dia

    known = temp_db.get_all_known_chaves()
    assert known == {"11.111.111/0001-11|2020-01-01|Gestor"}


def test_get_totals_conta_distintos_por_tipo(temp_db):
    temp_db.save_snapshot(
        [_registro("11.111.111/0001-11", tipo="Gestor"), _registro("22.222.222/0001-22", tipo="Consultoria")],
        data_coleta="2024-01-01",
    )

    totals = temp_db.get_totals()
    assert totals["gestores"] == 1
    assert totals["consultorias"] == 1
    assert totals["ultima_atualizacao"] == "2024-01-01"


def test_save_and_get_new_records_by_date(temp_db):
    temp_db.save_new_records([_registro("55.555.555/0001-55")], data_deteccao="2024-02-01")

    novos = temp_db.get_new_records_by_date("2024-02-01")
    assert len(novos) == 1
    assert novos[0]["cnpj"] == "55.555.555/0001-55"

    vazio = temp_db.get_new_records_by_date("2099-01-01")
    assert vazio == []


def test_get_latest_snapshot_by_chave_retorna_mais_recente(temp_db):
    temp_db.save_snapshot([_registro("11.111.111/0001-11", nome="Nome Antigo")], data_coleta="2024-01-01")
    temp_db.save_snapshot([_registro("11.111.111/0001-11", nome="Nome Novo")], data_coleta="2024-02-01")

    latest = temp_db.get_latest_snapshot_by_chave("11.111.111/0001-11|2020-01-01|Gestor")
    assert latest["nome"] == "Nome Novo"
    assert latest["data_coleta"] == "2024-02-01"