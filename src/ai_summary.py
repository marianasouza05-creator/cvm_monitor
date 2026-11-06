"""
Camada de IA — 100% OPCIONAL e COMPLEMENTAR.

A detecção de "o que é novo" já está pronta e correta antes deste módulo ser
chamado (ver comparator.py, baseado em chave_unica). A IA SÓ recebe a lista de
novos registros já calculada e escreve um resumo em linguagem natural. Se a IA
falhar ou não estiver configurada, o relatório continua funcionando normalmente.

Para trocar de provedor: implemente outra classe com `summarize(novos, alterados)`
e devolva-a em `get_provider()`. O modelo pode ser trocado pela variável de
ambiente ANTHROPIC_MODEL.
"""
import os
from abc import ABC, abstractmethod

from src.config import AI_ENABLED, ANTHROPIC_API_KEY
from src.logger_config import get_logger

logger = get_logger(__name__)

MODELO_PADRAO = "claude-sonnet-5-5"


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
    """Chama a API da Anthropic (Claude) para gerar um resumo executivo curto."""

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or os.getenv("ANTHROPIC_MODEL", MODELO_PADRAO)

    def summarize(self, novos: list[dict], alterados: list[dict]) -> str:
        if not novos and not alterados:
            return "Nenhuma novidade relevante para comentar hoje."

        try:
            import anthropic
        except ImportError:
            logger.warning("Pacote 'anthropic' não instalado; pulando resumo IA.")
            return "_(Pacote 'anthropic' não instalado — rode `pip install anthropic`.)_"

        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": self._build_prompt(novos, alterados)}],
            )
            return "".join(b.text for b in response.content if b.type == "text").strip()
        except Exception as exc:  # a IA nunca derruba o pipeline
            logger.error("Falha ao chamar a API da Anthropic: %s", exc)
            return f"_(Não foi possível gerar o resumo por IA: {exc})_"

    @staticmethod
    def _build_prompt(novos: list[dict], alterados: list[dict]) -> str:
        linhas = ["Novos registros de hoje na CVM:"]
        for r in novos[:100]:  # limita o tamanho do prompt
            identificador = r.get("cnpj") or "pessoa física, sem CNPJ"
            local = f", {r['uf']}" if r.get("uf") else ""
            linhas.append(
                f"- [{r['tipo']} / {r.get('pessoa', 'n/d')}] {r['nome']} "
                f"({identificador}{local}, situação: {r.get('situacao', 'n/d')}, "
                f"registrado em {r.get('data_registro', 'n/d')})"
            )
        if len(novos) > 100:
            linhas.append(f"... e mais {len(novos) - 100} registros.")
        if alterados:
            linhas.append("\nRegistros com alteração cadastral (não são novos):")
            for r in alterados[:30]:
                linhas.append(f"- {r['nome']} (registrado em {r.get('data_registro', 'n/d')})")

        linhas.append(
            "\nEscreva um resumo executivo curto (máx. 5 frases), em português, para "
            "um profissional comercial de mercado financeiro. Destaque a quantidade de "
            "novos gestores vs. consultores e qualquer padrão notável. Não invente "
            "informações que não estejam na lista acima."
        )
        return "\n".join(linhas)


def get_provider() -> LLMProvider:
    """Ponto único de troca de provedor de IA."""
    if AI_ENABLED:
        return AnthropicProvider(api_key=ANTHROPIC_API_KEY)
    return NoOpProvider()