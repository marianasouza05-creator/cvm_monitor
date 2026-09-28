"""
Testes da lógica de comparação (comparator.py) — a parte mais crítica
do sistema, já que é ela que decide o que é "novo".

Roda com:
    pytest tests/test_comparator.py -v
"""
import os
import tempfile

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    """Usa um banco SQLite temporário e isolado para cada teste."""
    tmp_dir = tempfile.mkdtemp()
    tmp_db_path = os.path.join(tmp_dir, "test.db")

    import src.config as config_module
    monkeypatch.setattr(config_module, "DB_PATH", tmp_db_path)

    import src.storage as storage_module
    monkeypatch.setattr(storage_module, "DB_PATH", tmp_db_path)

    storage_module.init_db()
    yield storage_module


def _registro(cnpj, nome, data_registro="2020-01-01", tipo="Gestor", situacao="EM FUNCIONAMENTO NORMAL", pessoa="PJ"):
    return {
        "chave_unica": f"{cnpj}|{data_registro}|{tipo}",
        "tipo": tipo,
        "pessoa": pessoa,
        "nome": nome,
        "cnpj": cnpj if pessoa == "PJ" else None,
        "situacao": situacao,
        "data_registro": data_registro,
    }


def test_primeiro_snapshot_marca_tudo_como_novo(temp_db):
    from src.comparator import compare_snapshot

    registros = [_registro("11.111.111/0001-11", "Empresa A"), _registro("22.222.222/0001-22", "Empresa B")]
    result = compare_snapshot(registros)

    assert len(result.novos) == 2
    assert result.alterados == []


def test_registro_ja_existente_nao_e_novo(temp_db):
    from src.comparator import compare_snapshot
    from src.storage import save_snapshot

    save_snapshot([_registro("11.111.111/0001-11", "Empresa A")], data_coleta="2024-01-01")

    result = compare_snapshot([_registro("11.111.111/0001-11", "Empresa A")])

    assert result.novos == []
    assert result.inalterados_count == 1


def test_mudanca_de_nome_nao_conta_como_novo_cadastro(temp_db):
    """Requisito mais importante do projeto: alteração de nome NÃO pode
    gerar um falso 'novo cadastro' quando a chave (CNPJ+data_registro)
    já existe."""
    from src.comparator import compare_snapshot
    from src.storage import save_snapshot

    save_snapshot(
        [_registro("11.111.111/0001-11", "Nome Antigo Ltda", data_registro="2020-01-01")],
        data_coleta="2024-01-01",
    )

    result = compare_snapshot(
        [_registro("11.111.111/0001-11", "Nome Novo S.A.", data_registro="2020-01-01")]
    )

    assert result.novos == []
    assert len(result.alterados) == 1
    assert result.alterados[0]["nome_anterior"] == "Nome Antigo Ltda"


def test_recadastramento_apos_cancelamento_conta_como_novo(temp_db):
    """Caso real encontrado nos dados da CVM (Spinnaker Capital): mesma
    empresa, mesmo CNPJ, mas registro novo (nova data_registro) após um
    cancelamento anterior. Isso DEVE contar como novo, pois representa um
    evento de negócio novo (reingresso no mercado)."""
    from src.comparator import compare_snapshot
    from src.storage import save_snapshot

    save_snapshot(
        [_registro("33.333.333/0001-33", "Empresa C", data_registro="2008-03-24", situacao="CANCELADA")],
        data_coleta="2024-01-01",
    )

    # mesmo CNPJ, mas nova data_registro -> chave_unica diferente -> é novo
    result = compare_snapshot(
        [_registro("33.333.333/0001-33", "Empresa C", data_registro="2024-06-01")]
    )

    assert len(result.novos) == 1
    assert result.novos[0]["chave_unica"] == "33.333.333/0001-33|2024-06-01|Gestor"


def test_pessoa_fisica_usa_nome_como_identificador(temp_db):
    """Pessoa física não tem CNPJ nem CPF disponível — a chave usa o nome."""
    from src.comparator import compare_snapshot

    registro_pf = {
        "chave_unica": "JOAO DA SILVA|2020-01-01",
        "tipo": "Gestor",
        "pessoa": "PF",
        "nome": "JOAO DA SILVA",
        "cnpj": None,
        "situacao": "EM FUNCIONAMENTO NORMAL",
        "data_registro": "2020-01-01",
    }
    result = compare_snapshot([registro_pf])

    assert len(result.novos) == 1
    assert result.novos[0]["cnpj"] is None


def test_mudanca_de_situacao_e_marcada_como_alteracao(temp_db):
    from src.comparator import compare_snapshot
    from src.storage import save_snapshot

    save_snapshot(
        [_registro("11.111.111/0001-11", "Empresa A", situacao="EM FUNCIONAMENTO NORMAL")],
        data_coleta="2024-01-01",
    )

    result = compare_snapshot(
        [_registro("11.111.111/0001-11", "Empresa A", situacao="CANCELADA")]
    )

    assert result.novos == []
    assert len(result.alterados) == 1
    assert result.alterados[0]["situacao_anterior"] == "EM FUNCIONAMENTO NORMAL"