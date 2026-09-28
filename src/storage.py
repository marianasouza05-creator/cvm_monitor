"""
Camada de armazenamento histórico.

Usa SQLite (arquivo único, zero setup) para guardar, para cada execução:
  - um snapshot completo do que foi coletado naquele dia (tabela `snapshots`)
  - os registros marcados como "novos" naquele dia (tabela `novos_registros`)

A chave de identidade de uma entidade é `chave_unica` = identificador +
"|" + data_registro, onde identificador é o CNPJ (pessoa jurídica) ou o
NOME (pessoa física — a CVM não disponibiliza CPF nos dados abertos).

Por que uma chave composta e não só o identificador? Porque o arquivo da
CVM é um histórico completo (inclui cancelados), e uma mesma empresa/pessoa
pode se recadastrar depois de cancelar — nesse caso ela ganha uma nova
data de registro. Tratar isso como "novo" é o comportamento correto do
ponto de vista de negócio (ver src/collector.py para o caso real que
motivou essa decisão).
"""
import sqlite3
from contextlib import contextmanager
from datetime import date

from src.config import DB_PATH
from src.logger_config import get_logger

logger = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_coleta TEXT NOT NULL,
    chave_unica TEXT NOT NULL,
    tipo TEXT NOT NULL,
    pessoa TEXT NOT NULL,
    nome TEXT NOT NULL,
    cnpj TEXT,
    situacao TEXT,
    data_registro TEXT,
    UNIQUE(data_coleta, chave_unica)
);

CREATE TABLE IF NOT EXISTS novos_registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_deteccao TEXT NOT NULL,
    chave_unica TEXT NOT NULL,
    tipo TEXT NOT NULL,
    pessoa TEXT NOT NULL,
    nome TEXT NOT NULL,
    cnpj TEXT,
    situacao TEXT,
    data_registro TEXT
);

CREATE TABLE IF NOT EXISTS registros_injetados_demo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_unica TEXT NOT NULL,
    tipo TEXT NOT NULL,
    pessoa TEXT NOT NULL,
    nome TEXT NOT NULL,
    cnpj TEXT,
    situacao TEXT,
    data_registro TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info("Banco de dados inicializado em %s", DB_PATH)


def save_snapshot(records: list[dict], data_coleta: str | None = None) -> None:
    """Salva o snapshot do dia. Usa INSERT OR IGNORE para não duplicar
    caso a coleta seja rodada mais de uma vez no mesmo dia."""
    data_coleta = data_coleta or date.today().isoformat()
    with get_conn() as conn:
        for r in records:
            conn.execute(
                """
                INSERT OR IGNORE INTO snapshots
                    (data_coleta, chave_unica, tipo, pessoa, nome, cnpj, situacao, data_registro)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data_coleta,
                    r["chave_unica"],
                    r["tipo"],
                    r["pessoa"],
                    r["nome"],
                    r.get("cnpj"),
                    r.get("situacao"),
                    r.get("data_registro"),
                ),
            )
    logger.info("Snapshot de %s salvo (%d registros).", data_coleta, len(records))


def get_all_known_chaves(before_date: str | None = None) -> set[str]:
    """Retorna o conjunto de chaves únicas já vistas em QUALQUER snapshot
    anterior. É essa a base para decidir se um registro é 'novo'."""
    query = "SELECT DISTINCT chave_unica FROM snapshots"
    params = ()
    if before_date:
        query += " WHERE data_coleta < ?"
        params = (before_date,)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return {row["chave_unica"] for row in rows}


def get_latest_snapshot_by_chave(chave_unica: str) -> dict | None:
    """Retorna o registro mais recente conhecido para uma dada chave única
    (usado para detectar alteração de nome/situação sem confundir com 'novo')."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM snapshots
            WHERE chave_unica = ?
            ORDER BY data_coleta DESC
            LIMIT 1
            """,
            (chave_unica,),
        ).fetchone()
    return dict(row) if row else None


def save_new_records(records: list[dict], data_deteccao: str | None = None) -> None:
    data_deteccao = data_deteccao or date.today().isoformat()
    with get_conn() as conn:
        for r in records:
            conn.execute(
                """
                INSERT INTO novos_registros
                    (data_deteccao, chave_unica, tipo, pessoa, nome, cnpj, situacao, data_registro)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data_deteccao,
                    r["chave_unica"],
                    r["tipo"],
                    r["pessoa"],
                    r["nome"],
                    r.get("cnpj"),
                    r.get("situacao"),
                    r.get("data_registro"),
                ),
            )
    logger.info("%d novos registros persistidos para %s.", len(records), data_deteccao)


def get_new_records_by_date(data: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM novos_registros WHERE data_deteccao = ?", (data,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_history_dates() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT data_deteccao FROM novos_registros ORDER BY data_deteccao DESC"
        ).fetchall()
    return [r["data_deteccao"] for r in rows]


def get_totals() -> dict:
    with get_conn() as conn:
        latest_date_row = conn.execute(
            "SELECT MAX(data_coleta) as d FROM snapshots"
        ).fetchone()
        latest_date = latest_date_row["d"]
        if not latest_date:
            return {"gestores": 0, "consultorias": 0, "ultima_atualizacao": None}
        gestores = conn.execute(
            "SELECT COUNT(DISTINCT chave_unica) c FROM snapshots WHERE tipo='Gestor'"
        ).fetchone()["c"]
        consultorias = conn.execute(
            "SELECT COUNT(DISTINCT chave_unica) c FROM snapshots WHERE tipo='Consultoria'"
        ).fetchone()["c"]
    return {
        "gestores": gestores,
        "consultorias": consultorias,
        "ultima_atualizacao": latest_date,
    }


# ---------------------------------------------------------------------------
# Utilitário exclusivo do MODO DEMO (mock) — permite injetar registros
# fictícios para simular a chegada de novos cadastros no dia seguinte.
# ---------------------------------------------------------------------------
def add_injected_record(record: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO registros_injetados_demo
                (chave_unica, tipo, pessoa, nome, cnpj, situacao, data_registro)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["chave_unica"],
                record["tipo"],
                record.get("pessoa", "PJ"),
                record["nome"],
                record.get("cnpj"),
                record.get("situacao", "EM FUNCIONAMENTO NORMAL"),
                record.get("data_registro"),
            ),
        )


def get_injected_records() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM registros_injetados_demo").fetchall()
    return [dict(r) for r in rows]


def clear_injected_records() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM registros_injetados_demo")