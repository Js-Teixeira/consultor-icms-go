"""Contrato único consumido pela interface e pelo motor tributário."""

from typing import Protocol

from src.modelos import BaseTributaria


class ErroConfiguracaoDados(ValueError):
    """Configuração de fonte inválida, sem detalhes de credenciais."""


class ErroFonteDados(RuntimeError):
    """Falha de acesso à fonte selecionada, sem troca implícita de fonte."""


class RepositorioTributario(Protocol):
    nome_fonte: str

    def carregar_base(self) -> BaseTributaria:
        """Devolve as tabelas no formato esperado pelo motor atual."""

    def testar_conexao(self) -> bool:
        """Executa uma verificação leve e retorna apenas o estado."""
