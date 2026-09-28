"""
Configuração padrão de logging para todo o projeto.

Uso:
    from src.logger_config import get_logger
    logger = get_logger(__name__)
"""
import logging
import sys
from pathlib import Path

from src.config import DATA_DIR, LOG_LEVEL

LOG_FILE = DATA_DIR / "execucao.log"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        # Evita adicionar handlers duplicados se a função for chamada
        # várias vezes (ex: no Streamlit, que re-executa o script).
        return logger

    logger.setLevel(LOG_LEVEL)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger
