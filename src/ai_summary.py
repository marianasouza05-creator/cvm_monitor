"""
Camada de IA — 100% OPCIONAL e COMPLEMENTAR.

Importante: a detecção de "o que é novo" já está pronta e correta antes
deste módulo ser chamado (ver comparator.py, baseado em chave_unica). A IA
aqui SÓ recebe a lista de novos registros já calculada e produz um resumo
em linguagem natural para facilitar a leitura por um profissional. Se a IA
falhar ou não estiver configurada, o relatório continua funcionando
normalmente, só que sem o resumo textual.

Interface pensada para trocar de provedor facilmente: basta implementar
outra classe com o mesmo método `summarize(novos, alterados)` e trocar a
instância retornada por `get_provider()`.
"""
from abc import ABC, abstractmethod

from src.config import AI_ENABLED, ANTHROPIC_API_KEY
from src.logger_config import get_logger

logger = get_logger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def summarize(self, novos: list[dict], alterados: list[dict]) -> str:
        ...


class NoOpProvider(LLMProvider):
    """Usado quando não há chave de API configurada. Não quebra o pipeline."""

    def summarize(self, novos: list[dict], alterados: list[dict]) -> str:
        return (
            "_(Resumo por IA desabilitado — configure ANTHROPIC_API_KEY no "
            ".env para habilitar o resumo executivo automático.)_"
        )


class AnthropicProvider(LLMProvider):
    """Chama a API da Anthropic (Claude) para gerar um resumo executivo
    curto sobre os novos registros e alterações do dia."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model

    def summarize(self, novos: list[dict], alterados: list[dict]) -> str:
        if not novos and not alterados:
            return "Nenhuma novidade relevante para comentar hoje."

        try:
            import anthropic
        except ImportError:
            logger.warning("Pacote 'anthropic' não instalado; pulando resumo IA.")
            return "_(Pacote 'anthropic' não instalado — rode `pip install anthropic`.)_"

        prompt = self._build_prompt(novos, alterados)
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "".join(text_parts).strip()
        except Exception as exc:  # não deixa o pipeline quebrar por causa da IA
            logger.error("Falha ao chamar a API da Anthropic: %s", exc)
            return f"_(Não foi possível gerar o resumo por IA: {exc})_"

    @staticmethod
    def _build_prompt(novos: list[dict], alterados: list[dict]) -> str:
        linhas = ["Novos registros de hoje na CVM:"]
        for r in novos:
            identificador = r.get("cnpj") or "pessoa física, sem CNPJ"
            linhas.append(
                f"- [{r['tipo']} / {r.get('pessoa', 'n/d')}] {r['nome']} "
                f"({identificador}, situação: {r.get('situacao', 'n/d')}, "
                f"registrado em {r.get('data_registro', 'n/d')})"
            )
        if alterados:
            linhas.append("\nRegistros com alteração cadastral (não são novos):")
            for r in alterados:
                linhas.append(f"- {r['nome']} (registrado em {r.get('data_registro', 'n/d')})")

        linhas.append(
            "\nEscreva um resumo executivo curto (máx. 5 frases), em "
            "português, para um profissional de mercado financeiro. "
            "Destaque quantidade de novos gestores vs. consultorias e "
            "qualquer padrão notável. Não invente informações que não "
            "estejam na lista acima."
        )
        return "\n".join(linhas)


def get_provider() -> LLMProvider:
    """Ponto único de troca de provedor de IA."""
    if AI_ENABLED:
        return AnthropicProvider(api_key=ANTHROPIC_API_KEY)
    return NoOpProvider()