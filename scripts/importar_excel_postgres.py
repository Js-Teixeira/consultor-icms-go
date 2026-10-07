"""Importa planilha validada para PostgreSQL em uma única transação."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Date, Integer, Numeric, Table, func, inspect, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from src.carregamento import CAMINHO_BASE, ErroBase, carregar_base
from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import TABELAS
from src.modelos import BaseTributaria, ESCOPOS_OPERACAO, PREFIXOS_NCM_VALIDOS
from src.rastreabilidade import ids_informados, origens_consolidacao, problemas_vinculo
from updater.schema import evidencias_extracao, regras_consolidadas, regras_extraidas


class ErroImportacao(ValueError):
    """Dados da planilha incompatíveis com o schema PostgreSQL."""


def _vazio(valor: Any) -> bool:
    if valor is None:
        return True
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def _texto(valor: Any) -> str | None:
    if _vazio(valor):
        return None
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    resultado = str(valor).strip()
    return resultado or None


def _data(valor: Any, nome: str, linha: int, coluna: str) -> date | None:
    if _vazio(valor) or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        if isinstance(valor, datetime):
            return valor.date()
        if isinstance(valor, date):
            return valor
        if isinstance(valor, str):
            return date.fromisoformat(valor.strip())
        raise ValueError("formato não suportado")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ErroImportacao(f"Data inválida em {nome}, linha {linha}, coluna {coluna}.") from exc


def _percentual(valor: Any, nome: str, linha: int, coluna: str) -> Decimal | None:
    texto = _texto(valor)
    if texto is None:
        return None
    try:
        resultado = Decimal(texto.replace(",", "."))
        if not resultado.is_finite():
            raise InvalidOperation
        return resultado
    except InvalidOperation as exc:
        raise ErroImportacao(f"Percentual inválido em {nome}, linha {linha}, coluna {coluna}.") from exc


def _id_opcional(valor: Any, nome: str, linha: int, coluna: str) -> int | None:
    bruto = _texto(valor)
    if bruto is None:
        return None
    if not re.fullmatch(r"[1-9][0-9]*", bruto):
        raise ErroImportacao(f"ID inválido em {nome}, linha {linha}, coluna {coluna}.")
    return int(bruto)


def _normalizar_linha(nome: str, tabela: Table, linha: pd.Series, numero: int) -> dict[str, Any]:
    registro: dict[str, Any] = {}
    for coluna in tabela.columns:
        valor = linha.get(coluna.name)
        if isinstance(coluna.type, Date):
            registro[coluna.name] = _data(valor, nome, numero, coluna.name)
        elif isinstance(coluna.type, Numeric):
            registro[coluna.name] = _percentual(valor, nome, numero, coluna.name)
        elif isinstance(coluna.type, Integer):
            registro[coluna.name] = _id_opcional(valor, nome, numero, coluna.name)
        else:
            registro[coluna.name] = _texto(valor)

    chave = next(iter(tabela.primary_key.columns)).name
    if not registro[chave]:
        raise ErroImportacao(f"Chave {chave} vazia em {nome}, linha {numero}.")
    if nome == "NCM":
        if not isinstance(linha.get("ncm"), str) or not re.fullmatch(r"[0-9]{8}", registro["ncm"]):
            raise ErroImportacao(f"NCM deve ser texto com 8 dígitos em {nome}, linha {numero}.")
    if nome in {"Aliquotas", "Beneficios"}:
        chave_ncm = registro["chave_ncm"]
        tipo = (registro["tipo_correspondencia"] or "").upper()
        if not chave_ncm or not re.fullmatch(r"[0-9]{1,8}", chave_ncm):
            raise ErroImportacao(f"chave_ncm inválida em {nome}, linha {numero}.")
        if not isinstance(linha.get("chave_ncm"), str):
            raise ErroImportacao(f"chave_ncm deve ser texto em {nome}, linha {numero}.")
        if (tipo not in {"EXATO", "PREFIXO"}
                or (tipo == "EXATO" and len(chave_ncm) != 8)
                or (tipo == "PREFIXO" and len(chave_ncm) not in PREFIXOS_NCM_VALIDOS)):
            raise ErroImportacao(f"tipo_correspondencia inválido em {nome}, linha {numero}.")
        registro["tipo_correspondencia"] = tipo
        exige = (registro["exige_descricao"] or "").upper()
        if exige not in {"SIM", "NAO"}:
            raise ErroImportacao(f"exige_descricao inválido em {nome}, linha {numero}.")
        registro["exige_descricao"] = exige
    ativo = (registro["ativo"] or "").upper()
    if ativo not in {"SIM", "NAO"}:
        raise ErroImportacao(f"ativo inválido em {nome}, linha {numero}.")
    registro["ativo"] = ativo
    if nome == "Beneficios" and registro["aplicacao"]:
        aplicacao = registro["aplicacao"].upper()
        if aplicacao not in {"UNICO", "ALTERNATIVO", "CUMULATIVO"}:
            raise ErroImportacao(f"aplicacao inválida em {nome}, linha {numero}.")
        registro["aplicacao"] = aplicacao
    if nome == "Beneficios" and registro["escopo_operacao"]:
        escopo = registro["escopo_operacao"].upper()
        if escopo not in ESCOPOS_OPERACAO:
            raise ErroImportacao(f"escopo_operacao inválido em {nome}, linha {numero}.")
        registro["escopo_operacao"] = escopo
    return registro


def preparar_registros(base: BaseTributaria) -> dict[str, list[dict[str, Any]]]:
    """Converte linhas Excel aos tipos SQL e rejeita chaves duplicadas."""

    abas = {
        "NCM": base.ncm,
        "Legislacao": base.legislacao,
        "Aliquotas": base.aliquotas,
        "Beneficios": base.beneficios,
    }
    preparados: dict[str, list[dict[str, Any]]] = {}
    for nome, tabela in TABELAS.items():
        chave = next(iter(tabela.primary_key.columns)).name
        vistos: set[str] = set()
        registros = []
        for indice, linha in abas[nome].iterrows():
            registro = _normalizar_linha(nome, tabela, linha, indice + 2)
            if registro[chave] in vistos:
                raise ErroImportacao(f"Chave {chave} duplicada em {nome}, linha {indice + 2}.")
            vistos.add(registro[chave])
            registros.append(registro)
        preparados[nome] = registros
    return preparados


def validar_rastreabilidade(conexao: Any, preparados: dict[str, list[dict[str, Any]]]) -> None:
    """Confere somente IDs curados presentes na carga, antes de qualquer escrita."""

    fiscais = [(nome, registro) for nome in ("Aliquotas", "Beneficios")
               for registro in preparados[nome] if ids_informados(registro)]
    if not fiscais:
        return
    inspetor = inspect(conexao)
    for tabela in (regras_consolidadas, regras_extraidas, evidencias_extracao):
        if not inspetor.has_table(tabela.name):
            raise ErroImportacao(f"Rastreabilidade fornecida, mas a tabela {tabela.name} não existe.")
    consol_ids = {r["regra_consolidada_id"] for _, r in fiscais if r.get("regra_consolidada_id")}
    evidencia_ids = {r["evidencia_ncm_id"] for _, r in fiscais if r.get("evidencia_ncm_id")}
    consolidadas = {str(r["id"]): dict(r) for r in conexao.execute(select(
        regras_consolidadas.c.id, regras_consolidadas.c.regra_origem_id,
        regras_consolidadas.c.origens_equivalentes,
        regras_consolidadas.c.ato_origem_id).where(
            regras_consolidadas.c.id.in_(consol_ids))).mappings()}
    evidencias = {str(r["id"]): dict(r) for r in conexao.execute(select(
        evidencias_extracao.c.id, evidencias_extracao.c.regra_extraida_id,
        evidencias_extracao.c.tipo_evidencia, evidencias_extracao.c.valor_extraido).where(
            evidencias_extracao.c.id.in_(evidencia_ids))).mappings()}
    try:
        origem_ids = {int(origem) for r in consolidadas.values() for origem in origens_consolidacao(r)}
    except ValueError as exc:
        raise ErroImportacao("Rastreabilidade: origens equivalentes inválidas na consolidação.") from exc
    origem_ids |= {r["regra_extraida_id"] for r in evidencias.values()}
    extraidas = {str(r["id"]): dict(r) for r in conexao.execute(select(
        regras_extraidas.c.id, regras_extraidas.c.ato_id).where(
        regras_extraidas.c.id.in_(origem_ids))).mappings()}
    for nome, registro in fiscais:
        problemas = problemas_vinculo(registro, consolidadas, extraidas, evidencias)
        if problemas:
            chave = registro.get("id_regra") or registro.get("id_beneficio")
            raise ErroImportacao(f"{nome} {chave}: {problemas[0][0]}: {problemas[0][1]}")


def importar_base(base: BaseTributaria, repositorio: PostgresRepository, *, confirmar_atualizacao: bool = False) -> dict[str, int]:
    """Insere sem duplicar; atualiza existentes somente com confirmação explícita."""

    preparados = preparar_registros(base)
    with repositorio.engine.begin() as conexao:
        validar_rastreabilidade(conexao, preparados)
        for nome, tabela in TABELAS.items():
            registros = preparados[nome]
            if not registros:
                continue
            chave = next(iter(tabela.primary_key.columns)).name
            insercao = pg_insert(tabela)
            if confirmar_atualizacao:
                atualizacoes = {
                    coluna.name: (func.coalesce(insercao.excluded[coluna.name], tabela.c[coluna.name])
                                  if coluna.name in {"regra_consolidada_id", "evidencia_ncm_id"}
                                  else insercao.excluded[coluna.name])
                    for coluna in tabela.columns if coluna.name != chave
                }
                comando = insercao.on_conflict_do_update(index_elements=[tabela.c[chave]], set_=atualizacoes)
            else:
                comando = insercao.on_conflict_do_nothing(index_elements=[tabela.c[chave]])
            conexao.execute(comando, registros)
    return {nome: len(registros) for nome, registros in preparados.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa a planilha para PostgreSQL.")
    parser.add_argument("--planilha", type=Path, default=CAMINHO_BASE)
    parser.add_argument("--confirmar-atualizacao", action="store_true", help="Atualiza registros existentes com os dados da planilha")
    args = parser.parse_args()
    try:
        base = carregar_base(args.planilha)
        repositorio = criar_repositorio(data_source="postgres")
        assert isinstance(repositorio, PostgresRepository)
        totais = importar_base(base, repositorio, confirmar_atualizacao=args.confirmar_atualizacao)
    except (ErroBase, ErroConfiguracaoDados, ErroImportacao) as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError):
        print("Não foi possível importar para a base tributária online; a transação foi revertida.")
        return 1
    print("Linhas processadas: " + ", ".join(f"{nome}={total}" for nome, total in totais.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
