"""Valores e textos para apresentação, sem criar dados fiscais."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .busca import texto
from .modelos import Candidato

EXIBICAO_LEGISLACAO = (
    ("norma", "Norma"), ("numero", "Número"), ("ano", "Ano"),
    ("anexo", "Anexo"), ("artigo", "Artigo"), ("paragrafo", "Parágrafo"),
    ("inciso", "Inciso"), ("alinea", "Alínea"), ("item", "Item"),
    ("resumo", "Resumo"), ("url_fonte", "URL"),
    ("texto_relevante", "Trecho da legislação"),
)
EXIBICAO_BENEFICIO = (
    ("tipo_beneficio", "Tipo de benefício"),
    ("cbenef", "cBenef"),
    ("percentual_reducao_bc", "Redução da Base de Cálculo"),
    ("carga_efetiva", "Carga tributária efetiva"),
    ("credito_outorgado_percentual", "Crédito outorgado"),
    ("grupo_beneficio", "Grupo do benefício"),
    ("aplicacao", "Aplicação"),
    ("escopo_operacao", "Operação prevista"),
    ("condicoes", "Condições"),
)
CAMPOS_PERCENTUAIS = {
    "aliquota_icms", "adicional_percentual", "percentual_reducao_bc",
    "carga_efetiva", "credito_outorgado_percentual",
}
ROTULOS_ENUMS = {
    "tipo_beneficio": {
        "REDUCAO_BASE_CALCULO": "Redução da base de cálculo",
        "ISENCAO": "Isenção",
        "DIFERIMENTO": "Diferimento",
        "CREDITO_OUTORGADO": "Crédito outorgado",
    },
    "aplicacao": {
        "UNICO": "Benefício único",
        "ALTERNATIVO": "Benefícios alternativos",
        "CUMULATIVO": "Benefícios cumulativos",
    },
    "escopo_operacao": {
        "INTERNA": "Operação interna",
        "INTERESTADUAL": "Operação interestadual",
        "AMBAS": "Operações interna e interestadual",
        "NAO_DEFINIDA": "Não definida na base",
    },
}


def rotulo_enum(campo: str, valor: Any) -> str:
    """Traduz códigos conhecidos apenas na camada de apresentação."""

    original = texto(valor)
    return ROTULOS_ENUMS.get(campo, {}).get(original.upper(), original)


def formatar_percentual(valor: Any) -> str:
    """Formata pontos percentuais da planilha com duas casas, sem mudar a escala."""

    original = texto(valor)
    if not original:
        return "Não informado na base"
    try:
        numero = Decimal(original.removesuffix("%").strip().replace(",", "."))
        if not numero.is_finite():
            raise InvalidOperation
        return f"{numero.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}".replace(".", ",") + "%"
    except InvalidOperation:
        return f"Valor percentual inválido na base: {original}"


def valor_exibicao(valor: Any) -> str:
    """Exibe o valor original da célula sem supor escala percentual."""

    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, Decimal):
        return format(valor, "f")
    return texto(valor) or "Não informado na base"


def campos_preenchidos(candidato: Candidato, campos: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """Retorna apenas os campos cadastrados para um fundamento ou benefício."""

    fonte = candidato.legislacao if campos == EXIBICAO_LEGISLACAO else candidato.dados
    if fonte is None:
        return []
    return [
        (rotulo, formatar_percentual(fonte.get(chave)) if chave in CAMPOS_PERCENTUAIS
         else rotulo_enum(chave, fonte.get(chave)) if chave in ROTULOS_ENUMS
         else valor_exibicao(fonte.get(chave)))
        for chave, rotulo in campos if texto(fonte.get(chave))
    ]


def vigencia_exibicao(candidato: Candidato) -> str:
    """Apresenta somente os limites cadastrados da vigência."""

    inicio_bruto = texto(candidato.dados.get("vigencia_inicio"))
    fim_bruto = texto(candidato.dados.get("vigencia_fim"))

    def data_formatada(valor: Any) -> str:
        if isinstance(valor, (date, datetime)):
            return valor.strftime("%d/%m/%Y")
        bruto = texto(valor)
        try:
            return date.fromisoformat(bruto[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return bruto

    if inicio_bruto and fim_bruto:
        return f"{data_formatada(candidato.dados['vigencia_inicio'])} até {data_formatada(candidato.dados['vigencia_fim'])}"
    if inicio_bruto:
        return f"Início da vigência: {data_formatada(candidato.dados['vigencia_inicio'])}"
    if fim_bruto:
        return f"Fim da vigência: {data_formatada(candidato.dados['vigencia_fim'])}"
    return "Vigência específica não cadastrada."
