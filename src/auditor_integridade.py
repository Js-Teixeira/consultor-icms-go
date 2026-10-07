"""Auditoria de integridade fiscal somente leitura, sem corrigir registros."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any
from zoneinfo import ZoneInfo

from .busca import _data, situacao_vigencia, texto
from .modelos import BaseTributaria, ESCOPOS_OPERACAO, PREFIXOS_NCM_VALIDOS
from .rastreabilidade import ids_informados, problemas_vinculo

CHAVES = {"ncm": "ncm", "aliquotas": "id_regra", "beneficios": "id_beneficio",
          "legislacao": "id_legislacao"}
PREFIXOS_ESTRUTURADOS = PREFIXOS_NCM_VALIDOS
ADMINISTRATIVO_NAO_VERIFICADO = "__administrativo_nao_verificado__"
MENSAGEM_ADMINISTRATIVO_NAO_VERIFICADO = (
    "A credencial utilizada não possui acesso às estruturas administrativas de "
    "rastreabilidade. A auditoria fiscal principal foi concluída."
)
LACUNA_FINAL = (
    "LACUNA DE RASTREABILIDADE: vínculos opcionais da regra fiscal final só são verificáveis "
    "quando IDs curados foram informados e as tabelas do updater estão disponíveis."
)
LACUNA_NCM_AUTOMATICO = (
    "LACUNA DE RASTREABILIDADE: regras manuais antigas podem ter ambos os vínculos vazios; "
    "não se atribui evidência ou extração por igualdade de NCM."
)


@dataclass(frozen=True)
class Ocorrencia:
    codigo: str
    nivel: str
    tabela: str
    id_registro: str
    ncm: str | None
    mensagem: str
    detalhes: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Relatorio:
    totais_tabelas: dict[str, int]
    ocorrencias: list[Ocorrencia] = field(default_factory=list)
    lacunas: list[str] = field(default_factory=lambda: [LACUNA_FINAL, LACUNA_NCM_AUTOMATICO])

    def adicionar(self, codigo: str, nivel: str, tabela: str, registro: dict[str, Any],
                  mensagem: str, **detalhes: Any) -> None:
        chave = CHAVES.get(tabela, "id")
        ncm = registro.get("ncm") if tabela == "ncm" else registro.get("chave_ncm", registro.get("ncm_chave"))
        self.ocorrencias.append(Ocorrencia(
            codigo, nivel, tabela, texto(registro.get(chave)) or texto(registro.get("id")),
            texto(ncm) or None, mensagem, detalhes,
        ))

    def contagem_niveis(self) -> dict[str, int]:
        contagem = Counter(o.nivel for o in self.ocorrencias)
        return {nivel: contagem[nivel] for nivel in ("ERRO", "ALERTA", "INFO")}

    def contagem_codigos(self) -> dict[str, int]:
        return dict(sorted(Counter(o.codigo for o in self.ocorrencias).items()))

    def para_dict(self) -> dict[str, Any]:
        return {"tabelas": self.totais_tabelas, "niveis": self.contagem_niveis(),
                "por_codigo": self.contagem_codigos(),
                "ocorrencias": [o.para_dict() for o in self.ocorrencias],
                "lacunas": self.lacunas}


def _ativo(registro: dict[str, Any]) -> bool:
    return texto(registro.get("ativo")).upper() == "SIM"


def _valor(valor: Any) -> str:
    bruto = texto(valor).replace(",", ".")
    if not bruto:
        return ""
    try:
        return str(Decimal(bruto).normalize())
    except InvalidOperation:
        return bruto


def _intervalo(registro: dict[str, Any]) -> tuple[date, date] | None:
    try:
        inicio = _data(registro.get("vigencia_inicio")) or date.min
        fim = _data(registro.get("vigencia_fim")) or date.max
    except ValueError:
        return None
    return (inicio, fim) if inicio <= fim else None


def _sobrepostos(a: dict[str, Any], b: dict[str, Any]) -> bool:
    primeiro, segundo = _intervalo(a), _intervalo(b)
    return bool(primeiro and segundo and max(primeiro[0], segundo[0]) <= min(primeiro[1], segundo[1]))


def _duplicidades_pk(relatorio: Relatorio, tabelas: dict[str, list[dict[str, Any]]]) -> None:
    for nome, linhas in tabelas.items():
        chave = CHAVES[nome]
        grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for linha in linhas:
            grupos[texto(linha.get(chave))].append(linha)
        for identificador, duplicadas in grupos.items():
            if len(duplicadas) > 1:
                relatorio.adicionar("PK_DUPLICADA", "ERRO", nome, duplicadas[0],
                                   f"Chave primária {identificador or '(vazia)'} repetida na fonte.",
                                   quantidade=len(duplicadas))


def _validar_ncm(relatorio: Relatorio, tabela: str, linha: dict[str, Any],
                 catalogo: set[str], catalogo_oficial: set[str] | None) -> None:
    chave = texto(linha.get("ncm" if tabela == "ncm" else "chave_ncm"))
    tipo = "EXATO" if tabela == "ncm" else texto(linha.get("tipo_correspondencia")).upper()
    if tabela == "beneficios" and not chave:
        if _ativo(linha):
            relatorio.adicionar("BENEFICIO_SEM_NCM", "ERRO", tabela, linha,
                               "Benefício ativo sem chave NCM não pode participar da consulta.")
        return
    if not re.fullmatch(r"[0-9]+", chave or ""):
        relatorio.adicionar("NCM_INVALIDO", "ERRO", tabela, linha, "Código NCM ausente ou não numérico.")
        return
    if tipo == "EXATO" and len(chave) < 8:
        relatorio.adicionar("NCM_INCOMPLETO", "ERRO", tabela, linha,
                           "Correspondência EXATO requer oito dígitos.", comprimento=len(chave))
        return
    if tipo == "PREFIXO" and len(chave) in PREFIXOS_ESTRUTURADOS:
        pass
    elif tipo != "EXATO" or len(chave) != 8:
        relatorio.adicionar("NCM_INVALIDO", "ERRO", tabela, linha,
                           "Tipo de correspondência ou comprimento NCM inválido.",
                           tipo_correspondencia=tipo, comprimento=len(chave))
        return
    if tabela == "ncm":
        if catalogo_oficial is not None and chave not in catalogo_oficial:
            relatorio.adicionar("NCM_INEXISTENTE", "ALERTA", tabela, linha,
                               "Código não consta no último cache oficial validado; conferir fonte atual.",
                               catalogo="último cache oficial validado")
        return
    referencia = catalogo_oficial if catalogo_oficial is not None else catalogo
    existe = chave in referencia if tipo == "EXATO" else any(n.startswith(chave) for n in referencia)
    if not existe:
        fonte = "último cache oficial validado" if catalogo_oficial is not None else "cadastro NCM local"
        relatorio.adicionar("NCM_INEXISTENTE", "ALERTA", tabela, linha,
                           f"Código/prefixo não encontrado no {fonte}; confirmar na fonte oficial.",
                           catalogo=fonte)


def _vigencia(relatorio: Relatorio, tabela: str, linha: dict[str, Any], referencia: date) -> None:
    estado = situacao_vigencia(linha, referencia)
    if estado == "INCONSISTENTE":
        relatorio.adicionar("VIGENCIA_INCONSISTENTE", "ERRO", tabela, linha,
                           "Datas de vigência inválidas ou início posterior ao fim.")
    elif not texto(linha.get("vigencia_inicio")) and not texto(linha.get("vigencia_fim")):
        relatorio.adicionar("VIGENCIA_NAO_ESTRUTURADA", "ALERTA", tabela, linha,
                           "Nenhum limite de vigência foi cadastrado; revisar sem presumir revogação.")
    elif _ativo(linha) and texto(linha.get("vigencia_fim")):
        intervalo = _intervalo(linha)
        if intervalo and intervalo[1] < referencia:
            relatorio.adicionar("REGRA_ATIVA_COM_VIGENCIA_ENCERRADA", "ALERTA", tabela, linha,
                               "Registro ativo com vigência cadastrada encerrada; verificar status, sem presumir revogação.",
                               vigencia_fim=str(intervalo[1]))


def _fundamento(relatorio: Relatorio, tabela: str, linha: dict[str, Any],
                legislacoes: dict[str, dict[str, Any]]) -> None:
    identificador = texto(linha.get("id_legislacao"))
    if not identificador:
        codigo = "BENEFICIO_SEM_LEGISLACAO" if tabela == "beneficios" else "LEGISLACAO_INEXISTENTE"
        relatorio.adicionar(codigo, "ERRO", tabela, linha, "Regra sem id_legislacao cadastrado.")
    elif identificador not in legislacoes:
        relatorio.adicionar("LEGISLACAO_INEXISTENTE", "ERRO", tabela, linha,
                           "Fundamento legal referenciado não existe na base.", id_legislacao=identificador)
    elif not _ativo(legislacoes[identificador]):
        relatorio.adicionar("LEGISLACAO_INATIVA", "ERRO", tabela, linha,
                           "Fundamento cadastrado está inativo e não pode sustentar a regra ativa.",
                           id_legislacao=identificador)


def _duplicidades_e_conflitos(relatorio: Relatorio, tabela: str,
                              linhas: list[dict[str, Any]], referencia: date) -> None:
    ativas = [linha for linha in linhas if _ativo(linha)]
    grupos: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for linha in ativas:
        base = (texto(linha.get("chave_ncm")), texto(linha.get("tipo_correspondencia")).upper())
        if tabela == "aliquotas":
            assinatura = base + (texto(linha.get("vigencia_inicio")), texto(linha.get("vigencia_fim")),
                                 _valor(linha.get("aliquota_icms")), texto(linha.get("id_legislacao")),
                                 texto(linha.get("descricao_regra")), texto(linha.get("palavras_chave")),
                                 texto(linha.get("exige_descricao")))
        else:
            assinatura = base + (texto(linha.get("tipo_beneficio")), texto(linha.get("grupo_beneficio")),
                                 texto(linha.get("escopo_operacao")), texto(linha.get("vigencia_inicio")),
                                 texto(linha.get("vigencia_fim")), texto(linha.get("id_legislacao")),
                                 _valor(linha.get("carga_efetiva")), _valor(linha.get("percentual_reducao_bc")),
                                 _valor(linha.get("credito_outorgado_percentual")),
                                 texto(linha.get("aplicacao")), texto(linha.get("condicoes")),
                                 texto(linha.get("descricao_regra")), texto(linha.get("exige_descricao")))
        grupos[assinatura].append(linha)
    for grupo in grupos.values():
        if len(grupo) > 1:
            relatorio.adicionar("DUPLICIDADE_FUNCIONAL", "ALERTA", tabela, grupo[0],
                               "Registros ativos com a mesma chave material e valores cadastrados.",
                               ids=[texto(r.get(CHAVES[tabela])) for r in grupo])

    por_chave: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for linha in ativas:
        por_chave[(texto(linha.get("chave_ncm")),
                   texto(linha.get("tipo_correspondencia")).upper())].append(linha)
    for a, b in (par for grupo in por_chave.values() for par in combinations(grupo, 2)):
        if not _sobrepostos(a, b):
            continue
        if tabela == "aliquotas":
            if (situacao_vigencia(a, referencia) == situacao_vigencia(b, referencia) == "VIGENTE"
                    and _valor(a.get("aliquota_icms")) and _valor(b.get("aliquota_icms"))
                    and _valor(a.get("aliquota_icms")) != _valor(b.get("aliquota_icms"))):
                relatorio.adicionar("CONFLITO_ALIQUOTA", "ERRO", tabela, a,
                                   "Regras ativas simultâneas da mesma chave/especificidade têm alíquotas diferentes.",
                                   outro_id=texto(b.get("id_regra")), valores=[_valor(a.get("aliquota_icms")),
                                                                              _valor(b.get("aliquota_icms"))])
        elif all(texto(a.get(c)) == texto(b.get(c)) for c in
                 ("tipo_beneficio", "grupo_beneficio", "escopo_operacao", "id_legislacao")):
            divergentes = [campo for campo in ("carga_efetiva", "percentual_reducao_bc", "credito_outorgado_percentual")
                           if _valor(a.get(campo)) and _valor(b.get(campo)) and
                           _valor(a.get(campo)) != _valor(b.get(campo))]
            if divergentes:
                relatorio.adicionar("CONFLITO_BENEFICIO", "ALERTA", tabela, a,
                                   "Regras aparentemente equivalentes têm valores incompatíveis; revisão humana necessária.",
                                   outro_id=texto(b.get("id_beneficio")), campos=divergentes)


def _auditar_updater(relatorio: Relatorio, updater: dict[str, list[dict[str, Any]]] | None) -> None:
    if not updater or ADMINISTRATIVO_NAO_VERIFICADO in updater:
        return
    extraidas = {texto(r.get("id")): r for r in updater.get("regras_extraidas", [])}
    evidencias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evidencia in updater.get("evidencias_extracao", []):
        evidencias[texto(evidencia.get("regra_extraida_id"))].append(evidencia)
    for consolidada in updater.get("regras_consolidadas", []):
        origem_id = texto(consolidada.get("regra_origem_id"))
        origem = extraidas.get(origem_id)
        if origem is not None and texto(origem.get("confianca")).upper() == "BAIXA":
            relatorio.adicionar("REGRA_ORIGEM_BAIXA_CONFIANCA", "ALERTA", "regras_consolidadas", consolidada,
                               "Consolidação ligada por ID a extração de confiança BAIXA; não implica publicação fiscal.",
                               regra_extraida_id=origem_id)
    for extraida in extraidas.values():
        ncm = texto(extraida.get("ncm_chave"))
        if not ncm:
            continue
        for evidencia in evidencias.get(texto(extraida.get("id")), []):
            if (texto(evidencia.get("tipo_evidencia")).upper() == "NCM"
                    and texto(evidencia.get("metodo")).startswith(("varredura_integral", "regex_contextual"))
                    and texto(evidencia.get("valor_extraido")).replace(".", "") == ncm
                    and not texto(evidencia.get("texto_origem"))):
                relatorio.adicionar("NCM_AUTOMATICO_SEM_EVIDENCIA", "ERRO", "regras_extraidas", extraida,
                                   "Extração automática de NCM ligada por ID não preservou trecho de evidência.",
                                   evidencia_id=texto(evidencia.get("id")))


def _auditar_vinculos(relatorio: Relatorio, tabelas: dict[str, list[dict[str, Any]]],
                     updater: dict[str, list[dict[str, Any]]] | None) -> None:
    if updater is not None and ADMINISTRATIVO_NAO_VERIFICADO in updater:
        return  # O relatório já contém um único INFO; não gerar falsos alertas por regra.
    disponivel = updater is not None and all(nome in updater for nome in (
        "regras_consolidadas", "regras_extraidas", "evidencias_extracao"))
    if disponivel:
        assert updater is not None
        consolidadas = {texto(r.get("id")): r for r in updater["regras_consolidadas"]}
        extraidas = {texto(r.get("id")): r for r in updater["regras_extraidas"]}
        evidencias = {texto(r.get("id")): r for r in updater["evidencias_extracao"]}
    for nome in ("aliquotas", "beneficios"):
        for linha in tabelas[nome]:
            if not ids_informados(linha):
                continue  # NULL é válido para regras manuais antigas.
            if not disponivel:
                relatorio.adicionar("RASTREABILIDADE_NAO_VERIFICAVEL", "ALERTA", nome, linha,
                                   "Tabelas do updater indisponíveis para verificar IDs informados.")
                continue
            for codigo, mensagem in problemas_vinculo(linha, consolidadas, extraidas, evidencias):
                relatorio.adicionar(codigo, "ERRO", nome, linha, mensagem)
            consolidada = consolidadas.get(texto(linha.get("regra_consolidada_id")))
            if consolidada:
                origem = extraidas.get(texto(consolidada.get("regra_origem_id")))
                if origem and texto(origem.get("confianca")).upper() == "BAIXA":
                    relatorio.adicionar("REGRA_ORIGEM_BAIXA_CONFIANCA", "ALERTA", nome, linha,
                                       "Regra fiscal ligada por ID a extração de confiança BAIXA.",
                                       regra_extraida_id=texto(origem.get("id")))


def auditar_integridade(base: BaseTributaria, *, referencia: date | None = None,
                       catalogo_oficial: set[str] | None = None,
                       updater: dict[str, list[dict[str, Any]]] | None = None) -> Relatorio:
    """Analisa dados em memória; não executa SQL nem altera objetos de entrada."""

    referencia = referencia or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    tabelas = {"ncm": base.ncm.to_dict("records"), "aliquotas": base.aliquotas.to_dict("records"),
               "beneficios": base.beneficios.to_dict("records"),
               "legislacao": base.legislacao.to_dict("records")}
    relatorio = Relatorio({nome: len(linhas) for nome, linhas in tabelas.items()})
    _duplicidades_pk(relatorio, tabelas)
    catalogo = {texto(r.get("ncm")) for r in tabelas["ncm"] if _ativo(r) and
                re.fullmatch(r"[0-9]{8}", texto(r.get("ncm")))}
    legislacoes = {texto(r.get("id_legislacao")): r for r in tabelas["legislacao"]}

    for linha in tabelas["ncm"]:
        _validar_ncm(relatorio, "ncm", linha, catalogo, catalogo_oficial)
    for linha in tabelas["legislacao"]:
        if not texto(linha.get("url_fonte")):
            relatorio.adicionar("LEGISLACAO_SEM_FONTE", "ALERTA", "legislacao", linha,
                               "Fundamento sem URL de fonte cadastrada.")
        if not texto(linha.get("texto_relevante")):
            relatorio.adicionar("LEGISLACAO_SEM_TEXTO_RELEVANTE", "ALERTA", "legislacao", linha,
                               "Fundamento sem trecho relevante cadastrado.")
        _vigencia(relatorio, "legislacao", linha, referencia)

    for nome in ("aliquotas", "beneficios"):
        for linha in tabelas[nome]:
            _validar_ncm(relatorio, nome, linha, catalogo, catalogo_oficial)
            _vigencia(relatorio, nome, linha, referencia)
            if not _ativo(linha):
                continue
            _fundamento(relatorio, nome, linha, legislacoes)
            if nome == "aliquotas":
                if not texto(linha.get("aliquota_icms")):
                    relatorio.adicionar("ALIQUOTA_AUSENTE", "ERRO", nome, linha,
                                       "Regra ativa de alíquota sem percentual cadastrado.")
            else:
                escopo = texto(linha.get("escopo_operacao")).upper() or "NAO_DEFINIDA"
                if escopo == "NAO_DEFINIDA":
                    relatorio.adicionar("OPERACAO_NAO_ESTRUTURADA", "ALERTA", nome, linha,
                                       "Escopo da operação não estruturado; revisar sem inferir pelo texto.")
                elif escopo not in ESCOPOS_OPERACAO:
                    relatorio.adicionar("OPERACAO_INVALIDA", "ERRO", nome, linha,
                                       "Escopo da operação fora dos valores permitidos.", valor=escopo)
                if not texto(linha.get("cbenef")):
                    relatorio.adicionar("CBENEF_NAO_CADASTRADO", "INFO", nome, linha,
                                       "cBenef opcional ainda não cadastrado na base.")
                if (texto(linha.get("tipo_beneficio")).upper() == "REDUCAO_BASE_CALCULO"
                        and not texto(linha.get("percentual_reducao_bc"))
                        and not texto(linha.get("carga_efetiva"))):
                    relatorio.adicionar("REDUCAO_SEM_VALOR", "ERRO", nome, linha,
                                       "Redução sem percentual nem carga efetiva cadastrados.")
                if texto(linha.get("exige_descricao")).upper() == "SIM" and not texto(linha.get("condicoes")):
                    relatorio.adicionar("CONDICOES_AUSENTES", "ALERTA", nome, linha,
                                       "Benefício exige identificação por descrição, mas não há condições textuais cadastradas.")
            if (texto(linha.get("exige_descricao")).upper() == "SIM"
                    and not texto(linha.get("descricao_regra"))
                    and not texto(linha.get("palavras_chave"))):
                relatorio.adicionar("REGRA_EXIGE_DESCRICAO_SEM_REFERENCIA", "ERRO", nome, linha,
                                   "Regra exige descrição sem texto ou palavras-chave de referência.")
        _duplicidades_e_conflitos(relatorio, nome, tabelas[nome], referencia)
    _auditar_updater(relatorio, updater)
    _auditar_vinculos(relatorio, tabelas, updater)
    if updater is not None and ADMINISTRATIVO_NAO_VERIFICADO in updater:
        relatorio.adicionar(
            "RASTREABILIDADE_ADMINISTRATIVA_NAO_VERIFICADA", "INFO", "updater", {},
            MENSAGEM_ADMINISTRATIVO_NAO_VERIFICADO,
            estruturas=updater[ADMINISTRATIVO_NAO_VERIFICADO],
        )
    return relatorio
