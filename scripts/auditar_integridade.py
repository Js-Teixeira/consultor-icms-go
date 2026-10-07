"""CLI de auditoria somente leitura das quatro tabelas fiscais."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from scripts.sincronizar_ncm_oficial import CAMINHO_CACHE, ErroSincronizacao, carregar_cache
from src.auditor_integridade import ADMINISTRATIVO_NAO_VERIFICADO, Relatorio, auditar_integridade
from src.carregamento import CAMINHO_BASE
from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.excel_repository import ExcelRepository
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import TABELAS
from src.modelos import BaseTributaria
from updater.schema import evidencias_extracao, regras_consolidadas, regras_extraidas

CSV_TABELAS = {"NCM": "NCM", "ALIQUOTA": "Aliquotas", "BENEFICIO": "Beneficios",
               "LEGISLACAO": "Legislacao"}


class ErroConexaoPostgres(RuntimeError):
    """Não foi possível iniciar a leitura PostgreSQL."""


class ErroSchemaFiscal(RuntimeError):
    """Tabela ou chave fiscal obrigatória ausente/inacessível no catálogo."""


class ErroLeituraFiscal(RuntimeError):
    """SELECT de uma das quatro tabelas fiscais obrigatórias falhou."""


def _causa_sql(exc: SQLAlchemyError) -> str:
    """Explica a categoria SQL sem imprimir parâmetros nem credenciais."""

    origem = getattr(exc, "orig", None)
    sqlstate = getattr(origem, "sqlstate", None) or getattr(origem, "pgcode", None)
    if sqlstate == "42501":
        return "permissão SELECT negada (SQLSTATE 42501)"
    return f"{type(exc).__name__}" + (f" (SQLSTATE {sqlstate})" if sqlstate else "")


def carregar_csv_local(caminho: Path) -> BaseTributaria:
    """Lê registros brutos para também encontrar erros que o importador recusaria."""

    grupos: dict[str, list[dict[str, str]]] = {nome: [] for nome in TABELAS}
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        if not leitor.fieldnames or "tipo_registro" not in leitor.fieldnames:
            raise ValueError("CSV sem coluna tipo_registro.")
        for numero, registro in enumerate(leitor, 2):
            tipo = (registro.get("tipo_registro") or "").strip().upper()
            if tipo == "RASCUNHO":
                continue
            if tipo not in CSV_TABELAS:
                raise ValueError(f"Tipo de registro inválido na linha {numero}.")
            grupos[CSV_TABELAS[tipo]].append(registro)
    return BaseTributaria(pd.DataFrame(grupos["NCM"]), pd.DataFrame(grupos["Aliquotas"]),
                          pd.DataFrame(grupos["Beneficios"]), pd.DataFrame(grupos["Legislacao"]))


def carregar_excel_local(caminho: Path) -> BaseTributaria:
    """Lê abas sem validação prévia para poder relatar defeitos estruturais."""

    abas = pd.read_excel(caminho, sheet_name=list(TABELAS), dtype=object, engine="openpyxl")
    return BaseTributaria(abas["NCM"].dropna(how="all"), abas["Aliquotas"].dropna(how="all"),
                          abas["Beneficios"].dropna(how="all"), abas["Legislacao"].dropna(how="all"))


def _carregar_updater_opcional(engine) -> dict[str, list[dict]]:
    """Consulta estruturas administrativas em transação separada da leitura fiscal."""

    tabelas = (regras_consolidadas, regras_extraidas, evidencias_extracao)
    pendentes: list[dict[str, str]] = []
    updater: dict[str, list[dict]] = {}
    atual = tabelas[0].name
    try:
        with engine.connect() as conexao:
            if conexao.dialect.name == "postgresql":
                conexao.exec_driver_sql("SET TRANSACTION READ ONLY")
            inspetor = inspect(conexao)
            for tabela in tabelas:
                atual = tabela.name
                if not inspetor.has_table(atual):
                    pendentes.append({"tabela": atual, "causa": "tabela administrativa ausente"})
                elif conexao.dialect.name == "postgresql" and not conexao.execute(text(
                    "SELECT has_table_privilege(current_user, :tabela, 'SELECT')"
                ), {"tabela": atual}).scalar_one():
                    pendentes.append({"tabela": atual, "causa": "SELECT não permitido"})
            if pendentes:
                return {ADMINISTRATIVO_NAO_VERIFICADO: pendentes}
            for tabela in tabelas:
                atual = tabela.name
                updater[atual] = [dict(linha) for linha in conexao.execute(select(tabela)).mappings()]
    except SQLAlchemyError as exc:
        return {ADMINISTRATIVO_NAO_VERIFICADO: [{"tabela": atual, "causa": _causa_sql(exc)}]}
    return updater


def carregar_postgres_somente_leitura(repositorio: PostgresRepository) -> tuple[BaseTributaria, dict[str, list[dict]]]:
    """Lê quatro tabelas fiscais obrigatórias; updater é administrativo e opcional."""

    dados = {}
    try:
        with repositorio.engine.connect() as conexao:
            if conexao.dialect.name == "postgresql":
                conexao.exec_driver_sql("SET TRANSACTION READ ONLY")
            try:
                inspetor = inspect(conexao)
            except SQLAlchemyError as exc:
                raise ErroSchemaFiscal(f"Inspeção do schema fiscal falhou: {_causa_sql(exc)}.") from exc
            for nome, tabela in TABELAS.items():
                try:
                    if not inspetor.has_table(tabela.name):
                        raise ErroSchemaFiscal(f"Tabela fiscal obrigatória {tabela.name} não encontrada.")
                    existentes = {coluna["name"] for coluna in inspetor.get_columns(tabela.name)}
                except SQLAlchemyError as exc:
                    raise ErroSchemaFiscal(
                        f"Inspeção da tabela fiscal {tabela.name} falhou: {_causa_sql(exc)}."
                    ) from exc
                chave = next(iter(tabela.primary_key.columns)).name
                if chave not in existentes:
                    raise ErroSchemaFiscal(f"Tabela fiscal {tabela.name} sem chave esperada {chave}.")
                colunas = [coluna for coluna in tabela.columns if coluna.name in existentes]
                try:
                    linhas = [dict(linha) for linha in conexao.execute(select(*colunas)).mappings()]
                except SQLAlchemyError as exc:
                    raise ErroLeituraFiscal(
                        f"SELECT da tabela fiscal obrigatória {tabela.name} falhou: {_causa_sql(exc)}."
                    ) from exc
                dados[nome] = pd.DataFrame.from_records(linhas, columns=[coluna.name for coluna in tabela.columns])
    except SQLAlchemyError as exc:
        raise ErroConexaoPostgres(f"Conexão ou transação de leitura falhou: {_causa_sql(exc)}.") from exc
    base = BaseTributaria(dados["NCM"], dados["Aliquotas"], dados["Beneficios"], dados["Legislacao"])
    return base, _carregar_updater_opcional(repositorio.engine)


def _catalogo_oficial_local() -> set[str] | None:
    if not CAMINHO_CACHE.is_file():
        return None
    try:
        oficiais, _, _ = carregar_cache()
    except ErroSincronizacao:
        return None
    return set(oficiais)


def mostrar_relatorio(relatorio: Relatorio, *, formato_json: bool = False) -> None:
    if formato_json:
        print(json.dumps(relatorio.para_dict(), ensure_ascii=False, indent=2, default=str))
        return
    print("=== AUDITORIA DE INTEGRIDADE ===")
    for tabela, rotulo in (("ncm", "NCMs"), ("aliquotas", "Alíquotas"),
                          ("beneficios", "Benefícios"), ("legislacao", "Legislações")):
        print(f"{rotulo}: {relatorio.totais_tabelas[tabela]}")
    print()
    for nivel, rotulo in (("ERRO", "ERROS"), ("ALERTA", "ALERTAS"), ("INFO", "INFO")):
        print(f"{rotulo}: {relatorio.contagem_niveis()[nivel]}")
    print("\nPor código:")
    for codigo, quantidade in relatorio.contagem_codigos().items():
        print(f"{codigo}: {quantidade}")
    if relatorio.ocorrencias:
        print("\nExemplos (até 10):")
        for ocorrencia in relatorio.ocorrencias[:10]:
            print(f"{ocorrencia.nivel} {ocorrencia.codigo} | {ocorrencia.tabela} "
                  f"{ocorrencia.id_registro} | {ocorrencia.mensagem}")
    administrativa = next((o for o in relatorio.ocorrencias
                           if o.codigo == "RASTREABILIDADE_ADMINISTRATIVA_NAO_VERIFICADA"), None)
    if administrativa:
        if administrativa not in relatorio.ocorrencias[:10]:
            print(f"INFO {administrativa.codigo} | {administrativa.mensagem}")
        estruturas = administrativa.detalhes.get("estruturas", [])
        if estruturas:
            print("Estruturas administrativas: " + "; ".join(
                f"{item['tabela']} ({item['causa']})" for item in estruturas))
    print("\nLacunas técnicas:")
    for lacuna in relatorio.lacunas:
        print(lacuna)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita integridade sem alterar dados fiscais.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--arquivo-csv", type=Path, help="Audita CSV local sem acessar banco")
    grupo.add_argument("--arquivo-excel", type=Path, help="Audita Excel local sem acessar banco")
    parser.add_argument("--json", action="store_true", help="Mostra relatório estruturado em JSON")
    args = parser.parse_args()
    try:
        updater = None
        if args.arquivo_csv:
            base = carregar_csv_local(args.arquivo_csv)
        elif args.arquivo_excel:
            base = carregar_excel_local(args.arquivo_excel)
        else:
            repositorio = criar_repositorio()
            if isinstance(repositorio, ExcelRepository):
                base = carregar_excel_local(repositorio.caminho or CAMINHO_BASE)
            elif isinstance(repositorio, PostgresRepository):
                base, updater = carregar_postgres_somente_leitura(repositorio)
            else:
                raise ValueError("Fonte de dados não suportada pelo auditor.")
        relatorio = auditar_integridade(base, catalogo_oficial=_catalogo_oficial_local(), updater=updater)
    except (ErroConexaoPostgres, ErroSchemaFiscal, ErroLeituraFiscal) as exc:
        print(f"Não foi possível concluir a auditoria fiscal: {exc}")
        return 2
    except ErroConfiguracaoDados as exc:
        print(f"Configuração da fonte de dados inválida: {exc}")
        return 2
    except SQLAlchemyError as exc:
        print(f"Falha SQL inesperada na auditoria: {_causa_sql(exc)}.")
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"Não foi possível concluir a auditoria: {type(exc).__name__}: {exc}")
        return 2
    mostrar_relatorio(relatorio, formato_json=args.json)
    return 1 if relatorio.contagem_niveis()["ERRO"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
