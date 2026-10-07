"""Classificação explicável da confiança da consulta."""

import pandas as pd

from .modelos import ResultadoConsulta

SCORE_MINIMO_DESCRICAO = 70.0
MENSAGEM_DESCRICAO_NECESSARIA = (
    "Esta regra depende da identificação do produto. Informe a descrição para aumentar a precisão da consulta."
)


def _valor_ausente(valor: object) -> bool:
    return valor is None or pd.isna(valor) or str(valor).strip() == ""


def _motivo_descricao(informada: bool) -> str:
    if not informada:
        return MENSAGEM_DESCRICAO_NECESSARIA
    return "A descrição informada não corresponde claramente à regra que exige identificação do produto."


def avaliar_confianca(resultado: ResultadoConsulta) -> None:
    """Considera especificidade, empates, texto, vigência e vínculo legal."""

    if resultado.situacao != "ENCONTRADO":
        resultado.nivel_confianca = "REVISAO_NECESSARIA"
        if resultado.situacao == "NCM_NAO_ENCONTRADO":
            resultado.motivos_confianca.append("NCM não encontrado na tabela oficial cadastrada.")
        elif resultado.situacao == "SEM_TRATAMENTO_CADASTRADO":
            resultado.motivos_confianca.append(
                "NCM validado na tabela oficial; tratamento tributário de Goiás ainda não cadastrado na base."
            )
        elif resultado.situacao == "SEM_REGRA_VIGENTE":
            resultado.motivos_confianca.append("Nenhuma regra correspondente está vigente na data consultada.")
        return

    informada = bool(resultado.descricao_original.strip())
    candidatos = resultado.candidatos_aliquota + resultado.candidatos_beneficio
    revisao: list[str] = []
    media: list[str] = []

    if any(c.vigencia == "INCONSISTENTE" for c in candidatos):
        revisao.append("Há regra correspondente com datas de vigência inconsistentes.")
    if any(c.vigencia == "VIGENTE" and c.problema_fundamento for c in candidatos):
        revisao.append("Há regra vigente com fundamento ausente ou com vigência inconsistente.")
    if any(c.escopo_operacao == "NAO_DEFINIDA" for c in resultado.beneficios_encontrados):
        revisao.append("O escopo da operação de um benefício ainda não está estruturado na base.")

    regra = resultado.regra_priorizada
    possibilidades = resultado.possibilidades_aliquota
    if regra:
        if _valor_ausente(regra.dados.get("aliquota_icms")):
            revisao.append("A regra priorizada não possui alíquota cadastrada.")
        if regra.tipo_correspondencia == "PREFIXO":
            media.append("A alíquota foi encontrada por prefixo de NCM; confira o enquadramento do produto.")
        if informada and (regra.score_descricao or 0) < SCORE_MINIMO_DESCRICAO:
            media.append("A descrição informada não corresponde claramente ao texto da regra priorizada.")
        if len(possibilidades) > 1:
            media.append("A descrição priorizou uma regra, mas há outras candidatas igualmente específicas.")
    elif len(possibilidades) > 1:
        revisao.append("Duas ou mais regras de alíquota igualmente específicas permanecem plausíveis.")
    elif len(possibilidades) == 1 and possibilidades[0].exige_descricao == "SIM":
        motivo = _motivo_descricao(informada)
        if not informada and possibilidades[0].tipo_correspondencia == "EXATO":
            media.append(motivo)
        else:
            revisao.append(motivo)
    else:
        revisao.append("Não foi possível priorizar uma regra de alíquota vigente.")

    if resultado.beneficios_pendentes:
        beneficios = resultado.beneficios_possiveis
        if len(beneficios) > 1:
            revisao.append("Há benefícios igualmente específicos sem desempate seguro.")
        elif beneficios and beneficios[0].exige_descricao == "SIM":
            motivo = _motivo_descricao(informada)
            (revisao if informada else media).append(motivo)
        else:
            revisao.append("O benefício não pôde ser priorizado com segurança.")
    elif any("priorizou um benefício" in motivo for motivo in resultado.ambiguidades):
        media.append("A descrição priorizou um benefício entre alternativas igualmente específicas.")

    if revisao:
        resultado.nivel_confianca = "REVISAO_NECESSARIA"
        resultado.motivos_confianca = revisao + media
    elif media:
        resultado.nivel_confianca = "MEDIA"
        resultado.motivos_confianca = media
    else:
        resultado.nivel_confianca = "ALTA"
        vigencia_determinada = bool(regra and all(
            not _valor_ausente(regra.dados.get(campo))
            for campo in ("vigencia_inicio", "vigencia_fim")
        ))
        qualificacao = "vigente" if vigencia_determinada else "ativa na base"
        resultado.motivos_confianca = [
            f"Uma regra EXATA {qualificacao} foi priorizada por NCM, "
            "com fundamento cadastrado e identificação suficiente."
        ]
