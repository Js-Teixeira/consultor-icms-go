"""Leitura e validação estrutural da base Excel."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .modelos import BaseTributaria
from .modelos import ESCOPOS_OPERACAO

CAMINHO_BASE = Path(__file__).resolve().parents[1] / "base" / "base_tributaria_go.xlsx"
COLUNAS_OBRIGATORIAS = {
    "NCM": {"ncm", "descricao_oficial", "ativo"},
    "Aliquotas": {"id_regra", "chave_ncm", "tipo_correspondencia", "aliquota_icms", "id_legislacao", "vigencia_inicio", "vigencia_fim", "ativo", "exige_descricao"},
    "Beneficios": {"id_beneficio", "chave_ncm", "tipo_correspondencia", "tipo_beneficio", "id_legislacao", "vigencia_inicio", "vigencia_fim", "ativo", "exige_descricao", "grupo_beneficio", "aplicacao"},
    "Legislacao": {"id_legislacao", "norma", "numero", "ano", "url_fonte", "ativo"},
}
VALORES_SIM_NAO = {"SIM", "NAO"}
APLICACOES_BENEFICIO = {"UNICO", "ALTERNATIVO", "CUMULATIVO"}


class ErroBase(ValueError):
    """Erro que pode ser mostrado diretamente ao usuário."""


def carregar_base(caminho: str | Path = CAMINHO_BASE) -> BaseTributaria:
    """Lê todas as abas exigidas e valida nomes e colunas essenciais."""

    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroBase(f"Planilha indisponível: {caminho}")
    try:
        abas = pd.read_excel(caminho, sheet_name=list(COLUNAS_OBRIGATORIAS), dtype=object, engine="openpyxl")
    except ValueError as exc:
        raise ErroBase(f"Aba obrigatória ausente na planilha: {exc}") from exc
    except Exception as exc:
        raise ErroBase(f"Planilha indisponível ou ilegível: {exc}") from exc

    for nome, obrigatorias in COLUNAS_OBRIGATORIAS.items():
        tabela = abas[nome]
        tabela.columns = [str(coluna).strip() for coluna in tabela.columns]
        ausentes = obrigatorias - set(tabela.columns)
        if ausentes:
            raise ErroBase(f"Colunas obrigatórias ausentes em {nome}: {', '.join(sorted(ausentes))}.")
        abas[nome] = tabela.dropna(how="all").reset_index(drop=True)

    for nome in ("Aliquotas", "Beneficios"):
        for indice, linha in abas[nome].iterrows():
            if str(linha["ativo"]).strip().upper() != "SIM":
                continue
            exige = str(linha["exige_descricao"]).strip().upper()
            if exige not in VALORES_SIM_NAO:
                raise ErroBase(f"Valor inválido em {nome}, linha {indice + 2}, coluna exige_descricao: use SIM ou NAO.")
            if nome == "Beneficios":
                valor_aplicacao = linha["aplicacao"]
                aplicacao = "" if pd.isna(valor_aplicacao) else str(valor_aplicacao).strip().upper()
                if aplicacao and aplicacao not in APLICACOES_BENEFICIO:
                    raise ErroBase(f"Valor inválido em Beneficios, linha {indice + 2}, coluna aplicacao: use UNICO, ALTERNATIVO ou CUMULATIVO.")
                valor_escopo = linha.get("escopo_operacao")
                escopo = "" if valor_escopo is None or pd.isna(valor_escopo) else str(valor_escopo).strip().upper()
                if escopo and escopo not in ESCOPOS_OPERACAO:
                    raise ErroBase(f"Valor inválido em Beneficios, linha {indice + 2}, coluna escopo_operacao.")

    return BaseTributaria(
        ncm=abas["NCM"],
        aliquotas=abas["Aliquotas"],
        beneficios=abas["Beneficios"],
        legislacao=abas["Legislacao"],
    )


def base_vazia(base: BaseTributaria) -> bool:
    """Indica que não há regras fiscais cadastradas nas duas abas de regras."""

    def tem_regra_ativa(tabela: pd.DataFrame) -> bool:
        return not tabela.empty and tabela["ativo"].fillna("").astype(str).str.strip().str.upper().eq("SIM").any()

    return not (tem_regra_ativa(base.aliquotas) or tem_regra_ativa(base.beneficios))
