"""Opções provenientes do cadastro; benefícios não representam Ex da TIPI."""

from dataclasses import dataclass

from .busca import texto
from .modelos import Candidato, ResultadoConsulta


@dataclass(frozen=True)
class OpcaoConsulta:
    chave: str
    descricao: str
    natureza: str
    regra: Candidato | None = None


def opcoes_consulta(resultado: ResultadoConsulta) -> list[OpcaoConsulta]:
    """Usa tratamentos reais ou o único registro do catálogo, sem criar desdobramentos."""

    if resultado.situacao == "NCM_NAO_ENCONTRADO":
        return []
    if resultado.possibilidades_aliquota:
        return [OpcaoConsulta(
            chave=f"aliquota:{indice}:{regra.identificador}",
            descricao=texto(regra.dados.get("descricao_regra")) or resultado.descricao_oficial
                      or "Descrição não cadastrada",
            natureza="Tratamento de ICMS cadastrado",
            regra=regra,
        ) for indice, regra in enumerate(resultado.possibilidades_aliquota)]
    return [OpcaoConsulta(
        chave=f"classificacao:{resultado.ncm_normalizado}",
        descricao=resultado.descricao_oficial or "Descrição não cadastrada",
        natureza="Classificação NCM cadastrada",
    )]
