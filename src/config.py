"""
Configurações centrais do projeto.

Lê variáveis de ambiente (via .env, se presente) e define caminhos padrão.
Nada de segredos hardcoded aqui — tudo vem de variável de ambiente.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv é opcional; se não estiver instalado, seguimos só com
    # variáveis de ambiente já exportadas no sistema/CI.
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# MONITOR_DATA_DIR permite apontar os dados para outra pasta (útil em testes).
DATA_DIR = Path(os.getenv("MONITOR_DATA_DIR", BASE_DIR / "data"))
REPORTS_DIR = DATA_DIR / "reports"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "monitor.db"

for _d in (DATA_DIR, REPORTS_DIR, RAW_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Chave de LLM (opcional) ---
# Se não configurada, o módulo de IA simplesmente não roda (fallback textual).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_ENABLED = bool(ANTHROPIC_API_KEY)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Situação cadastral considerada "ativa" nos totais do painel.
SITUACAO_ATIVA = "EM FUNCIONAMENTO NORMAL"

# Status do funil comercial (campo interno, separado dos dados da CVM).
STATUS_COMERCIAL = ["Novo lead", "Prioritário", "Abordado", "Em conversa", "Sem interesse"]