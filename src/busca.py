"""Consulta de alíquota interna por NCM e vínculo legal cadastrado."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd

from .modelos import BaseTributaria, Candidato, HipoteseEspecial, PREFIXOS_NCM_VALIDOS, ResultadoConsulta
from .normalizacao import normalizar_ncm

# A alíquota modal não confirma, sozinha, o enquadramento tributário do produto.
INICIO_ALIQUOTA_MODAL_19 = date(2024, 4, 1)
ALIQUOTA_MODAL_GO = Decimal("19")
FONTE_CTE_GO = "https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm"


def _hipoteses_legais_condicionadas(ncm: str, referencia: date) -> list[HipoteseEspecial]:
    """Ressalvas documentadas; não cadastram alíquota definitiva nem benefício."""

    if ncm != "04029900" or referencia < INICIO_ALIQUOTA_MODAL_19:
        return []
    return [
        HipoteseEspecial(
            aliquota=Decimal("12"),
            descricao="Leite em estado natural, pasteurizado ou esterilizado (UHT)",
            fundamento="Lei nº 11.651/1991, art. 27, inciso II, alínea b",
            fonte=FONTE_CTE_GO,
            condicao=(
                "Somente se as características reais da mercadoria atenderem à "
                "descrição prevista em lei. O NCM 04029900, isoladamente, não "
                "comprova o direito aos 12%; pode abranger outros produtos, "
                "inclusive leite condensado."
            ),
        ),
    ]


def texto(valor: Any) -> str:
    """Converte uma célula preenchida em texto sem expor NaN."""

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
    """Classifica limites inclusivos e datas inconsistentes sem inferir revogação."""

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
        return len(chave) == 8 and chave == ncm
    if tipo == "PREFIXO":
        return len(chave) in PREFIXOS_NCM_VALIDOS and ncm.startswith(chave)
    return False


def _fundamento(base: BaseTributaria, candidato: Candidato, referencia: date) -> None:
    chave = texto(candidato.dados.get("id_legislacao"))
    if not chave:
        candidato.problema_fundamento = "Regra sem fundamento legal cadastrado."
        return
    encontrados = [linha for linha in base.legislacao.to_dict("records")
                   if texto(linha.get("id_legislacao")) == chave and _ativo(linha)]
    if not encontrados:
        candidato.problema_fundamento = "Fundamento legal inexistente ou inativo na base."
        return
    if len(encontrados) != 1:
        candidato.problema_fundamento = "Há mais de um fundamento legal ativo para a regra."
        return
    fundamento = encontrados[0]
    candidato.legislacao = fundamento
    if situacao_vigencia(fundamento, referencia) != "VIGENTE":
        candidato.problema_fundamento = "Vigência do fundamento legal exige verificação."
        return
    if _data(fundamento.get("vigencia_inicio")) is None:
        candidato.problema_fundamento = "Início de vigência do fundamento legal não cadastrado."
        return
    try:
        verificada_em = _data(fundamento.get("data_verificacao"))
    except ValueError:
        verificada_em = None
    if verificada_em is None or verificada_em > referencia:
        candidato.problema_fundamento = "Verificação do fundamento legal ausente ou inconsistente."
        return
    if not all(texto(fundamento.get(campo)) for campo in ("norma", "numero", "ano")):
        candidato.problema_fundamento = "Identificação da norma incompleta na base."
        return
    if not any(texto(fundamento.get(campo)) for campo in ("artigo", "anexo", "inciso", "item")):
        candidato.problema_fundamento = "Dispositivo legal específico não cadastrado."
        return
    try:
        url = urlparse(texto(fundamento.get("url_fonte")))
        fonte_valida = url.scheme in {"http", "https"} and bool(url.netloc)
    except ValueError:
        fonte_valida = False
    if not fonte_valida:
        candidato.problema_fundamento = "Endereço da fonte ausente ou inválido na base."


def _percentual_valido(valor: Any) -> bool:
    try:
        numero = Decimal(texto(valor).replace(",", "."))
    except InvalidOperation:
        return False
    return numero.is_finite() and 0 <= numero <= 100


def consultar(base: BaseTributaria, ncm: str, data_referencia: date | None = None) -> ResultadoConsulta:
    """Seleciona uma única alíquota interna quando o cadastro permite fazê-lo."""

    normalizado = normalizar_ncm(ncm)
    referencia = data_referencia or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    resultado = ResultadoConsulta(
        ncm_original=ncm,
        ncm_normalizado=normalizado,
        data_referencia=referencia,
    )
    for linha in base.ncm.to_dict("records"):
        if texto(linha.get("ncm")) == normalizado and _ativo(linha):
            resultado.descricao_oficial = texto(linha.get("descricao_oficial"))
            break
    else:
        resultado.situacao = "NCM_NAO_ENCONTRADO"
        return resultado

    resultado.hipoteses_especiais = _hipoteses_legais_condicionadas(normalizado, referencia)

    for linha in base.aliquotas.to_dict("records"):
        if not _ativo(linha) or not _corresponde(normalizado, linha):
            continue
        candidato = Candidato(
            identificador=texto(linha.get("id_regra")),
            chave_ncm=texto(linha.get("chave_ncm")),
            tipo_correspondencia=texto(linha.get("tipo_correspondencia")).upper(),
            dados=linha,
            vigencia=situacao_vigencia(linha, referencia),
            exige_descricao=texto(linha.get("exige_descricao")).upper() or "NAO",
        )
        _fundamento(base, candidato, referencia)
        resultado.candidatos_aliquota.append(candidato)
    resultado.candidatos_aliquota.sort(key=lambda candidato: candidato.prioridade, reverse=True)
    if not resultado.candidatos_aliquota:
        resultado.situacao = "SEM_TRATAMENTO_CADASTRADO"
        if referencia >= INICIO_ALIQUOTA_MODAL_19:
            resultado.aliquota_geral_referencia = ALIQUOTA_MODAL_GO
        return resultado

    vigentes = [c for c in resultado.candidatos_aliquota if c.vigencia == "VIGENTE"]
    if not vigentes:
        resultado.situacao = "SEM_REGRA_VIGENTE"
        return resultado
    prioridade = vigentes[0].prioridade
    resultado.possibilidades_aliquota = [c for c in vigentes if c.prioridade == prioridade]
    if len(resultado.possibilidades_aliquota) != 1:
        resultado.situacao = "VERIFICACAO_NECESSARIA"
        return resultado
    escolhida = resultado.possibilidades_aliquota[0]
    if (escolhida.problema_fundamento or escolhida.exige_descricao != "NAO"
            or _data(escolhida.dados.get("vigencia_inicio")) is None
            or not _percentual_valido(escolhida.dados.get("aliquota_icms"))):
        resultado.situacao = "VERIFICACAO_NECESSARIA"
        return resultado
    resultado.regra_priorizada = escolhida
    return resultado
