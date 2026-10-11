"""Formatação da alíquota cadastrada, sem alterar sua escala."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .busca import texto


def formatar_percentual(valor: Any) -> str:
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
