"""Diagnóstico somente leitura da prontidão de produção."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from scripts.auditar_integridade import (
    ErroConexaoPostgres, ErroLeituraFiscal, ErroSchemaFiscal, _causa_sql,
    carregar_csv_local, carregar_postgres_somente_leitura,
)
from scripts.importar_validacao_ncm import CAMINHO_VALIDACAO, ler_validacao
from scripts.sincronizar_ncm_oficial import CAMINHO_CACHE, ErroSincronizacao, carregar_cache
from src.auditor_integridade import auditar_integridade
from src.cobertura_fiscal import resumir_cobertura
from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.schema import TABELAS, ncm
from src.regressoes_fiscais import conferir_snapshot, conferir_snapshot_base


def verificar_schema(engine: Engine) -> dict[str, Any]:
    """Inspeciona schema, conta registros e consulta privilégios sem escrever."""

    resultado: dict[str, Any] = {"conexao": False, "schema": False, "operacao": False,
                                 "rastreabilidade": False, "contagens": {}, "permissoes": None,
                                 "ncms_banco": set()}
    with engine.connect() as conexao:
        if conexao.dialect.name == "postgresql":
            conexao.exec_driver_sql("SET TRANSACTION READ ONLY")
        resultado["conexao"] = conexao.execute(text("SELECT 1")).scalar_one() == 1
        try:
            inspetor = inspect(conexao)
        except SQLAlchemyError as exc:
            raise ErroSchemaFiscal(f"Inspeção do schema fiscal falhou: {_causa_sql(exc)}.") from exc
        existentes = {}
        colunas = {}
        for tabela in TABELAS.values():
            try:
                existentes[tabela.name] = inspetor.has_table(tabela.name)
                if existentes[tabela.name]:
                    colunas[tabela.name] = {c["name"] for c in inspetor.get_columns(tabela.name)}
            except SQLAlchemyError as exc:
                raise ErroSchemaFiscal(
                    f"Inspeção da tabela fiscal {tabela.name} falhou: {_causa_sql(exc)}."
                ) from exc
        resultado["tabelas"] = existentes
        resultado["colunas_faltantes"] = {
            tabela.name: sorted({c.name for c in tabela.columns} - colunas.get(tabela.name, set()))
            for tabela in TABELAS.values()
        }
        resultado["operacao"] = {"escopo_operacao", "cbenef"} <= colunas.get("beneficios", set())
        resultado["rastreabilidade"] = all(
            {"regra_consolidada_id", "evidencia_ncm_id"} <= colunas.get(nome, set())
            for nome in ("aliquotas", "beneficios"))
        resultado["schema"] = all(existentes.values()) and all(
            not faltantes for faltantes in resultado["colunas_faltantes"].values())
        for nome, tabela in TABELAS.items():
            if existentes[tabela.name]:
                try:
                    resultado["contagens"][nome] = conexao.execute(select(func.count()).select_from(tabela)).scalar_one()
                except SQLAlchemyError as exc:
                    raise ErroLeituraFiscal(
                        f"SELECT da tabela fiscal obrigatória {tabela.name} falhou: {_causa_sql(exc)}."
                    ) from exc
        if existentes["ncm"] and "ncm" in colunas["ncm"]:
            try:
                resultado["ncms_banco"] = set(conexao.execute(select(ncm.c.ncm)).scalars())
            except SQLAlchemyError as exc:
                raise ErroLeituraFiscal(f"SELECT da tabela fiscal obrigatória ncm falhou: {_causa_sql(exc)}.") from exc
        if conexao.dialect.name == "postgresql":
            try:
                resultado["permissoes"] = {
                    tabela.name: {privilegio: bool(conexao.execute(text(
                        "SELECT has_table_privilege(current_user, :tabela, :privilegio)"
                    ), {"tabela": tabela.name, "privilegio": privilegio}).scalar_one())
                                  for privilegio in ("SELECT", "INSERT", "UPDATE", "DELETE")}
                    for tabela in TABELAS.values() if existentes[tabela.name]
                }
            except SQLAlchemyError:
                resultado["permissoes"] = None
    return resultado


def verificar_prontidao() -> tuple[dict[str, str], list[str], dict[str, Any]]:
    """Retorna estados e bloqueadores; a execução não modifica o PostgreSQL."""

    estados: dict[str, str] = {}
    motivos: list[str] = []
    detalhes: dict[str, Any] = {}
    fonte = os.getenv("DATA_SOURCE", "").strip().lower()
    estados["Regressões PostgreSQL"] = "NÃO VERIFICADO"
    estados["DATA_SOURCE"] = "OK" if fonte == "postgres" else "PENDENTE"
    if fonte != "postgres":
        motivos.append("DATA_SOURCE deve ser postgres em produção.")

    try:
        preparados, rascunhos = ler_validacao(CAMINHO_VALIDACAO)
        casos, beneficios = conferir_snapshot(preparados)
        if (casos, beneficios, rascunhos) != (14, 4, 0):
            raise AssertionError("Quantidade de casos, benefícios ou rascunhos alterada.")
        estados["Regressões fiscais"] = f"OK ({casos} casos, {beneficios} benefícios)"
    except (AssertionError, KeyError, ValueError, OSError) as exc:
        estados["Regressões fiscais"] = "FALHA"
        motivos.append(f"Regressões fiscais locais falharam ({type(exc).__name__}).")
    try:
        local = carregar_csv_local(CAMINHO_VALIDACAO)
        detalhes["cobertura_local"] = resumir_cobertura(local)
    except (ValueError, OSError) as exc:
        motivos.append(f"Cobertura fiscal local indisponível ({type(exc).__name__}).")

    oficiais = None
    if not CAMINHO_CACHE.is_file():
        estados["Cache NCM"] = "AUSENTE"
        motivos.append("Cache de download oficial NCM ausente; validade oficial não verificável.")
    else:
        try:
            oficiais, _, metadados = carregar_cache()
            estados["Cache NCM"] = f"OK ({len(oficiais)} NCMs; download {metadados['download_em']})"
            detalhes["cache_data"] = metadados["download_em"]
        except (ErroSincronizacao, KeyError):
            estados["Cache NCM"] = "INVÁLIDO"
            motivos.append("Cache NCM oficial inválido.")

    if not os.getenv("DATABASE_URL"):
        estados["PostgreSQL"] = "PENDENTE (DATABASE_URL ausente)"
        motivos.append("DATABASE_URL não configurada; verificação de produção depende de conexão PostgreSQL.")
        for nome in ("Schema fiscal", "Migração operação/cBenef", "Migração rastreabilidade",
                     "Auditoria", "NCM oficial", "Permissões"):
            estados[nome] = "NÃO VERIFICADO"
        return estados, motivos, detalhes
    try:
        repo = criar_repositorio(data_source="postgres")
        banco = verificar_schema(repo.engine)
        estados["PostgreSQL"] = "OK" if banco["conexao"] else "FALHA"
        estados["Schema fiscal"] = "OK" if banco["schema"] else "PENDENTE"
        estados["Migração operação/cBenef"] = "OK" if banco["operacao"] else "PENDENTE"
        estados["Migração rastreabilidade"] = "OK" if banco["rastreabilidade"] else "PENDENTE"
        detalhes["contagens"] = banco["contagens"]
        if not banco["schema"]:
            motivos.append("Schema fiscal incompleto; verificar tabelas e colunas ausentes.")
            detalhes["colunas_faltantes"] = banco["colunas_faltantes"]
        if not banco["operacao"]:
            motivos.append("Migração operação/cBenef pendente.")
        if not banco["rastreabilidade"]:
            motivos.append("Migração rastreabilidade pendente.")
        if all(banco["tabelas"].values()):
            try:
                base, updater = carregar_postgres_somente_leitura(repo)
                try:
                    casos_banco, beneficios_banco = conferir_snapshot_base(base)
                    if (casos_banco, beneficios_banco) != (14, 4):
                        raise AssertionError("Quantidade de casos ou benefícios divergente.")
                    estados["Regressões PostgreSQL"] = f"OK ({casos_banco} casos, {beneficios_banco} benefícios)"
                except (AssertionError, KeyError, ValueError, OSError) as exc:
                    estados["Regressões PostgreSQL"] = "FALHA"
                    motivos.append(f"Regressões PostgreSQL falharam: {exc or type(exc).__name__}.")
                relatorio = auditar_integridade(base, catalogo_oficial=set(oficiais) if oficiais else None,
                                                updater=updater)
                niveis = relatorio.contagem_niveis()
                detalhes["auditoria"] = niveis
                detalhes["cobertura_banco"] = resumir_cobertura(base)
                estados["Auditoria"] = (
                    f"{'OK' if niveis['ERRO'] == 0 else 'FALHA'} "
                    f"({niveis['ERRO']} erros, {niveis['ALERTA']} alertas, {niveis['INFO']} informações)"
                )
                if niveis["ERRO"]:
                    motivos.append(f"Auditoria detectou {niveis['ERRO']} erro(s).")
                if relatorio.contagem_codigos().get("RASTREABILIDADE_NAO_VERIFICAVEL", 0):
                    motivos.append("Vínculos de rastreabilidade informados não puderam ser verificados.")
            except (ErroConexaoPostgres, ErroSchemaFiscal, ErroLeituraFiscal) as exc:
                estados["Auditoria"] = "FALHA"
                motivos.append(str(exc))
            except (SQLAlchemyError, ValueError, KeyError) as exc:
                estados["Auditoria"] = "FALHA"
                motivos.append(f"Auditoria fiscal não pôde ser concluída ({type(exc).__name__}).")
        else:
            estados["Auditoria"] = "NÃO VERIFICADO"
        if oficiais is None:
            estados["NCM oficial"] = "PENDENTE"
        else:
            banco_ncms = banco["ncms_banco"]
            divergentes = len(set(oficiais) ^ banco_ncms)
            estados["NCM oficial"] = ("OK (compatível com último cache; vigência não atestada)"
                                      if divergentes == 0 else f"PENDENTE ({divergentes} divergências)")
            if divergentes:
                motivos.append("Cadastro NCM diverge do último cache oficial validado.")
        permissoes = banco["permissoes"]
        if permissoes is None:
            estados["Permissões"] = "NÃO VERIFICADO"
            motivos.append("Privilégios do usuário público não puderam ser verificados.")
        else:
            somente_leitura = all(p["SELECT"] and not any(p[a] for a in ("INSERT", "UPDATE", "DELETE"))
                                  for p in permissoes.values()) and len(permissoes) == len(TABELAS)
            estados["Permissões"] = "OK (somente leitura)" if somente_leitura else "PENDENTE"
            if not somente_leitura:
                motivos.append("Credencial PostgreSQL deve ter SELECT e não ter INSERT/UPDATE/DELETE nas tabelas fiscais.")
            detalhes["permissoes"] = permissoes
    except ErroLeituraFiscal as exc:
        estados["PostgreSQL"] = "OK (conexão estabelecida)"
        estados["Auditoria"] = "FALHA"
        motivos.append(str(exc))
        for nome in ("Schema fiscal", "Migração operação/cBenef", "Migração rastreabilidade",
                     "NCM oficial", "Permissões"):
            estados.setdefault(nome, "NÃO VERIFICADO")
    except ErroSchemaFiscal as exc:
        estados["PostgreSQL"] = "OK (conexão estabelecida)"
        estados["Schema fiscal"] = "FALHA"
        motivos.append(str(exc))
        for nome in ("Migração operação/cBenef", "Migração rastreabilidade",
                     "Auditoria", "NCM oficial", "Permissões"):
            estados.setdefault(nome, "NÃO VERIFICADO")
    except (ErroConfiguracaoDados, SQLAlchemyError, OSError, ValueError, KeyError):
        estados["PostgreSQL"] = "FALHA"
        motivos.append("Conexão PostgreSQL ou configuração falhou; nenhuma conclusão sobre as tabelas foi obtida.")
        for nome in ("Schema fiscal", "Migração operação/cBenef", "Migração rastreabilidade",
                     "Auditoria", "NCM oficial", "Permissões"):
            estados.setdefault(nome, "NÃO VERIFICADO")
    return estados, motivos, detalhes


def main() -> int:
    estados, motivos, detalhes = verificar_prontidao()
    print("=== PRONTIDÃO PARA PRODUÇÃO ===")
    for nome, estado in estados.items():
        print(f"{nome:.<30} {estado}")
    if "contagens" in detalhes:
        print("\nRegistros PostgreSQL:")
        for nome, total in detalhes["contagens"].items():
            print(f"{nome}: {total}")
    for titulo, chave in (("Cobertura fiscal local", "cobertura_local"),
                          ("Cobertura fiscal PostgreSQL", "cobertura_banco")):
        if chave in detalhes:
            c = detalhes[chave]
            print(f"\n{titulo}:")
            print(f"NCMs cadastrados: {c['ncms_cadastrados']}")
            print(f"NCMs com alíquota: {c['ncms_com_aliquota']}")
            print(f"NCMs com benefício: {c['ncms_com_beneficio']}")
            print(f"NCM sem tratamento fiscal cadastrado na base: {c['ncms_sem_tratamento_cadastrado']}")
            print(f"Regras EXATO: {c['regras_exato']}; regras PREFIXO: {c['regras_prefixo']}")
    if "permissoes" in detalhes:
        print("\nPrivilégios PostgreSQL da credencial atual:")
        for tabela, permissoes in detalhes["permissoes"].items():
            print(tabela + ": " + ", ".join(
                f"{acao}={'SIM' if permitido else 'NAO'}" for acao, permitido in permissoes.items()))
    print("\nSTATUS FINAL: " + ("NÃO PRONTO" if motivos else "PRONTO"))
    if motivos:
        print("Motivos:")
        for motivo in motivos:
            print(f"- {motivo}")
    return 1 if motivos else 0


if __name__ == "__main__":
    raise SystemExit(main())
