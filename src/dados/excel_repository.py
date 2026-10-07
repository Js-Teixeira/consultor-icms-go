"""Adaptador da planilha local para o contrato do motor."""

from pathlib import Path

from src.carregamento import CAMINHO_BASE, carregar_base
from src.modelos import BaseTributaria


class ExcelRepository:
    nome_fonte = "Excel local"

    def __init__(self, caminho: str | Path = CAMINHO_BASE) -> None:
        self.caminho = Path(caminho)

    def carregar_base(self) -> BaseTributaria:
        """Reutiliza integralmente a leitura e validação Excel existentes."""

        return carregar_base(self.caminho)

    def testar_conexao(self) -> bool:
        """Verifica somente a disponibilidade do arquivo local."""

        return self.caminho.is_file()
