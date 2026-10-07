"""Extração fiscal determinística, conservadora e rastreável de textos já coletados."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from bs4 import BeautifulSoup

from .normalizacao import sem_acentos

EXTRACTOR_VERSION = "2.5.0"
MAX_TRECHO = 3000
MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
NUMERO_NCM = r"(?<!\d)(?:\d{4}\.\d{2}\.\d{2}|\d{4}\.\d{2}|\d{8}|\d{6}|\d{4})(?!\d)"
NCM_COM_ROTULO = re.compile(
    rf"\b(?:NCM(?:\s*[/\-]\s*SH)?|posi[cç][aã]o|subposi[cç][aã]o|classifica[cç][aã]o fiscal)\s*[:\-]?\s*({NUMERO_NCM})",
    re.IGNORECASE,
)
NCM_EXATO_SEM_ROTULO = re.compile(r"(?<![\d.])(?:\d{4}\.\d{2}\.\d{2}|\d{8})(?![\d.])")
CONTEXTO_NCM_SEM_ROTULO = re.compile(
    r"\b(?:ncm|classific\w*|posic\w*|subposic\w*)\b"
)
NCM_PROCEDIMENTAL = re.compile(
    r"\b(?:manifestacao\s+do\s+fisco|document\w*\s+fisc\w*|obrigac\w*\s+acessoria|"
    r"requerimento|solicitacao|cadastro|procedimento\s+administrativo)\b"
)
MOTIVO_NCM_PROCEDIMENTAL = (
    "NCM identificado em dispositivo procedimental, sem tratamento tributário material suficiente para consulta."
)
PERCENTUAL = re.compile(r"(?<!\d)(\d{1,3}(?:[,.]\d{1,4})?)\s*%")
PADROES_PERCENTUAIS = (
    ("percentual_reducao_bc", re.compile(r"redu[cç][aã]o\s+(?:de\s+)?" + PERCENTUAL.pattern + r"\s+da\s+base|base\s+de\s+c[aá]lculo.{0,45}?reduzid[ao]\s+(?:em\s+)?" + PERCENTUAL.pattern, re.I)),
    ("carga_efetiva", re.compile(r"carga\s+(?:tribut[aá]ria|efetiva).{0,55}?" + PERCENTUAL.pattern, re.I)),
    ("credito_outorgado_percentual", re.compile(r"cr[eé]dito\s+outorgado\s+(?:de\s+|equivalente\s+a\s+)?" + PERCENTUAL.pattern, re.I)),
    ("aliquota_icms", re.compile(r"al[ií]quota(?:\s+(?:do\s+)?ICMS)?\s+(?:(?:[eé]\s+)?de\s+|em\s+|correspondente\s+a\s+)?" + PERCENTUAL.pattern, re.I)),
)
DISPOSITIVOS = {
    "anexo": re.compile(r"\bAnexo\s+([IVXLCDM]+|\d+[A-Z]?)\b", re.I),
    "artigo": re.compile(r"\b(?:Art\.?|Artigo)\s*(\d+[º°]?(?:-[A-Z])?)", re.I),
    "paragrafo": re.compile(r"(?:§|par[aá]grafo)\s*(\d+[º°]?|[uú]nico)", re.I),
    "inciso": re.compile(r"\binciso\s+([IVXLCDM]+)\b", re.I),
    "alinea": re.compile(r"\bal[ií]nea\s+[\"'“]?([a-z])\b", re.I),
    "item": re.compile(r"\b(?:subitem|item)\s+(\d+(?:\.\d+)*)\b", re.I),
}
CONDICAO = re.compile(r"\b(?:desde que|quando|exclusivamente|somente|condicionad[oa]\s+a|vedad[ao]\s+a|n[aã]o se aplica|aplica-se somente|destinad[oa]\s+a|para utiliza[cç][aã]o em|estabelecimento|contribuinte|atividade econ[oô]mica|op[cç][aã]o|ren[uú]ncia|veda[cç][aã]o|cumula[cç][aã]o)\b", re.I)
EXCECAO = re.compile(r"\b(?:exceto|salvo|n[aã]o se aplica|vedad[oa]|excluem-se|n[aã]o alcan[cç]a)\b", re.I)
ACAO_EVIDENCIA = {
    "INCLUI": re.compile(r"\b(?:ficam? acrescid[oa]s?|introduz[- ]se)\b", re.I),
    "ALTERA": re.compile(r"\b(?:passa[m]? a vigorar|ficam? alterad[oa]s?)\b", re.I),
    "REVOGA": re.compile(r"\b(?:ficam? revogad[oa]s?|revoga-se)\b", re.I),
    "PRORROGA": re.compile(r"\b(?:prorroga[- ]se|ficam? prorrogad[oa]s?)\b", re.I),
    "SUBSTITUI": re.compile(r"\bsubstitu[ií]d[oa]s?\b", re.I),
    "RENOVA": re.compile(r"\brenovad[oa]s?\b", re.I),
}
TIPO_EVIDENCIA = {
    "ALIQUOTA": re.compile(r"\bal[ií]quota\b", re.I),
    "ISENCAO": re.compile(r"\b(?:isent[oa]s?|isen[cç][aã]o)\b", re.I),
    "REDUCAO_BASE_CALCULO": re.compile(r"\b(?:redu[cç][aã]o|reduzid[ao]s?)\b", re.I),
    "CREDITO_OUTORGADO": re.compile(r"\bcr[eé]dito\s+outorgado\b", re.I),
    "DIFERIMENTO": re.compile(r"\b(?:diferimento|diferid[oa]s?)\b", re.I),
    "SUSPENSAO": re.compile(r"\b(?:suspens[aã]o|suspens[ao]s?)\b", re.I),
    "OUTRO_BENEFICIO": re.compile(r"\bbenef[ií]cio\s+fiscal\b", re.I),
    "REVOGACAO": re.compile(r"\brevogad[oa]s?\b|\brevoga-se\b", re.I),
}
DATA_EXTENSO = r"(\d{1,2})\s+de\s+([a-zçãéíô]+)\s+de\s+(\d{4})"
VIGENCIA_INICIO = re.compile(r"(?:produz\s+efeitos\s+a\s+partir\s+de|entra\s+em\s+vigor\s+em|com\s+efeitos\s+desde)\s+" + DATA_EXTENSO, re.I)
VIGENCIA_FIM = re.compile(r"\bat[eé]\s+" + DATA_EXTENSO, re.I)
NORMA_ALTERADA = re.compile(r"\bDecreto\s+n[º°o.]?\s*[\d.]+/\d{4}\b|\bRCTE\b|\bAnexo\s+[IVXLCDM]+\b", re.I)
PAUTA_PRECO = re.compile(r"\b(?:prec[oa]s?\s+(?:de\s+)?pauta|pauta\s+de\s+mercadorias|valores?\s+de\s+referencia|precos?\s+publicados|preco\s+medio\s+ponderado)\b")
CREDITO_TRIBUTARIO = re.compile(r"\b(?:exigibilidade|credito\s+tributario|divida\s+ativa|parcelamento|cobranca|execucao\s+fiscal|tare\s+suspens[oa])\b")
PROCEDIMENTO = re.compile(r"\b(?:processo\s+administrativo|procedimento\s+administrativo|obrigac(?:ao|oes)\s+acessorias?)\b")
ADMINISTRATIVO = re.compile(r"\b(?:estrutura\s+administrativa|nomeac(?:ao|oes)|competencia\s+administrativa)\b")
SUSPENSAO_TRIBUTARIA = re.compile(
    r"\b(?:suspensao|suspens[oa]s?|suspenso)\b.{0,100}\b(?:incidencia|pagamento|recolhimento)\s+do\s+icms\b"
    r"|\b(?:incidencia|pagamento|recolhimento)\s+do\s+icms\b.{0,100}\b(?:suspensao|suspens[oa]s?|suspenso)\b"
)
CONTEXTO_OPERACAO = re.compile(r"\b(?:operac(?:ao|oes)|mercadoria|produto|prestac(?:ao|oes)|saida|entrada|importac(?:ao|oes)|situac(?:ao|oes)\s+tributaria)\b")
CONCESSAO_BENEFICIO = re.compile(
    r"\b(?:autorizad[oa]\s+a\s+conceder|concede(?:-se)?|concedid[oa]s?|instituid[oa]s?|"
    r"assegurad[oa]s?|outorgad[oa]s?)\b.{0,100}\b(?:credito\s+outorgado|beneficio\s+fiscal|isencao)\b"
)
PAPEIS_COMPLEMENTARES = {
    "CONSEQUENCIA": re.compile(r"\b(?:estorn(?:ar|o|ad[oa])|devolver|restituir|perda\s+do\s+beneficio|cancelamento\s+do\s+beneficio)\b"),
    "VEDACAO": re.compile(r"\b(?:vedad[oa]s?|proibid[oa]s?|nao\s+podera|impedid[oa]s?)\b"),
    "EXCECAO": re.compile(r"\b(?:exceto|salvo|nao\s+se\s+aplica|dispensad[oa]s?)\b"),
    "UTILIZACAO": re.compile(r"\b(?:utilizad[oa]s?|utilizacao|aproveitament[oa]|apropriad[oa]s?|compensad[oa]s?)\b"),
    "BENEFICIARIO": re.compile(r"\b(?:para\s+ser\s+beneficiario|beneficiarios?|destinad[oa]s?\s+a\s+(?:contribuintes?|estabelecimentos?))\b"),
    "CONDICAO": re.compile(r"\b(?:condicionad[oa]s?|desde\s+que|deve(?:ra)?\s+celebrar|termo\s+de\s+acordo|regime\s+especial|requisit[oa]s?)\b"),
    "CALCULO": re.compile(r"\b(?:calculo|apuracao|base\s+de\s+calculo|montante|valor\s+do\s+credito|percentual\s+do\s+credito)\b"),
    "ABRANGENCIA": re.compile(r"\b(?:abrangencia|abrange|alcan[cç]a|aplica-se\s+(?:a|as|aos))\b"),
    "PROCEDIMENTO": re.compile(r"\b(?:requerimento|solicitacao|pedido\s+de\s+habilitacao|cadastro|procedimento)\b"),
    "REFERENCIA": re.compile(r"\b(?:nos\s+termos\s+de|conforme\s+o|observado\s+o\s+disposto)\b"),
}
PRODUTO_DESCRITO = re.compile(
    r"\b(?:mercadorias?|produtos?)\s*:?[ \t]+"
    r"(?:(?:denominad[oa]s?|identificad[oa]s?|descrit[oa]s?)\s+(?:como\s+)?)?"
    r"(?P<descricao>[\wÀ-ÿ][\wÀ-ÿ -]{2,80})",
    re.I,
)
DESCRITOR_GENERICO = {
    "de", "do", "da", "dos", "das", "em", "para", "que", "industrial", "industrializado",
    "industrializados", "fabricado", "fabricados", "fabricada", "fabricadas", "nacional",
    "nacionais", "destinado", "destinados", "destinada", "destinadas", "referido",
    "referidos", "referida", "referidas", "previsto", "previstos", "listado",
    "listados", "constante", "constantes", "abrangido", "abrangidos", "qualquer",
    "todos", "todas", "demais", "beneficiado", "beneficiados", "no", "na", "nos", "nas",
    "descrito", "descritos", "descrita", "descritas", "identificado", "identificados",
    "identificada", "identificadas", "produzido", "produzidos", "produzida", "produzidas",
    "objeto", "alcancada", "alcancadas", "alcancado", "alcancados", "nao",
    "produto", "produtos", "mercadoria", "mercadorias",
}
MOTIVO_SEM_VINCULO = "Benefício fiscal sem vínculo suficiente com NCM ou mercadoria consultável."
MOTIVO_PENDENTE = "Mercadoria identificada no texto; associação a NCM oficial ainda não confirmada."


@dataclass(frozen=True)
class EvidenciaFiscal:
    tipo_evidencia: str
    valor_extraido: str
    texto_origem: str
    posicao_inicio: int
    posicao_fim: int
    confianca: str = "ALTA"
    metodo: str = "regex_contextual_v2"


@dataclass
class RegraExtraida:
    tipo_regra: str
    acao_legislativa: str
    trecho_origem: str
    inicio_trecho: int
    fim_trecho: int
    ncm_chave: str | None = None
    ncm_original: str | None = None
    tipo_correspondencia: str | None = None
    descricao_legal: str | None = None
    descricao_resumida: str | None = None
    aliquota_icms: Decimal | None = None
    percentual_reducao_bc: Decimal | None = None
    carga_efetiva: Decimal | None = None
    credito_outorgado_percentual: Decimal | None = None
    tipo_beneficio: str | None = None
    anexo: str | None = None
    artigo: str | None = None
    paragrafo: str | None = None
    inciso: str | None = None
    alinea: str | None = None
    item: str | None = None
    vigencia_inicio: date | None = None
    vigencia_fim: date | None = None
    condicoes_texto: str | None = None
    norma_alterada: str | None = None
    confianca: str = "BAIXA"
    status_revisao: str = "PENDENTE"
    escopo_fiscal: str = "INDETERMINADO"
    elegivel_consolidacao: str = "NAO"
    motivo_elegibilidade: str = "Classificação de escopo pendente."
    papel_dispositivo: str = "INDETERMINADO"
    grupo_regra_id: str | None = None
    descricao_proxima_ncm: str | None = None
    elegivel_consulta_ncm: str = "NAO"
    status_vinculo_ncm: str = "SEM_VINCULO_NCM"
    motivo_consulta_ncm: str = MOTIVO_SEM_VINCULO
    motivos_confianca: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    evidencias: list[EvidenciaFiscal] = field(default_factory=list)

    @property
    def chave_extracao(self) -> str:
        identificador = f"{self.inicio_trecho}:{self.fim_trecho}:{self.tipo_regra}:{self.ncm_chave or ''}:{self.ncm_original or ''}"
        return hashlib.sha256(identificador.encode("utf-8")).hexdigest()

    @property
    def ncm_normalizado(self) -> str | None:
        """Nome explícito do código normalizado já armazenado em ncm_chave."""

        return self.ncm_chave


@dataclass(frozen=True)
class Bloco:
    texto: str
    inicio: int
    fim: int
    cabecalho: tuple[str, ...] = ()
    celulas: tuple[str, ...] = ()
    fragmentado: bool = False


@dataclass(frozen=True)
class NcmDetectado:
    original: str
    normalizado: str
    tipo_correspondencia: str
    inicio: int
    fim: int
    contexto: str
    inicio_contexto: int
    fim_contexto: int
    descricao_proxima: str | None = None


def _blocos(texto: str, html_original: str | None) -> list[Bloco]:
    """Mantém linhas e linhas de tabelas isoladas com offsets no texto limpo."""

    tabelas: list[Bloco] = []
    ocupados: list[tuple[int, int]] = []
    if html_original and "<table" in html_original.lower():
        for tabela in BeautifulSoup(html_original, "html.parser").find_all("table"):
            linhas = tabela.find_all("tr")
            cabecalho: tuple[str, ...] = ()
            cursor_tabela = 0
            for linha in linhas:
                celulas = tuple(c.get_text(" ", strip=True) for c in linha.find_all(["th", "td"], recursive=False))
                if not celulas:
                    continue
                if linha.find("th"):
                    cabecalho = celulas
                    primeiro = texto.find(celulas[0], cursor_tabela)
                    if primeiro >= 0:
                        cursor = primeiro + len(celulas[0])
                        for celula in celulas[1:]:
                            indice = texto.find(celula, cursor)
                            if indice < 0:
                                break
                            cursor = indice + len(celula)
                        else:
                            ocupados.append((primeiro, cursor))
                            cursor_tabela = cursor
                    continue
                primeiro = texto.find(celulas[0], cursor_tabela)
                if primeiro < 0:
                    continue
                cursor = primeiro + len(celulas[0])
                for celula in celulas[1:]:
                    indice = texto.find(celula, cursor)
                    if indice < 0:
                        break
                    cursor = indice + len(celula)
                else:
                    if not any(primeiro < fim and cursor > inicio for inicio, fim in ocupados):
                        tabelas.append(Bloco(texto[primeiro:cursor], primeiro, cursor, cabecalho, celulas))
                        ocupados.append((primeiro, cursor))
                        cursor_tabela = cursor
    linhas: list[Bloco] = []
    cabecalho: tuple[str, ...] = ()
    for match in re.finditer(r"[^\n]+", texto):
        linha = match.group().strip()
        if not linha or any(match.start() >= inicio and match.end() <= fim for inicio, fim in ocupados):
            continue
        if "|" in linha:
            celulas = tuple(c.strip() for c in linha.split("|"))
            if any("ncm" in sem_acentos(c).lower() for c in celulas) and not re.search(NUMERO_NCM, linha):
                cabecalho = celulas
                continue
            linhas.append(Bloco(match.group(), match.start(), match.end(), cabecalho, celulas))
        else:
            linhas.append(Bloco(match.group(), match.start(), match.end()))
    return sorted(tabelas + linhas, key=lambda bloco: bloco.inicio)


def _evidencia(bloco: Bloco, inicio: int, fim: int, tipo: str, valor: str, metodo: str = "regex_contextual_v2") -> EvidenciaFiscal:
    return EvidenciaFiscal(tipo, valor, bloco.texto[inicio:fim], bloco.inicio + inicio, bloco.inicio + fim, metodo=metodo)


def _fragmentar(bloco: Bloco) -> list[Bloco]:
    """Limita trechos extensos sem descartar silenciosamente conteúdo fiscal."""

    if len(bloco.texto) <= MAX_TRECHO:
        return [bloco]
    partes: list[Bloco] = []
    inicio = 0
    while inicio < len(bloco.texto):
        fim = min(inicio + MAX_TRECHO, len(bloco.texto))
        if fim < len(bloco.texto):
            pontos = [bloco.texto.rfind(separador, inicio + MAX_TRECHO // 2, fim)
                      for separador in ("; ", ". ", " ")]
            corte = max(pontos)
            if corte > inicio:
                fim = corte + 1
        partes.append(Bloco(bloco.texto[inicio:fim], bloco.inicio + inicio,
                            bloco.inicio + fim, bloco.cabecalho, (), True))
        inicio = fim
    return partes


def _ncms(bloco: Bloco) -> list[tuple[str, int, int]]:
    encontrados = [(m.group(1), m.start(1), m.end(1)) for m in NCM_COM_ROTULO.finditer(bloco.texto)]
    if bloco.cabecalho and bloco.celulas:
        for indice, titulo in enumerate(bloco.cabecalho):
            if indice >= len(bloco.celulas):
                continue
            rotulo = sem_acentos(titulo).lower()
            if "ncm" not in rotulo and "posicao" not in rotulo and "classificacao fiscal" not in rotulo:
                continue
            celula = bloco.celulas[indice]
            for m in re.finditer(NUMERO_NCM, celula):
                pos = bloco.texto.find(celula)
                candidato = (m.group(), pos + m.start(), pos + m.end())
                if pos >= 0 and candidato not in encontrados:
                    encontrados.append(candidato)
    return sorted(encontrados, key=lambda item: item[1])


def _contexto_ncm(texto: str, inicio: int, fim: int) -> tuple[str, int, int]:
    """Prefere a linha/dispositivo inteiro e amplia contexto quando o código está isolado."""

    inicio_linha = texto.rfind("\n", 0, inicio) + 1
    proxima_quebra = texto.find("\n", fim)
    fim_linha = len(texto) if proxima_quebra < 0 else proxima_quebra
    if inicio - inicio_linha < 80 and inicio_linha > 0:
        inicio_linha = texto.rfind("\n", 0, inicio_linha - 1) + 1
    if fim_linha - fim < 80 and fim_linha < len(texto):
        proxima_quebra = texto.find("\n", fim_linha + 1)
        fim_linha = len(texto) if proxima_quebra < 0 else proxima_quebra
    artigos_proximos = list(DISPOSITIVOS["artigo"].finditer(texto[max(0, inicio - 600):inicio]))
    if artigos_proximos:
        inicio_artigo = max(0, inicio - 600) + artigos_proximos[-1].start()
        if fim_linha - inicio_artigo <= MAX_TRECHO:
            inicio_linha = min(inicio_linha, inicio_artigo)
    if fim_linha - inicio_linha > MAX_TRECHO:
        inicio_linha = max(0, inicio - 500)
        fim_linha = min(len(texto), fim + 500)
    return texto[inicio_linha:fim_linha], inicio_linha, fim_linha


def _descricao_proxima_ncm(texto: str, inicio_rotulo: int) -> str | None:
    esquerda = texto[max(0, inicio_rotulo - 220):inicio_rotulo]
    padrao = re.compile(
        r"\b(?:importa[cç][aã]o\s+de|mercadorias?|produtos?)\s+"
        r"(?P<descricao>[^.;:\n]{3,100}?)\s+classificad[oa]s?\s+(?:na|no)\s*$",
        re.I,
    )
    match = padrao.search(esquerda)
    if match:
        return " ".join(match.group("descricao").split())
    return None


def detectar_ncms(texto: str, html_original: str | None = None) -> list[NcmDetectado]:
    """Localiza códigos no ato inteiro antes de qualquer filtro fiscal semântico."""

    encontrados: dict[tuple[int, int], tuple[str, int]] = {}
    for match in NCM_COM_ROTULO.finditer(texto):
        encontrados[(match.start(1), match.end(1))] = (match.group(1), match.start())
    for bloco in _blocos(texto, html_original):
        if bloco.cabecalho:
            for original, inicio, fim in _ncms(bloco):
                encontrados.setdefault((bloco.inicio + inicio, bloco.inicio + fim),
                                      (original, bloco.inicio + inicio))
    for match in NCM_EXATO_SEM_ROTULO.finditer(texto):
        intervalo = (match.start(), match.end())
        if intervalo in encontrados:
            continue
        original = match.group()
        inicio_linha = texto.rfind("\n", 0, match.start()) + 1
        fim_linha = texto.find("\n", match.end())
        contexto_linha = texto[inicio_linha:len(texto) if fim_linha < 0 else fim_linha]
        contexto_fiscal = CONTEXTO_NCM_SEM_ROTULO.search(sem_acentos(contexto_linha).lower())
        partes = original.split(".")
        parece_data = (len(partes) == 3 and 1900 <= int(partes[0]) <= 2099
                       and 1 <= int(partes[1]) <= 12 and 1 <= int(partes[2]) <= 31)
        if "." not in original and 1900 <= int(original[:4]) <= 2099:
            parece_data = (1 <= int(original[4:6]) <= 12 and 1 <= int(original[6:8]) <= 31)
        if parece_data or ("." not in original and not contexto_fiscal):
            continue
        encontrados[intervalo] = (original, match.start())
    resultado: list[NcmDetectado] = []
    for (inicio, fim), (original, inicio_rotulo) in sorted(encontrados.items()):
        contexto, inicio_contexto, fim_contexto = _contexto_ncm(texto, inicio, fim)
        normalizado = original.replace(".", "")
        resultado.append(NcmDetectado(
            original, normalizado, "EXATO" if len(normalizado) == 8 else "PREFIXO",
            inicio, fim, contexto, inicio_contexto, fim_contexto,
            _descricao_proxima_ncm(texto, inicio_rotulo),
        ))
    return resultado


def _tipo_acao(texto: str) -> tuple[str | None, str]:
    t = sem_acentos(texto).lower()
    acao = "SEM_IDENTIFICACAO"
    for padrao, valor in (
        (r"\bfica[m]? revogad[oa]s?\b|\brevoga-se\b", "REVOGA"),
        (r"\bficam? acrescid[oa]s?\b|\bintroduz[- ]se\b", "INCLUI"),
        (r"\bpassa[m]? a vigorar\b|\bficam? alterad[oa]s?\b", "ALTERA"),
        (r"\bprorroga[- ]se\b|\bficam? prorrogad[oa]s?\b", "PRORROGA"),
        (r"\bsubstitu[ií]d[oa]s?\b", "SUBSTITUI"),
        (r"\brenovad[oa]s?\b", "RENOVA"),
    ):
        if re.search(padrao, t):
            acao = valor
            break
    if acao == "REVOGA":
        return "REVOGACAO", acao
    if re.search(r"\breduzid[ao]s?\s+a\s+base|\breducao\s+(?:de\s+\d+[,.]?\d*%\s+)?da\s+base|\bbase\s+de\s+calculo.{0,45}?reduzid", t):
        return "REDUCAO_BASE_CALCULO", acao
    if re.search(r"\b(?:fica[m]?\s+)?isent[oa]s?\b|\bisencao\b", t):
        return "ISENCAO", acao
    if "credito outorgado" in t:
        return "CREDITO_OUTORGADO", acao
    if re.search(r"\bdiferimento\b|\bdiferid[oa]s?\b", t):
        return "DIFERIMENTO", acao
    if SUSPENSAO_TRIBUTARIA.search(t) and CONTEXTO_OPERACAO.search(t) and not CREDITO_TRIBUTARIO.search(t):
        return "SUSPENSAO", acao
    if re.search(r"\baliquota\b", t):
        return "ALIQUOTA", acao
    if re.search(r"\bbeneficio\s+fiscal\b", t):
        return "OUTRO_BENEFICIO", acao
    if acao != "SEM_IDENTIFICACAO":
        return "ALTERACAO_LEGISLATIVA", acao
    return None, acao


def _papel_dispositivo(texto: str, tipo: str, tem_percentual: bool) -> str:
    """Identifica o efeito do trecho sem transformar referência em novo benefício."""

    normalizado = sem_acentos(texto).lower()
    if CONCESSAO_BENEFICIO.search(normalizado):
        return "REGRA_MATERIAL"
    if tipo == "CREDITO_OUTORGADO":
        for papel in ("CONSEQUENCIA", "VEDACAO", "UTILIZACAO", "BENEFICIARIO", "CALCULO"):
            if PAPEIS_COMPLEMENTARES[papel].search(normalizado):
                return papel
    if tipo in {"ALIQUOTA", "REDUCAO_BASE_CALCULO"} and tem_percentual:
        return "REGRA_MATERIAL"
    if tipo == "CREDITO_OUTORGADO" and re.search(r"\bcredito\s+outorgado\s+(?:de|equivalente\s+a)\s+\d", normalizado):
        return "REGRA_MATERIAL"
    if tipo in {"ISENCAO", "DIFERIMENTO", "SUSPENSAO"} and re.search(
        r"\b(?:ficam?\s+)?(?:isent[oa]s?|diferid[oa]s?|suspens[oa]s?|suspensao)\b", normalizado
    ):
        return "REGRA_MATERIAL"
    for papel, padrao in PAPEIS_COMPLEMENTARES.items():
        if padrao.search(normalizado):
            return papel
    if tipo in {"REDUCAO_BASE_CALCULO", "CREDITO_OUTORGADO", "OUTRO_BENEFICIO", "ALIQUOTA", "REVOGACAO"}:
        return "REGRA_MATERIAL"
    return "INDETERMINADO"


def _agrupar_regras(regras: list[RegraExtraida], texto: str) -> None:
    """Agrupa apenas complementos de uma regra material já elegível por NCM."""

    principal: RegraExtraida | None = None
    ultimo_fim = 0
    indice = 0
    while indice < len(regras):
        inicio = regras[indice].inicio_trecho
        fim = regras[indice].fim_trecho
        bloco: list[RegraExtraida] = []
        while indice < len(regras) and (regras[indice].inicio_trecho, regras[indice].fim_trecho) == (inicio, fim):
            bloco.append(regras[indice])
            indice += 1
        entre = sem_acentos(texto[ultimo_fim:inicio]).lower()
        if re.search(r"\b(?:capitulo|secao|titulo)\s+(?:[ivxlcdm]+|\d+)\b", entre):
            principal = None
        ultimo_fim = fim
        materiais = [r for r in bloco if r.papel_dispositivo == "REGRA_MATERIAL"
                     and r.elegivel_consulta_ncm == "SIM" and r.ncm_chave]
        if materiais:
            for regra in materiais:
                chave = f"{hashlib.sha256(texto.encode('utf-8')).hexdigest()}:{regra.chave_extracao}"
                regra.grupo_regra_id = hashlib.sha256(chave.encode("utf-8")).hexdigest()[:32]
            principal = materiais[0] if len(materiais) == 1 else None
            continue
        if any(r.papel_dispositivo == "REGRA_MATERIAL" for r in bloco):
            principal = None
            continue
        if any(r.escopo_fiscal in {"PAUTA_PRECO", "CREDITO_TRIBUTARIO", "ADMINISTRATIVO"} for r in bloco):
            principal = None
            continue
        for regra in bloco:
            if regra.papel_dispositivo in {"REGRA_MATERIAL", "INDETERMINADO"}:
                continue
            tipos_mencionados = {tipo for tipo in ("CREDITO_OUTORGADO", "ISENCAO", "DIFERIMENTO", "SUSPENSAO")
                                if TIPO_EVIDENCIA[tipo].search(regra.trecho_origem)}
            if principal and (not tipos_mencionados or principal.tipo_regra in tipos_mencionados):
                regra.grupo_regra_id = principal.grupo_regra_id
                regra.escopo_fiscal = "ALIQUOTA_BENEFICIO"
                regra.elegivel_consolidacao = "NAO"
                regra.motivo_elegibilidade = "Dispositivo complementar vinculado à regra material."
                regra.motivos_confianca.append("Vinculado por sequência textual e tipo de benefício; revisar associação.")
                regra.confianca = "MEDIA" if regra.confianca != "BAIXA" else "BAIXA"


def _mercadoria_identificada(regra: RegraExtraida) -> bool:
    """Exige descrição concreta no trecho, sem inferir um código fiscal."""

    candidatos = [regra.descricao_legal] if regra.descricao_legal else []
    candidatos.extend(m.group("descricao") for m in PRODUTO_DESCRITO.finditer(regra.trecho_origem))
    for candidato in candidatos:
        primeira = sem_acentos(candidato.strip()).lower().split(" ", 1)[0] if candidato else ""
        if primeira and primeira not in DESCRITOR_GENERICO and not primeira.isdigit():
            return True
    return False


def _classificar_consulta_ncm(regra: RegraExtraida) -> None:
    """Filtra a consulta pública sem descartar a extração legislativa."""

    principal = regra.papel_dispositivo == "REGRA_MATERIAL" and regra.elegivel_consolidacao == "SIM"
    if regra.ncm_chave:
        regra.status_vinculo_ncm = "NCM_EXPLICITO"
        if principal:
            regra.elegivel_consulta_ncm = "SIM"
            regra.motivo_consulta_ncm = "NCM, posição ou subposição explícita no dispositivo material."
        else:
            regra.motivo_consulta_ncm = (MOTIVO_NCM_PROCEDIMENTAL if regra.escopo_fiscal == "PROCEDIMENTO"
                                        else "NCM explícito em dispositivo sem regra material independente.")
        return
    if principal and _mercadoria_identificada(regra):
        regra.status_vinculo_ncm = "PENDENTE_VINCULO_NCM"
        regra.motivo_consulta_ncm = MOTIVO_PENDENTE
        return
    regra.status_vinculo_ncm = "SEM_VINCULO_NCM"
    regra.motivo_consulta_ncm = (MOTIVO_SEM_VINCULO if principal else
                                "Dispositivo sem regra material independente para consulta NCM.")


def _completar_ncms(regras: list[RegraExtraida], deteccoes: list[NcmDetectado],
                    texto: str) -> list[RegraExtraida]:
    """Vincula NCM à regra do mesmo trecho ou cria referência auditável separada."""

    def preservar_descricao(regra: RegraExtraida, detectado: NcmDetectado) -> None:
        if not detectado.descricao_proxima or regra.descricao_proxima_ncm:
            return
        regra.descricao_proxima_ncm = detectado.descricao_proxima
        inicio = texto.rfind(detectado.descricao_proxima, detectado.inicio_contexto, detectado.inicio)
        if inicio >= 0:
            regra.evidencias.append(EvidenciaFiscal(
                "DESCRICAO_PROXIMA_NCM", detectado.descricao_proxima,
                texto[inicio:inicio + len(detectado.descricao_proxima)],
                inicio, inicio + len(detectado.descricao_proxima), metodo="varredura_integral_v3",
            ))

    referencias: list[RegraExtraida] = []
    for detectado in deteccoes:
        ja_vinculadas = [regra for regra in regras if any(
            e.tipo_evidencia == "NCM" and
            (e.posicao_inicio, e.posicao_fim) == (detectado.inicio, detectado.fim)
            for e in regra.evidencias)]
        if ja_vinculadas:
            for regra in ja_vinculadas:
                preservar_descricao(regra, detectado)
            continue
        abrangentes = [r for r in regras if r.inicio_trecho <= detectado.inicio
                       and detectado.fim <= r.fim_trecho]
        unico = (abrangentes[0] if len(abrangentes) == 1 and abrangentes[0].ncm_chave is None
                 and sum(abrangentes[0].inicio_trecho <= d.inicio and
                         d.fim <= abrangentes[0].fim_trecho for d in deteccoes) == 1 else None)
        if unico:
            unico.ncm_chave = detectado.normalizado
            unico.ncm_original = detectado.original
            unico.tipo_correspondencia = detectado.tipo_correspondencia
            preservar_descricao(unico, detectado)
            unico.evidencias.append(EvidenciaFiscal(
                "NCM", detectado.original, texto[detectado.inicio:detectado.fim],
                detectado.inicio, detectado.fim, metodo="varredura_integral_v3",
            ))
            unico.motivos_confianca.append("NCM explícito localizado na varredura integral do mesmo trecho.")
            continue
        normalizado_contexto = sem_acentos(detectado.contexto).lower()
        procedimental = bool(NCM_PROCEDIMENTAL.search(normalizado_contexto))
        referencia = RegraExtraida(
            "ALTERACAO_LEGISLATIVA", "SEM_IDENTIFICACAO", detectado.contexto,
            detectado.inicio_contexto, detectado.fim_contexto,
            ncm_chave=detectado.normalizado, ncm_original=detectado.original,
            tipo_correspondencia=detectado.tipo_correspondencia,
            papel_dispositivo="PROCEDIMENTO" if procedimental else "REFERENCIA",
            escopo_fiscal="PROCEDIMENTO" if procedimental else "INDETERMINADO",
            motivo_elegibilidade="Referência a NCM sem regra tributária material independente.",
            confianca="BAIXA",
        )
        referencia.evidencias.append(EvidenciaFiscal(
            "NCM", detectado.original, texto[detectado.inicio:detectado.fim],
            detectado.inicio, detectado.fim, metodo="varredura_integral_v3",
        ))
        preservar_descricao(referencia, detectado)
        artigo = list(DISPOSITIVOS["artigo"].finditer(texto[:detectado.inicio]))
        if artigo:
            ultimo = artigo[-1]
            referencia.artigo = ultimo.group(1).rstrip("º°")
            referencia.evidencias.append(EvidenciaFiscal(
                "ARTIGO", referencia.artigo, ultimo.group(), ultimo.start(), ultimo.end(),
                metodo="varredura_integral_v3",
            ))
        referencia.motivos_confianca.append(
            "NCM explícito preservado antes dos filtros fiscais; enquadramento material não identificado."
        )
        referencias.append(referencia)
    return referencias


def _classificar_escopo(regra: RegraExtraida, bloco: Bloco) -> None:
    """Separa regra fiscal material de menções correlatas sem descartar a evidência."""

    texto = sem_acentos(bloco.texto).lower()
    escopo: str | None = None
    motivo: str
    tipo_material = regra.tipo_regra in {
        "ALIQUOTA", "ISENCAO", "REDUCAO_BASE_CALCULO", "CREDITO_OUTORGADO", "DIFERIMENTO", "SUSPENSAO",
    }
    # Para alíquota, a palavra isolada em uma pauta não define a taxa aplicável.
    if regra.tipo_regra == "ALIQUOTA":
        tipo_material = regra.aliquota_icms is not None
    if regra.tipo_regra == "OUTRO_BENEFICIO":
        tipo_material = bool(re.search(r"\bbeneficio\s+fiscal\b.{0,80}\b(?:icms|operac(?:ao|oes)|mercadoria|produto)\b", texto))
    if CREDITO_TRIBUTARIO.search(texto) and regra.tipo_regra not in {
        "ALIQUOTA", "ISENCAO", "REDUCAO_BASE_CALCULO", "CREDITO_OUTORGADO", "DIFERIMENTO",
    }:
        escopo = "CREDITO_TRIBUTARIO"
        motivo = "Menção a crédito tributário, exigibilidade ou cobrança; não define benefício aplicável à operação."
    elif PROCEDIMENTO.search(texto) and regra.tipo_regra not in {
        "ALIQUOTA", "ISENCAO", "REDUCAO_BASE_CALCULO", "CREDITO_OUTORGADO", "DIFERIMENTO",
    }:
        escopo = "PROCEDIMENTO"
        motivo = "Procedimento administrativo sem regra material de alíquota ou benefício."
    elif ADMINISTRATIVO.search(texto):
        escopo = "ADMINISTRATIVO"
        motivo = "Conteúdo administrativo sem regra material de alíquota ou benefício."
    elif PAUTA_PRECO.search(texto) and not tipo_material:
        escopo = "PAUTA_PRECO"
        motivo = "Alteração de pauta ou preço de referência sem regra fiscal material explícita."
    elif regra.tipo_regra in {
        "ALIQUOTA", "ISENCAO", "REDUCAO_BASE_CALCULO", "CREDITO_OUTORGADO", "DIFERIMENTO", "SUSPENSAO", "OUTRO_BENEFICIO",
    }:
        # Palavra fiscal isolada não basta: exige valor, ICMS, NCM ou contexto da operação.
        material = (bool(CONCESSAO_BENEFICIO.search(texto))
                    or regra.aliquota_icms is not None or regra.percentual_reducao_bc is not None
                    or regra.credito_outorgado_percentual is not None
                    or bool(re.search(r"\bicms\b", texto))
                    or bool(regra.ncm_chave)
                    or bool(CONTEXTO_OPERACAO.search(texto)))
        if material and tipo_material:
            regra.escopo_fiscal = "ALIQUOTA_BENEFICIO"
            regra.elegivel_consolidacao = "SIM"
            regra.motivo_elegibilidade = "Regra material explícita de alíquota ou benefício fiscal."
            return
        escopo = "INDETERMINADO"
        motivo = "Termo fiscal isolado, sem conteúdo material suficiente para consolidação."
    elif regra.tipo_regra == "REVOGACAO" and re.search(
        r"\b(?:icms|aliquota|isencao|reducao\s+da\s+base|credito\s+outorgado|diferimento)\b", texto
    ):
        regra.escopo_fiscal = "ALIQUOTA_BENEFICIO"
        regra.elegivel_consolidacao = "SIM"
        regra.motivo_elegibilidade = "Revogação explicitamente vinculada a alíquota ou benefício fiscal."
        return
    else:
        escopo = "INDETERMINADO"
        motivo = "Ação ou menção genérica sem regra fiscal material identificada."
    regra.escopo_fiscal = escopo
    regra.elegivel_consolidacao = "NAO"
    regra.motivo_elegibilidade = motivo
    if escopo != "INDETERMINADO":
        padrao = {"PAUTA_PRECO": PAUTA_PRECO, "CREDITO_TRIBUTARIO": CREDITO_TRIBUTARIO,
                  "PROCEDIMENTO": PROCEDIMENTO, "ADMINISTRATIVO": ADMINISTRATIVO}[escopo]
        match = padrao.search(texto)
        if match:
            regra.evidencias.append(_evidencia(bloco, match.start(), match.end(), "ESCOPO_FISCAL", bloco.texto[match.start():match.end()]))


def _data(match: re.Match[str] | None) -> date | None:
    if not match:
        return None
    mes = MESES.get(sem_acentos(match.group(2)).lower())
    if mes is None:
        return None
    try:
        return date(int(match.group(3)), mes, int(match.group(1)))
    except ValueError:
        return None


def _preencher_contexto(regra: RegraExtraida, bloco: Bloco) -> None:
    acao = ACAO_EVIDENCIA.get(regra.acao_legislativa)
    match_acao = acao.search(bloco.texto) if acao else None
    if match_acao:
        regra.evidencias.append(_evidencia(bloco, match_acao.start(), match_acao.end(),
                                            "ACAO_LEGISLATIVA", match_acao.group()))
    padrao_tipo = TIPO_EVIDENCIA.get(regra.tipo_regra)
    match_tipo = padrao_tipo.search(bloco.texto) if padrao_tipo else None
    if match_tipo:
        regra.evidencias.append(_evidencia(bloco, match_tipo.start(), match_tipo.end(),
                                            "TIPO_REGRA", match_tipo.group()))
    for campo, padrao in DISPOSITIVOS.items():
        match = padrao.search(bloco.texto)
        if match:
            valor = match.group(1).rstrip("º°")
            setattr(regra, campo, valor)
            regra.evidencias.append(_evidencia(bloco, match.start(), match.end(), campo.upper(), valor))
    for campo, padrao in PADROES_PERCENTUAIS:
        match = padrao.search(bloco.texto)
        if match:
            grupo = next((indice for indice, valor in enumerate(match.groups(), 1) if valor is not None), None)
            if grupo is not None:
                valor = match.group(grupo)
                setattr(regra, campo, Decimal(valor.replace(",", ".")))
                tipo = {"aliquota_icms": "ALIQUOTA", "percentual_reducao_bc": "REDUCAO_BC", "carga_efetiva": "CARGA_EFETIVA", "credito_outorgado_percentual": "CREDITO_OUTORGADO"}[campo]
                regra.evidencias.append(_evidencia(bloco, match.start(grupo), match.end(grupo), tipo, valor))
    # Em tabela, um cabeçalho explícito também fornece o contexto do percentual.
    if bloco.cabecalho and bloco.celulas:
        for titulo, celula in zip(bloco.cabecalho, bloco.celulas):
            contexto = sem_acentos(titulo).lower()
            inicio = bloco.texto.find(celula)
            if inicio < 0:
                continue
            if "descricao" in contexto and regra.descricao_legal is None and celula.strip():
                regra.descricao_legal = celula.strip()
                regra.evidencias.append(_evidencia(bloco, inicio, inicio + len(celula), "DESCRICAO", celula.strip(), "cabecalho_tabela_v2"))
            percentual = PERCENTUAL.fullmatch(celula.strip())
            if not percentual:
                continue
            campo = (("aliquota_icms", "ALIQUOTA") if "aliquota" in contexto else
                     ("percentual_reducao_bc", "REDUCAO_BC") if "reducao" in contexto else
                     ("carga_efetiva", "CARGA_EFETIVA") if "carga" in contexto else
                     ("credito_outorgado_percentual", "CREDITO_OUTORGADO") if "credito outorgado" in contexto else None)
            if campo and getattr(regra, campo[0]) is None:
                setattr(regra, campo[0], Decimal(percentual.group(1).replace(",", ".")))
                regra.evidencias.append(_evidencia(bloco, inicio, inicio + len(celula), campo[1], percentual.group(1), "cabecalho_tabela_v2"))
    condicao = CONDICAO.search(bloco.texto)
    if condicao:
        regra.condicoes_texto = bloco.texto.strip()
        regra.evidencias.append(_evidencia(bloco, condicao.start(), condicao.end(), "CONDICAO", condicao.group()))
    excecao = EXCECAO.search(bloco.texto)
    if excecao:
        regra.alertas.append("Exceção ou vedação explícita; revisar alcance da regra.")
        regra.evidencias.append(_evidencia(bloco, excecao.start(), excecao.end(), "EXCECAO", excecao.group()))
        if regra.condicoes_texto is None:
            regra.condicoes_texto = bloco.texto.strip()
    for campo, padrao in (("vigencia_inicio", VIGENCIA_INICIO), ("vigencia_fim", VIGENCIA_FIM)):
        match = padrao.search(bloco.texto)
        if match:
            valor = _data(match)
            if valor:
                setattr(regra, campo, valor)
                regra.evidencias.append(_evidencia(bloco, match.start(), match.end(), "VIGENCIA", match.group()))
            else:
                regra.alertas.append("Data de vigência textual não pôde ser interpretada.")
    encontrados_norma = list(NORMA_ALTERADA.finditer(bloco.texto))
    normas = list(dict.fromkeys(m.group() for m in encontrados_norma))
    regra.norma_alterada = "; ".join(normas) or None
    for match_norma in encontrados_norma:
        regra.evidencias.append(_evidencia(bloco, match_norma.start(), match_norma.end(),
                                            "NORMA_ALTERADA", match_norma.group()))


def _avaliar(regra: RegraExtraida, quantidade_ncm: int) -> None:
    explicitacao = regra.tipo_regra != "ALTERACAO_LEGISLATIVA"
    dispositivo = any((regra.anexo, regra.artigo, regra.paragrafo, regra.inciso, regra.alinea, regra.item))
    campo_percentual = {
        "ALIQUOTA": "aliquota_icms",
        "REDUCAO_BASE_CALCULO": "percentual_reducao_bc",
        "CREDITO_OUTORGADO": "credito_outorgado_percentual",
    }.get(regra.tipo_regra)
    if not explicitacao:
        regra.motivos_confianca.append("Ação ou percentual detectado sem regra fiscal completa.")
        regra.confianca = "BAIXA"
    elif not regra.ncm_chave:
        regra.motivos_confianca.append("Tipo fiscal explícito, mas sem NCM confirmado no mesmo trecho.")
        regra.confianca = "MEDIA"
    elif not dispositivo or (campo_percentual and getattr(regra, campo_percentual) is None):
        regra.motivos_confianca.append("NCM e tipo fiscal identificados; dispositivo ou percentual específico ausente.")
        regra.confianca = "MEDIA"
    else:
        regra.motivos_confianca.append("NCM, tipo fiscal e dispositivo explícitos no mesmo trecho.")
        regra.confianca = "ALTA"
    if quantidade_ncm > 1:
        regra.alertas.append("Vários NCMs no mesmo trecho; confirmar associação individual.")
        regra.confianca = "BAIXA"
    if regra.alertas:
        regra.confianca = "BAIXA"
        regra.motivos_confianca.append("Há alerta de ambiguidade, exceção ou vedação.")


def extrair_regras(texto_limpo: str, texto_original: str | None = None) -> list[RegraExtraida]:
    """Extrai candidatos por trecho independente, sem afirmar enquadramento fiscal."""

    deteccoes_ncm = detectar_ncms(texto_limpo, texto_original)
    regras: list[RegraExtraida] = []
    artigo_contexto: tuple[str, str, int, int] | None = None
    for bloco in (parte for original in _blocos(texto_limpo, texto_original)
                  for parte in _fragmentar(original)):
        artigo_encontrado = DISPOSITIVOS["artigo"].search(bloco.texto)
        if artigo_encontrado and not bloco.cabecalho and not bloco.fragmentado and artigo_encontrado.start() == 0:
            artigo_contexto = (artigo_encontrado.group(1).rstrip("º°"), artigo_encontrado.group(),
                               bloco.inicio + artigo_encontrado.start(), bloco.inicio + artigo_encontrado.end())
        tipo_bruto, acao = _tipo_acao(" ".join(bloco.cabecalho) + " " + bloco.texto if bloco.cabecalho else bloco.texto)
        ncms = _ncms(bloco)
        percentuais = list(PERCENTUAL.finditer(bloco.texto))
        papel = _papel_dispositivo(bloco.texto, tipo_bruto or "ALTERACAO_LEGISLATIVA", bool(percentuais))
        texto_normalizado = sem_acentos(bloco.texto).lower()
        marcador_escopo = any(p.search(texto_normalizado) for p in (
            PAUTA_PRECO, CREDITO_TRIBUTARIO, PROCEDIMENTO, ADMINISTRATIVO,
        ))
        if tipo_bruto is None and not (percentuais and ncms) and not marcador_escopo and papel == "INDETERMINADO":
            continue
        tipo = tipo_bruto if papel == "REGRA_MATERIAL" else "ALTERACAO_LEGISLATIVA"
        tipo = tipo or "ALTERACAO_LEGISLATIVA"
        for ncm in ncms or [None]:
            regra = RegraExtraida(tipo, acao, bloco.texto, bloco.inicio, bloco.fim)
            regra.papel_dispositivo = papel
            if tipo in {"ISENCAO", "REDUCAO_BASE_CALCULO", "CREDITO_OUTORGADO",
                        "DIFERIMENTO", "SUSPENSAO", "OUTRO_BENEFICIO"}:
                regra.tipo_beneficio = tipo
            if ncm:
                original, inicio, fim = ncm
                chave = original.replace(".", "")
                regra.ncm_original = original
                regra.ncm_chave = chave
                regra.tipo_correspondencia = "EXATO" if len(chave) == 8 else "PREFIXO"
                regra.evidencias.append(_evidencia(bloco, inicio, fim, "NCM", original))
            _preencher_contexto(regra, bloco)
            padrao_papel = (CONCESSAO_BENEFICIO if papel == "REGRA_MATERIAL" else
                            PAPEIS_COMPLEMENTARES.get(papel))
            match_papel = padrao_papel.search(texto_normalizado) if padrao_papel else None
            if match_papel:
                regra.evidencias.append(_evidencia(bloco, match_papel.start(), match_papel.end(),
                                                    "PAPEL_DISPOSITIVO", bloco.texto[match_papel.start():match_papel.end()]))
            if papel != "REGRA_MATERIAL" and tipo_bruto in TIPO_EVIDENCIA:
                referido = TIPO_EVIDENCIA[tipo_bruto].search(bloco.texto)
                if referido:
                    regra.evidencias.append(_evidencia(bloco, referido.start(), referido.end(),
                                                        "BENEFICIO_REFERENCIADO", referido.group()))
            if artigo_contexto and not (artigo_encontrado and artigo_encontrado.start() == 0):
                artigo, origem, inicio_artigo, fim_artigo = artigo_contexto
                regra.artigo = artigo
                regra.evidencias.append(EvidenciaFiscal("ARTIGO", artigo, origem,
                                                         inicio_artigo, fim_artigo))
            _classificar_escopo(regra, bloco)
            if papel != "REGRA_MATERIAL":
                regra.elegivel_consolidacao = "NAO"
                if regra.escopo_fiscal == "ALIQUOTA_BENEFICIO":
                    regra.motivo_elegibilidade = "Dispositivo complementar sem regra material independente."
            if bloco.fragmentado:
                regra.alertas.append("Trecho extenso dividido; revisar associação e contexto jurídico.")
            classificados = {(ev.posicao_inicio, ev.posicao_fim) for ev in regra.evidencias if ev.tipo_evidencia in {
                "ALIQUOTA", "REDUCAO_BC", "CARGA_EFETIVA", "CREDITO_OUTORGADO"}}
            for match in percentuais:
                posicoes = (bloco.inicio + match.start(), bloco.inicio + match.end())
                if not any(posicoes[0] <= inicio and fim <= posicoes[1] for inicio, fim in classificados):
                    regra.evidencias.append(_evidencia(bloco, match.start(), match.end(), "PERCENTUAL_NAO_CLASSIFICADO", match.group()))
                    regra.alertas.append("Percentual detectado sem classificação contextual segura.")
            _avaliar(regra, len(ncms))
            if regra.elegivel_consolidacao == "NAO":
                regra.confianca = "BAIXA"
                regra.motivos_confianca.append(regra.motivo_elegibilidade)
            regras.append(regra)
    referencias_ncm = _completar_ncms(regras, deteccoes_ncm, texto_limpo)
    regras.extend(referencias_ncm)
    regras.sort(key=lambda regra: (regra.inicio_trecho, regra.fim_trecho, regra.ncm_chave or ""))
    for regra in regras:
        _classificar_consulta_ncm(regra)
        if regra.elegivel_consulta_ncm != "SIM":
            if regra.elegivel_consolidacao == "SIM":
                regra.motivo_elegibilidade = (
                    "Regra material sem NCM, posição ou subposição explícita; "
                    "fora da consolidação da consulta por NCM."
                )
            regra.elegivel_consolidacao = "NAO"
    _agrupar_regras(regras, texto_limpo)
    return regras
