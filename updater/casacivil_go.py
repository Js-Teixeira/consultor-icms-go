"""Localização do conteúdo integral na API pública oficial da Casa Civil."""

from __future__ import annotations

import re
from datetime import date, datetime

from .fontes import ClienteOficial, ErroColeta
from .documentos import extrair_doc
from .modelos import AtoDescoberto, ConteudoOficial
from .normalizacao import identificar_ato, limpar_html, limpar_texto, normalizar_numero_ato, sem_acentos

URL_BUSCA = "https://legisla.casacivil.go.gov.br/api/v2/pesquisa/legislacoes"
TEXTO_CONSOLIDADO = re.compile(r"^\s*texto\s+consolidado\b[^\n]*$", re.IGNORECASE | re.MULTILINE)


def _indicacao_consolidado(texto: str) -> str:
    """Marca apenas indicação textual explícita no cabeçalho do documento."""

    return "SIM" if TEXTO_CONSOLIDADO.search(texto[:500]) else "NAO"


def _tipo_confere(tipo_descoberto: str, tipo_api: str) -> bool:
    esperado = sem_acentos(tipo_descoberto).upper()
    recebido = sem_acentos(tipo_api).upper()
    if esperado == "DECRETO":
        return recebido in {"DECRETO", "DECRETO NUMERADO"}
    if esperado == "LEI":
        return recebido in {"LEI", "LEI ORDINARIA"}
    if esperado == "LEI COMPLEMENTAR":
        return recebido == "LEI COMPLEMENTAR"
    if esperado.startswith("INSTRUCAO NORMATIVA"):
        return recebido.startswith("INSTRUCAO NORMATIVA")
    return esperado == recebido


def _data_diario(resultado: dict) -> date | None:
    diarios = resultado.get("diarios")
    if not isinstance(diarios, list):
        return None
    for diario in diarios:
        if not isinstance(diario, dict) or not isinstance(diario.get("data_diario"), str):
            continue
        try:
            return datetime.strptime(diario["data_diario"], "%d/%m/%Y").date()
        except ValueError:
            continue
    return None


def _data_ato_casacivil(detalhe: dict) -> date | None:
    valor = detalhe.get("data_legislacao")
    if not isinstance(valor, str):
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def _publicacao_no_doc(texto: str, ano_ato: int) -> date | None:
    """Lê data do DOE apenas quando o ano abreviado confere com o ato."""

    match = re.search(r"PUBLICAD[AO]\s+NO\s+DOE\s+DE\s+(\d{1,2})[./](\d{1,2})[./](\d{2,4})", texto, re.IGNORECASE)
    if not match:
        return None
    ano_texto = match.group(3)
    if len(ano_texto) == 2:
        if int(ano_texto) != ano_ato % 100:
            return None
        ano = ano_ato
    else:
        ano = int(ano_texto)
    try:
        return date(ano, int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def buscar_texto_oficial(ato: AtoDescoberto, cliente: ClienteOficial) -> ConteudoOficial | None:
    """Confere número, ano e tipo antes de aceitar o texto da Casa Civil."""

    dados = cliente.json(URL_BUSCA, params={"numero": ato.numero, "ano": ato.ano, "qtd_por_pagina": 20})
    resultados = dados.get("resultados")
    if not isinstance(resultados, list):
        raise ErroColeta("Busca da Casa Civil retornou formato inesperado.")
    for resultado in resultados:
        if not isinstance(resultado, dict):
            continue
        tipo = resultado.get("tipo_legislacao") or {}
        if not isinstance(tipo, dict):
            continue
        if (normalizar_numero_ato(str(resultado.get("numero", "")), ato.ano) != ato.numero
                or resultado.get("ano") != ato.ano
                or not _tipo_confere(ato.tipo_ato, str(tipo.get("nome", "")))):
            continue
        identificador = resultado.get("id")
        if not isinstance(identificador, int):
            continue
        url_detalhe = f"{URL_BUSCA}/{identificador}"
        detalhe = cliente.json(url_detalhe)
        tipo_detalhe = detalhe.get("tipo_legislacao") or {}
        if (detalhe.get("id") != identificador
                or detalhe.get("ano") != ato.ano
                or normalizar_numero_ato(str(detalhe.get("numero", "")), ato.ano) != ato.numero
                or not isinstance(tipo_detalhe, dict)
                or not _tipo_confere(ato.tipo_ato, str(tipo_detalhe.get("nome", "")))):
            raise ErroColeta("Identidade do ato diverge entre busca e texto oficial.")
        original = detalhe.get("conteudo")
        if not isinstance(original, str) or not original.strip():
            raise ErroColeta("Texto integral ausente na Casa Civil.")
        limpo = limpar_html(original)
        if not limpo:
            raise ErroColeta("Texto integral vazio após limpeza.")
        return ConteudoOficial(
            url_detalhe, original, limpo,
            data_publicacao=_data_diario(resultado),
            data_ato=_data_ato_casacivil(detalhe),
            texto_consolidado=_indicacao_consolidado(limpo),
        )
    return None


def ler_arquivo_economia(ato: AtoDescoberto, cliente: ClienteOficial) -> ConteudoOficial:
    """Extrai HTML ou .doc oficial quando a Casa Civil não possui o ato."""

    if not ato.url_arquivo_economia:
        raise ErroColeta("Ato sem link para texto integral oficial.")
    resposta = cliente.obter(ato.url_arquivo_economia)
    tipo = resposta.headers.get("content-type", "").lower()
    if ato.url_arquivo_economia.lower().split("?", 1)[0].endswith(".doc"):
        if not resposta.content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ErroColeta("Arquivo .doc oficial inválido ou inesperado.")
        original = extrair_doc(resposta.content)
        limpo = limpar_texto(original)
        if not limpo:
            raise ErroColeta("Texto integral vazio após conversão do arquivo .doc.")
        cabecalho = next((linha for linha in limpo.splitlines()[:8]
                         if identificar_ato(linha, "", ato.url_descoberta, ato.url_arquivo_economia)), None)
        identificado = identificar_ato(cabecalho, "", ato.url_descoberta, ato.url_arquivo_economia) if cabecalho else None
        if identificado and (identificado.tipo_ato, identificado.numero, identificado.ano) != (ato.tipo_ato, ato.numero, ato.ano):
            raise ErroColeta("Identidade do arquivo oficial diverge da página de descoberta.")
        data_documento = identificado.data_descoberta if identificado else None
        return ConteudoOficial(
            ato.url_arquivo_economia, original, limpo,
            data_publicacao=_publicacao_no_doc(original, ato.ano),
            data_ato=data_documento,
            texto_consolidado=_indicacao_consolidado(limpo),
        )
    if "html" not in tipo:
        raise ErroColeta("Formato do texto integral oficial não suportado.")
    original = resposta.text
    if not original.strip():
        raise ErroColeta("Página oficial vazia.")
    limpo = limpar_html(original)
    if not limpo:
        raise ErroColeta("Texto integral vazio após limpeza.")
    return ConteudoOficial(ato.url_arquivo_economia, original, limpo,
                          texto_consolidado=_indicacao_consolidado(limpo))
