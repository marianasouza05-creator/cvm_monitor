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
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "cvm_monitor.db"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# --- Chave de LLM (opcional) ---
# Se não configurada, o módulo de IA simplesmente não roda (fallback textual).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_ENABLED = bool(ANTHROPIC_API_KEY)

# --- Flag legado (não usada mais na prática) ---
# O app.py agora decide a fonte via toggle na interface (real vs. demo),
# então esta flag não controla mais nada — mantida só por compatibilidade.
USE_MOCK_SOURCE = False

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")