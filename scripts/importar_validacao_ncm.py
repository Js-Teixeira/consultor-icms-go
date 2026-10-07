"""Carga pequena e revisada das quatro tabelas fiscais, a partir de CSV."""

from __future__ import annotations

import argparse
import csv
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from scripts.importar_excel_postgres import ErroImportacao, _normalizar_linha, validar_rastreabilidade
from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.schema import TABELAS

CAMINHO_VALIDACAO = Path(__file__).resolve().parents[1] / "base" / "validacao_ncm.csv"
TIPOS = {"NCM": "NCM", "LEGISLACAO": "Legislacao", "ALIQUOTA": "Aliquotas", "BENEFICIO": "Beneficios"}
COLUNAS = {"tipo_registro"} | {col.name for tabela in TABELAS.values() for col in tabela.columns}
PERCENTUAIS = {"aliquota_icms", "adicional_percentual", "percentual_reducao_bc", "carga_efetiva", "credito_outorgado_percentual"}


def _obrigatorio(registro: dict, campo: str, tipo: str, numero: int) -> None:
    if registro.get(campo) is None or str(registro[campo]).strip() == "":
        raise ErroImportacao(f"{tipo}, linha {numero}: {campo} é obrigatório.")


def ler_validacao(caminho: Path = CAMINHO_VALIDACAO) -> tuple[dict[str, list[dict]], int]:
    """Valida o arquivo inteiro antes de abrir uma transação de escrita."""

    preparados = {nome: [] for nome in TABELAS}
    vistos = {nome: set() for nome in TABELAS}
    ncms_rascunho: set[str] = set()
    rascunhos = 0
    try:
        arquivo = caminho.open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ErroImportacao(f"CSV de validação indisponível: {caminho}") from exc
    with arquivo:
        leitor = csv.DictReader(arquivo)
        if not leitor.fieldnames or "tipo_registro" not in leitor.fieldnames:
            raise ErroImportacao("CSV sem coluna tipo_registro.")
        desconhecidas = set(leitor.fieldnames) - COLUNAS
        if desconhecidas:
            raise ErroImportacao(f"Colunas desconhecidas: {', '.join(sorted(desconhecidas))}.")
        for numero, linha in enumerate(leitor, 2):
            if None in linha:
                raise ErroImportacao(f"Linha {numero}: número de colunas maior que o cabeçalho.")
            tipo = (linha.get("tipo_registro") or "").strip().upper()
            if tipo == "RASCUNHO":
                ncm = (linha.get("ncm") or "").strip()
                if not re.fullmatch(r"[0-9]{8}", ncm) or any(
                    str(valor or "").strip() for campo, valor in linha.items()
                    if campo not in {"tipo_registro", "ncm"}
                ):
                    raise ErroImportacao(f"Rascunho inválido na linha {numero}: mantenha apenas o NCM de 8 dígitos.")
                if ncm in ncms_rascunho or ncm in vistos["NCM"]:
                    raise ErroImportacao(f"Rascunho duplicado na linha {numero}: {ncm}.")
                ncms_rascunho.add(ncm)
                rascunhos += 1
                continue
            if tipo not in TIPOS:
                raise ErroImportacao(f"Tipo de registro inválido na linha {numero}.")
            nome = TIPOS[tipo]
            tabela = TABELAS[nome]
            registro = _normalizar_linha(nome, tabela, pd.Series(linha), numero)
            chave = next(iter(tabela.primary_key.columns)).name
            if registro[chave] in vistos[nome]:
                raise ErroImportacao(f"{nome}, linha {numero}: {chave} duplicado no CSV.")
            if nome == "NCM" and registro[chave] in ncms_rascunho:
                raise ErroImportacao(f"NCM, linha {numero}: remova o rascunho duplicado antes de validar.")
            vistos[nome].add(registro[chave])
            permitidas = {col.name for col in tabela.columns} | {"tipo_registro"}
            if any(str(valor or "").strip() for campo, valor in linha.items() if campo not in permitidas):
                raise ErroImportacao(f"{nome}, linha {numero}: há campos de outra tabela preenchidos.")
            if nome == "NCM":
                _obrigatorio(registro, "descricao_oficial", nome, numero)
            if nome == "Legislacao":
                for campo in ("norma", "texto_relevante", "url_fonte"):
                    _obrigatorio(registro, campo, nome, numero)
                url = urlparse(registro["url_fonte"])
                host = (url.hostname or "").lower()
                if url.scheme != "https" or not (host == "gov.br" or host.endswith(".gov.br")):
                    raise ErroImportacao(f"Legislacao, linha {numero}: url_fonte deve apontar para HTTPS oficial .gov.br.")
            if nome in {"Aliquotas", "Beneficios"}:
                _obrigatorio(registro, "id_legislacao", nome, numero)
                if registro["exige_descricao"] == "SIM" and not (registro.get("descricao_regra") or registro.get("palavras_chave")):
                    raise ErroImportacao(f"{nome}, linha {numero}: regra que exige descrição precisa de texto ou palavras-chave.")
                if nome == "Aliquotas":
                    _obrigatorio(registro, "aliquota_icms", nome, numero)
                else:
                    _obrigatorio(registro, "tipo_beneficio", nome, numero)
                    if registro["aplicacao"] == "ALTERNATIVO":
                        _obrigatorio(registro, "grupo_beneficio", nome, numero)
            inicio, fim = registro.get("vigencia_inicio"), registro.get("vigencia_fim")
            if inicio and fim and inicio > fim:
                raise ErroImportacao(f"{nome}, linha {numero}: vigência inicial posterior à final.")
            for campo in PERCENTUAIS & registro.keys():
                valor = registro[campo]
                if valor is not None and (valor < Decimal("0") or valor > Decimal("100")):
                    raise ErroImportacao(f"{nome}, linha {numero}: {campo} deve estar em pontos percentuais entre 0 e 100.")
            preparados[nome].append(registro)
    return preparados, rascunhos


def importar_validacao(preparados: dict[str, list[dict]], repositorio, *, dry_run: bool,
                       confirmar_atualizacao: bool, relatorio: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Planeja e executa inserts/updates sob a mesma transação."""

    totais = {nome: {"inserir": 0, "atualizar": 0, "iguais": 0} for nome in TABELAS}
    with repositorio.engine.begin() as conexao:
        validar_rastreabilidade(conexao, preparados)
        existentes = {}
        for nome, tabela in TABELAS.items():
            chave = next(iter(tabela.primary_key.columns)).name
            ids = [registro[chave] for registro in preparados[nome]]
            existentes[nome] = (
                {linha[chave]: dict(linha) for linha in conexao.execute(select(tabela).where(tabela.c[chave].in_(ids))).mappings()}
                if ids else {}
            )
        legais_carga = {r["id_legislacao"]: r for r in preparados["Legislacao"]}
        ncms_carga = {r["ncm"]: r for r in preparados["NCM"]}
        for nome in ("Aliquotas", "Beneficios"):
            for registro in preparados[nome]:
                legal = registro["id_legislacao"]
                fundamento = legais_carga.get(legal)
                if fundamento is None:
                    linha = conexao.execute(select(TABELAS["Legislacao"]).where(TABELAS["Legislacao"].c.id_legislacao == legal)).mappings().first()
                    fundamento = dict(linha) if linha else None
                if not fundamento or fundamento["ativo"] != "SIM" or not all(fundamento.get(c) for c in ("norma", "texto_relevante", "url_fonte")):
                    raise ErroImportacao(f"{nome}: fundamento {legal} ativo e completo não consta na carga nem no banco.")
                chave_ncm = registro["chave_ncm"]
                if registro["tipo_correspondencia"] == "EXATO":
                    ncm = ncms_carga.get(chave_ncm)
                    if ncm is None:
                        linha = conexao.execute(select(TABELAS["NCM"]).where(TABELAS["NCM"].c.ncm == chave_ncm)).mappings().first()
                        ncm = dict(linha) if linha else None
                    if not ncm or ncm["ativo"] != "SIM" or not ncm.get("descricao_oficial"):
                        raise ErroImportacao(f"{nome}: NCM {chave_ncm} ativo e descrito não consta na carga nem no banco.")
                elif not any(n.startswith(chave_ncm) and r["ativo"] == "SIM" for n, r in ncms_carga.items()):
                    existe = conexao.execute(select(TABELAS["NCM"].c.ncm).where(
                        TABELAS["NCM"].c.ncm.like(chave_ncm + "%"), TABELAS["NCM"].c.ativo == "SIM"
                    ).limit(1)).scalar_one_or_none()
                    if existe is None:
                        raise ErroImportacao(f"{nome}: prefixo {chave_ncm} sem NCM ativo cadastrado.")
        plano = []
        for nome, tabela in TABELAS.items():
            chave = next(iter(tabela.primary_key.columns)).name
            for registro in preparados[nome]:
                atual = existentes[nome].get(registro[chave])
                # Células vazias não apagam metadados de um registro já existente.
                desejado = ({**atual, **{campo: valor for campo, valor in registro.items() if valor is not None}}
                            if atual is not None else registro)
                if atual is None:
                    acao = "inserir"
                elif all(atual.get(campo) == valor for campo, valor in desejado.items()):
                    acao = "iguais"
                elif confirmar_atualizacao:
                    acao = "atualizar"
                else:
                    raise ErroImportacao(f"{nome}: {registro[chave]} já existe com dados diferentes; use --confirmar-atualizacao após revisar.")
                totais[nome][acao] += 1
                if acao != "iguais" and relatorio is not None:
                    relatorio.append(f"{acao.upper()}: {nome} {registro[chave]}")
                plano.append((acao, tabela, chave, desejado))
        if not dry_run:
            for acao, tabela, chave, registro in plano:
                if acao == "inserir":
                    conexao.execute(tabela.insert().values(**registro))
                elif acao == "atualizar":
                    conexao.execute(tabela.update().where(tabela.c[chave] == registro[chave]).values(**registro))
    return totais


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida e importa uma pequena carga fiscal revisada.")
    parser.add_argument("--arquivo", type=Path, default=CAMINHO_VALIDACAO)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirmar-atualizacao", action="store_true")
    args = parser.parse_args()
    try:
        preparados, rascunhos = ler_validacao(args.arquivo)
        if not any(preparados.values()):
            print(f"{rascunhos} rascunhos; nenhuma linha fiscal validada para importar.")
            return 0
        repositorio = criar_repositorio(data_source="postgres")
        relatorio: list[str] = []
        totais = importar_validacao(preparados, repositorio, dry_run=args.dry_run,
                                   confirmar_atualizacao=args.confirmar_atualizacao,
                                   relatorio=relatorio)
    except (ErroImportacao, ErroConfiguracaoDados) as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError):
        print("Falha na base PostgreSQL; a transação foi revertida.")
        return 1
    print(("DRY-RUN" if args.dry_run else "Carga concluída") + f"; rascunhos ignorados: {rascunhos}.")
    for nome, contagem in totais.items():
        print(f"{nome}: " + ", ".join(f"{acao}={total}" for acao, total in contagem.items()))
    for detalhe in relatorio:
        print(detalhe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
