"""
Camada de armazenamento (SQLite, arquivo único em data/monitor.db).

Modelo — uma linha por entidade, não uma foto por dia:

  entidades   dados da CVM + primeira_deteccao (data em que o monitor viu a
              entidade pela 1ª vez) + baseline (1 = já existia na carga inicial,
              logo NÃO conta como "novo detectado")
  cargas      log de cada atualização (data, totais, status ok/erro)
  alteracoes  histórico de mudanças (nome, situação, contato)
  leads       dados COMERCIAIS internos (status, responsável, observações),
              separados dos dados oficiais da CVM e nunca sobrescritos por
              uma nova carga.

Dois conceitos de data, como no briefing:
  data_registro      -> data do registro na CVM (fonte)
  primeira_deteccao  -> data em que o monitor detectou a entidade
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pandas as pd

from src.collector import CAMPOS
from src.config import DB_PATH
from src.logger_config import get_logger

logger = get_logger(__name__)


def _definicao_entidades() -> str:
    colunas = []
    for c in CAMPOS:
        if c == "chave_unica":
            colunas.append("chave_unica TEXT PRIMARY KEY")
        elif c == "patrimonio_liquido":
            colunas.append("patrimonio_liquido REAL")
        elif c in ("tipo", "pessoa", "nome"):
            colunas.append(f"{c} TEXT NOT NULL")
        else:
            colunas.append(f"{c} TEXT")
    colunas += [
        "primeira_deteccao TEXT NOT NULL",
        "ultima_vista TEXT NOT NULL",
        "baseline INTEGER NOT NULL DEFAULT 0",
        "ativo_na_fonte INTEGER NOT NULL DEFAULT 1",
    ]
    return ",\n    ".join(colunas)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS entidades (
    {_definicao_entidades()}
);
CREATE INDEX IF NOT EXISTS idx_entidades_registro ON entidades(data_registro);
CREATE INDEX IF NOT EXISTS idx_entidades_deteccao ON entidades(primeira_deteccao);

CREATE TABLE IF NOT EXISTS cargas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_carga TEXT NOT NULL,
    iniciada_em TEXT NOT NULL,
    total INTEGER DEFAULT 0,
    novos INTEGER DEFAULT 0,
    alterados INTEGER DEFAULT 0,
    removidos INTEGER DEFAULT 0,
    baseline INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    mensagem TEXT
);

CREATE TABLE IF NOT EXISTS alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    chave_unica TEXT NOT NULL,
    campo TEXT NOT NULL,
    valor_anterior TEXT,
    valor_novo TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    chave_unica TEXT PRIMARY KEY,
    status TEXT,
    owner TEXT,
    linkedin TEXT,
    contato_extra TEXT,
    observacoes TEXT,
    atualizado_em TEXT
);
"""

CAMPOS_COMPARACAO = ["nome", "situacao", "uf", "municipio", "email", "site", "telefone", "ativo_na_fonte"]


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


# ----------------------------------------------------------------------------
# Cargas
# ----------------------------------------------------------------------------
def has_baseline() -> bool:
    """True se já existe ao menos uma carga concluída (a base de comparação)."""
    with get_conn() as conn:
        return conn.execute("SELECT 1 FROM cargas WHERE status = 'ok' LIMIT 1").fetchone() is not None


def load_existing() -> dict[str, dict]:
    """Campos de comparação de todas as entidades conhecidas, por chave."""
    colunas = ", ".join(["chave_unica"] + CAMPOS_COMPARACAO)
    with get_conn() as conn:
        rows = conn.execute(f"SELECT {colunas} FROM entidades").fetchall()
    return {r["chave_unica"]: dict(r) for r in rows}


def apply_carga(result, data_carga: str, iniciada_em: str) -> None:
    """
    Grava o resultado de uma comparação em uma única transação:
    upsert de todas as entidades (preserva primeira_deteccao e baseline das
    que já existiam), histórico de alterações, ausentes da fonte e log da carga.
    """
    colunas = CAMPOS + ["primeira_deteccao", "ultima_vista", "baseline", "ativo_na_fonte"]
    atualizaveis = [c for c in CAMPOS if c != "chave_unica"]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in atualizaveis)
    sql = (
        f"INSERT INTO entidades ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))}) "
        f"ON CONFLICT(chave_unica) DO UPDATE SET {set_clause}, "
        f"ultima_vista = excluded.ultima_vista, ativo_na_fonte = 1"
    )
    flag_baseline = 1 if result.baseline else 0
    linhas = [
        tuple(r.get(c) for c in CAMPOS) + (data_carga, data_carga, flag_baseline, 1)
        for r in result.registros
    ]
    historico = [
        (data_carga, r["chave_unica"], campo, antes, depois)
        for r in result.alterados
        for campo, antes, depois in r["mudancas"]
    ]

    with get_conn() as conn:
        conn.executemany(sql, linhas)
        if historico:
            conn.executemany(
                "INSERT INTO alteracoes (data, chave_unica, campo, valor_anterior, valor_novo) VALUES (?,?,?,?,?)",
                historico,
            )
        for i in range(0, len(result.removidos), 500):
            lote = result.removidos[i:i + 500]
            conn.execute(
                f"UPDATE entidades SET ativo_na_fonte = 0 WHERE chave_unica IN ({', '.join('?' * len(lote))})",
                lote,
            )
        conn.execute(
            "INSERT INTO cargas (data_carga, iniciada_em, total, novos, alterados, removidos, baseline, status) "
            "VALUES (?,?,?,?,?,?,?, 'ok')",
            (data_carga, iniciada_em, len(result.registros), len(result.novos),
             len(result.alterados), len(result.removidos), flag_baseline),
        )
    logger.info("Carga de %s gravada: %d entidades (%d novas).", data_carga, len(linhas), len(result.novos))


def log_carga_erro(data_carga: str, iniciada_em: str, mensagem: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cargas (data_carga, iniciada_em, status, mensagem) VALUES (?,?, 'erro', ?)",
            (data_carga, iniciada_em, mensagem[:500]),
        )


def last_carga() -> dict | None:
    """Última tentativa de carga (ok ou erro)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cargas ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def last_ok_carga() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cargas WHERE status = 'ok' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_cargas(limite: int = 30) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM cargas ORDER BY id DESC LIMIT ?", conn, params=(limite,))


def get_alteracoes(limite: int = 200) -> pd.DataFrame:
    sql = (
        "SELECT a.data, e.tipo, e.pessoa, e.nome, a.campo, a.valor_anterior, a.valor_novo "
        "FROM alteracoes a LEFT JOIN entidades e USING (chave_unica) ORDER BY a.id DESC LIMIT ?"
    )
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=(limite,))


# ----------------------------------------------------------------------------
# Leitura para a interface
# ----------------------------------------------------------------------------
def load_entidades_df() -> pd.DataFrame:
    """Todas as entidades + dados comerciais (leads), prontas para análise."""
    sql = (
        "SELECT e.*, l.status AS status_comercial, l.owner, l.linkedin, l.contato_extra, "
        "l.observacoes, l.atualizado_em AS lead_atualizado_em "
        "FROM entidades e LEFT JOIN leads l USING (chave_unica)"
    )
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn)


def get_data_version() -> tuple:
    """Muda sempre que há nova carga ou edição comercial (invalida o cache da UI)."""
    with get_conn() as conn:
        carga = conn.execute("SELECT COALESCE(MAX(id), 0) FROM cargas").fetchone()[0]
        lead = conn.execute("SELECT COALESCE(MAX(atualizado_em), '') FROM leads").fetchone()[0]
    return (carga, lead)


# ----------------------------------------------------------------------------
# Dados comerciais (internos)
# ----------------------------------------------------------------------------
def save_lead(chave_unica: str, status: str | None, owner: str | None = None,
              linkedin: str | None = None, contato_extra: str | None = None,
              observacoes: str | None = None) -> None:
    agora = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO leads (chave_unica, status, owner, linkedin, contato_extra, observacoes, atualizado_em) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(chave_unica) DO UPDATE SET status=excluded.status, "
            "owner=excluded.owner, linkedin=excluded.linkedin, contato_extra=excluded.contato_extra, "
            "observacoes=excluded.observacoes, atualizado_em=excluded.atualizado_em",
            (chave_unica, status or None, owner or None, linkedin or None, contato_extra or None,
             observacoes or None, agora),
        )


def save_leads_status(chaves: list[str], status: str) -> None:
    """Define o status de várias entidades de uma vez, sem apagar as demais anotações."""
    agora = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO leads (chave_unica, status, atualizado_em) VALUES (?,?,?) "
            "ON CONFLICT(chave_unica) DO UPDATE SET status=excluded.status, atualizado_em=excluded.atualizado_em",
            [(c, status, agora) for c in chaves],
        )