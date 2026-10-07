"""Busca por NCM, vigência, descrição e vínculo legal."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

from .confianca import SCORE_MINIMO_DESCRICAO, avaliar_confianca
from .modelos import BaseTributaria, Candidato, Operacao, PREFIXOS_NCM_VALIDOS, ResultadoConsulta
from .normalizacao import normalizar_ncm, normalizar_texto

# Limites de ranking textual. O texto nunca exclui uma regra encontrada por NCM.
MARGEM_DESEMPATE_DESCRICAO = 15.0


def texto(valor: Any) -> str:
    """Converte uma célula preenchida em texto sem expor NaN na interface."""

    if valor is None or pd.isna(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _ativo(linha: dict[str, Any]) -> bool:
    return texto(linha.get("ativo")).upper() == "SIM"


def _data(valor: Any) -> date | None:
    if not texto(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):
        raise ValueError("Data numérica sem formato reconhecível")
    try:
        return date.fromisoformat(texto(valor)[:10])
    except ValueError as exc:
        raise ValueError("Data inválida") from exc


def situacao_vigencia(linha: dict[str, Any], referencia: date) -> str:
    """Classifica limites inclusivos, vazios, vencidos e inconsistentes."""

    try:
        inicio = _data(linha.get("vigencia_inicio"))
        fim = _data(linha.get("vigencia_fim"))
    except ValueError:
        return "INCONSISTENTE"
    if inicio and fim and inicio > fim:
        return "INCONSISTENTE"
    if (inicio and referencia < inicio) or (fim and referencia > fim):
        return "FORA_DA_VIGENCIA"
    return "VIGENTE"


def _corresponde(ncm: str, linha: dict[str, Any]) -> bool:
    chave = texto(linha.get("chave_ncm"))
    tipo = texto(linha.get("tipo_correspondencia")).upper()
    if not chave.isascii() or not chave.isdigit():
        return False
    if tipo == "EXATO":
        return len(chave) == 8 and ncm == chave
    if tipo == "PREFIXO":
        return len(chave) in PREFIXOS_NCM_VALIDOS and ncm.startswith(chave)
    return False


def _scores_descricao(descricao: str, linha: dict[str, Any]) -> tuple[list[str], float | None, str, float | None, float | None]:
    """Compara separadamente a regra e cada termo da lista de palavras-chave."""

    palavras = [termo.strip() for termo in texto(linha.get("palavras_chave")).split(";") if termo.strip()]
    if not descricao:
        return palavras, None, "", None, None
    texto_regra = normalizar_texto(texto(linha.get("descricao_regra")))
    score_regra = round(fuzz.WRatio(descricao, texto_regra), 1) if texto_regra else None
    scores_palavras = [(termo, round(fuzz.WRatio(descricao, normalizar_texto(termo)), 1)) for termo in palavras]
    melhor_termo, melhor_score = max(scores_palavras, key=lambda item: item[1], default=("", None))
    pontuacoes = [score for score in (score_regra, melhor_score) if score is not None]
    return palavras, score_regra, melhor_termo, melhor_score, max(pontuacoes, default=0.0)


def _fundamento(base: BaseTributaria, candidato: Candidato, referencia: date) -> None:
    chave = texto(candidato.dados.get("id_legislacao"))
    if not chave:
        candidato.problema_fundamento = "Regra sem id_legislacao cadastrado."
        return
    encontrados = [linha for linha in base.legislacao.to_dict("records") if texto(linha.get("id_legislacao")) == chave and _ativo(linha)]
    if not encontrados:
        candidato.problema_fundamento = f"Fundamento {chave} não cadastrado ou inativo."
        return
    if len(encontrados) > 1:
        candidato.problema_fundamento = f"Mais de um fundamento ativo com id_legislacao {chave}."
        return
    candidato.legislacao = encontrados[0]
    vigencia = situacao_vigencia(encontrados[0], referencia)
    if vigencia != "VIGENTE":
        candidato.problema_fundamento = f"Vigência do fundamento {chave}: {vigencia}."


def _candidatos(
    base: BaseTributaria, tabela: pd.DataFrame, categoria: str,
    ncm: str, descricao: str, referencia: date,
) -> list[Candidato]:
    nome_id = "id_regra" if categoria == "aliquota" else "id_beneficio"
    encontrados: list[Candidato] = []
    for linha in tabela.to_dict("records"):
        if not _ativo(linha) or not _corresponde(ncm, linha):
            continue
        palavras, score_regra, melhor_termo, score_termo, score_final = _scores_descricao(descricao, linha)
        escopo = texto(linha.get("escopo_operacao")).upper() or "NAO_DEFINIDA"
        candidato = Candidato(
            categoria=categoria,
            identificador=texto(linha.get(nome_id)),
            chave_ncm=texto(linha.get("chave_ncm")),
            tipo_correspondencia=texto(linha.get("tipo_correspondencia")).upper(),
            dados=linha,
            vigencia=situacao_vigencia(linha, referencia),
            exige_descricao=texto(linha.get("exige_descricao")).upper() or "NAO",
            grupo_beneficio=texto(linha.get("grupo_beneficio")),
            aplicacao=texto(linha.get("aplicacao")).upper(),
            palavras_chave_utilizadas=palavras,
            score_descricao_regra=score_regra,
            melhor_palavra_chave=melhor_termo,
            score_melhor_palavra_chave=score_termo,
            score_descricao=score_final,
            escopo_operacao=escopo if categoria == "beneficio" else "NAO_DEFINIDA",
            cbenef=texto(linha.get("cbenef")) if categoria == "beneficio" else "",
        )
        _fundamento(base, candidato, referencia)
        encontrados.append(candidato)
    return sorted(encontrados, key=lambda c: (c.prioridade, c.score_descricao or 0), reverse=True)


def _priorizar(candidatos: list[Candidato]) -> tuple[Candidato | None, list[Candidato], bool]:
    vigentes = [c for c in candidatos if c.vigencia == "VIGENTE"]
    if not vigentes:
        return None, [], False
    maior = max(c.prioridade for c in vigentes)
    empatados = [c for c in vigentes if c.prioridade == maior]
    if len(empatados) == 1:
        return empatados[0], empatados, False
    ordenados = sorted(empatados, key=lambda c: c.score_descricao or 0, reverse=True)
    primeiro, segundo = ordenados[:2]
    if (primeiro.score_descricao is not None
            and primeiro.score_descricao >= SCORE_MINIMO_DESCRICAO
            and (segundo.score_descricao or 0) < SCORE_MINIMO_DESCRICAO
            and primeiro.score_descricao - (segundo.score_descricao or 0) >= MARGEM_DESEMPATE_DESCRICAO):
        return primeiro, empatados, True
    return None, empatados, False


def _descricao_suficiente(candidato: Candidato, descricao: str) -> bool:
    if candidato.exige_descricao == "NAO":
        return True
    return bool(descricao) and (candidato.score_descricao or 0) >= SCORE_MINIMO_DESCRICAO


def _avaliar_aplicabilidade(candidato: Candidato, operacao: Operacao, *, enquadrado: bool) -> None:
    """Decide apenas com NCM/descrição, vigência e operação estruturada."""

    if not enquadrado:
        candidato.aplicabilidade = "REVISAO_NECESSARIA"
        candidato.motivo_aplicabilidade = "O enquadramento desta regra exige confirmação da descrição ou desempate."
    elif candidato.problema_fundamento or candidato.vigencia != "VIGENTE":
        candidato.aplicabilidade = "REVISAO_NECESSARIA"
        candidato.motivo_aplicabilidade = "A vigência ou o fundamento da regra exige revisão."
    elif candidato.escopo_operacao == "NAO_DEFINIDA":
        candidato.aplicabilidade = "REVISAO_NECESSARIA"
        candidato.motivo_aplicabilidade = "O escopo da operação ainda não está estruturado na base."
    elif candidato.escopo_operacao not in {"INTERNA", "INTERESTADUAL", "AMBAS"}:
        candidato.aplicabilidade = "REVISAO_NECESSARIA"
        candidato.motivo_aplicabilidade = "O escopo da operação cadastrado é inválido."
    elif candidato.escopo_operacao != "AMBAS" and candidato.escopo_operacao != operacao:
        candidato.aplicabilidade = "NAO_APLICAVEL"
        tipo = "interna" if candidato.escopo_operacao == "INTERNA" else "interestadual"
        candidato.motivo_aplicabilidade = f"O benefício cadastrado está vinculado a operação {tipo}."
    elif texto(candidato.dados.get("condicoes")):
        candidato.aplicabilidade = "CONDICIONAL"
        candidato.motivo_aplicabilidade = (
            "A operação é compatível, mas o benefício possui condições legais "
            "que não podem ser comprovadas apenas pelo NCM e pela operação."
        )
    else:
        candidato.aplicabilidade = "APLICAVEL"
        candidato.motivo_aplicabilidade = "NCM, vigência e operação são compatíveis com a regra cadastrada."


def consultar(
    base: BaseTributaria, ncm: str, descricao: str = "", data_referencia: date | None = None,
    operacao: Operacao = "INTERNA",
) -> ResultadoConsulta:
    """Consulta regras sem ocultar empates nem candidatos fora da vigência."""

    if operacao not in {"INTERNA", "INTERESTADUAL"}:
        raise ValueError("Operação inválida; use INTERNA ou INTERESTADUAL.")
    normalizado = normalizar_ncm(ncm)
    referencia = data_referencia or date.today()
    resultado = ResultadoConsulta(ncm_original=ncm, ncm_normalizado=normalizado,
                                 data_referencia=referencia, descricao_original=descricao,
                                 operacao_consultada=operacao)
    ncm_encontrado = False
    for linha in base.ncm.to_dict("records"):
        if texto(linha.get("ncm")) == normalizado and _ativo(linha):
            ncm_encontrado = True
            resultado.descricao_oficial = texto(linha.get("descricao_oficial"))
            break
    if not ncm_encontrado:
        resultado.situacao = "NCM_NAO_ENCONTRADO"
        avaliar_confianca(resultado)
        return resultado
    descricao_limpa = normalizar_texto(descricao)
    resultado.candidatos_aliquota = _candidatos(base, base.aliquotas, "aliquota", normalizado, descricao_limpa, referencia)
    resultado.candidatos_beneficio = _candidatos(base, base.beneficios, "beneficio", normalizado, descricao_limpa, referencia)
    selecionada, empate_aliquota, desempatada = _priorizar(resultado.candidatos_aliquota)
    resultado.possibilidades_aliquota = empate_aliquota
    if selecionada and _descricao_suficiente(selecionada, descricao_limpa):
        resultado.regra_priorizada = selecionada
    vigentes = [c for c in resultado.candidatos_beneficio if c.vigencia == "VIGENTE"]
    resultado.beneficios_encontrados = vigentes
    grupos: dict[str, list[Candidato]] = {}
    for candidato in vigentes:
        # Regras alternativas do mesmo grupo disputam o enquadramento; regras
        # independentes podem ser mostradas juntas sem uma escolha artificial.
        grupo = (f"alternativo:{candidato.grupo_beneficio or candidato.chave_ncm}"
                 if candidato.aplicacao == "ALTERNATIVO" else f"regra:{candidato.identificador}")
        grupos.setdefault(grupo, []).append(candidato)
    beneficio_desempatado = False
    for grupo in grupos.values():
        escolhido, possibilidades, desempatado = _priorizar(grupo)
        beneficio_desempatado |= desempatado
        if escolhido and _descricao_suficiente(escolhido, descricao_limpa):
            resultado.beneficios_priorizados.append(escolhido)
        else:
            resultado.beneficios_possiveis.extend(possibilidades)
    resultado.beneficios_pendentes = bool(resultado.beneficios_possiveis)
    enquadrados = {id(candidato) for candidato in resultado.beneficios_priorizados}
    for candidato in vigentes:
        _avaliar_aplicabilidade(candidato, operacao, enquadrado=id(candidato) in enquadrados)

    if len(empate_aliquota) > 1:
        resultado.ambiguidades.append("Duas ou mais regras de alíquota igualmente específicas correspondem ao NCM.")
    if len(resultado.beneficios_possiveis) > 1 and not beneficio_desempatado:
        resultado.ambiguidades.append("Duas ou mais regras de benefício igualmente específicas permanecem plausíveis.")
    if desempatada:
        resultado.ambiguidades.append("A descrição priorizou uma regra entre regras de alíquota igualmente específicas; confira as alternativas.")
    if beneficio_desempatado:
        resultado.ambiguidades.append("A descrição priorizou um benefício entre regras igualmente específicas; confira as alternativas.")

    todos = resultado.candidatos_aliquota + resultado.candidatos_beneficio
    if not todos:
        resultado.situacao = "SEM_TRATAMENTO_CADASTRADO"
    elif not any(c.vigencia == "VIGENTE" for c in todos):
        resultado.situacao = "SEM_REGRA_VIGENTE"
    avaliar_confianca(resultado)
    return resultado
