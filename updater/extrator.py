"""Comando independente para a Fase 2, sobre atos já salvos no PostgreSQL."""

from __future__ import annotations

import argparse

from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository

from .extracao_fiscal import EXTRACTOR_VERSION, RegraExtraida, detectar_ncms, extrair_regras
from .repositorio_extracao import AtoParaExtrair, RepositorioExtracao


def _mostrar_regra(indice: int, regra: RegraExtraida) -> None:
    print(f"Regra {indice}:")
    print(f"  Tipo: {regra.tipo_regra}")
    print(f"  Ação: {regra.acao_legislativa}")
    print(f"  NCM: {regra.ncm_chave or 'não identificado'}")
    print(f"  NCM detectado: {'SIM' if regra.ncm_chave else 'NAO'}")
    if regra.ncm_original:
        print(f"  NCM original: {regra.ncm_original}")
        print(f"  NCM normalizado: {regra.ncm_normalizado}")
    if regra.descricao_proxima_ncm:
        print(f"  Descrição próxima ao NCM: {regra.descricao_proxima_ncm}")
    print(f"  Correspondência: {regra.tipo_correspondencia or 'não identificada'}")
    percentuais = [(nome, getattr(regra, nome)) for nome in (
        "aliquota_icms", "percentual_reducao_bc", "carga_efetiva", "credito_outorgado_percentual")
        if getattr(regra, nome) is not None]
    print("  Percentual: " + ("; ".join(f"{nome}={valor}%" for nome, valor in percentuais) or "não classificado"))
    dispositivo = ", ".join(f"{nome} {getattr(regra, nome)}" for nome in (
        "anexo", "artigo", "paragrafo", "inciso", "alinea", "item") if getattr(regra, nome))
    print(f"  Dispositivo: {dispositivo or 'não identificado'}")
    print(f"  Confiança: {regra.confianca}")
    print(f"  Escopo fiscal: {regra.escopo_fiscal}")
    print(f"  Elegível para consolidação: {regra.elegivel_consolidacao}")
    print(f"  Motivo: {regra.motivo_elegibilidade}")
    print(f"  Papel: {regra.papel_dispositivo}")
    print(f"  Grupo: {regra.grupo_regra_id or 'não vinculado'}")
    print(f"  Elegível para consulta NCM: {regra.elegivel_consulta_ncm}")
    print(f"  Status do vínculo NCM: {regra.status_vinculo_ncm}")
    print(f"  Motivo da consulta NCM: {regra.motivo_consulta_ncm}")
    if regra.alertas:
        print(f"  Alertas: {'; '.join(regra.alertas)}")
    print(f"  Trecho [{regra.inicio_trecho}:{regra.fim_trecho}]: {regra.trecho_origem}")


def _dispositivo(regra: RegraExtraida) -> str:
    partes = [f"Art. {regra.artigo}" if regra.artigo else None,
              f"§ {regra.paragrafo}" if regra.paragrafo else None,
              f"Inciso {regra.inciso}" if regra.inciso else None]
    return ", ".join(parte for parte in partes if parte) or f"trecho {regra.inicio_trecho}:{regra.fim_trecho}"


def _mostrar_grupos(identificacao: str, regras: list[RegraExtraida]) -> None:
    """Mostra principal e complementos preservando os trechos individuais."""

    for principal in (r for r in regras if r.papel_dispositivo == "REGRA_MATERIAL"
                      and r.elegivel_consolidacao == "SIM" and r.grupo_regra_id):
        print(f"BENEFÍCIO PRINCIPAL: {principal.tipo_regra}")
        print(f"ATO: {identificacao}")
        print(f"Dispositivo principal: {_dispositivo(principal)}")
        print(f"NCM: {principal.ncm_chave or 'não identificado'}")
        print("COMPLEMENTOS:")
        ligados = [r for r in regras if r.grupo_regra_id == principal.grupo_regra_id
                   and r is not principal and r.papel_dispositivo != "REGRA_MATERIAL"]
        for complemento in ligados:
            print(f"  {_dispositivo(complemento)} — {complemento.papel_dispositivo}")
        if not ligados:
            print("  nenhum identificado")


def executar(repo: RepositorioExtracao, *, ato_id: int | None = None, ano: int | None = None,
             limite: int = 10, relevancia: str = "ALTA", dry_run: bool = False) -> tuple[int, int, int]:
    """Extrai por versão; dry-run só lê e imprime, nunca abre transação de escrita."""

    atos: list[AtoParaExtrair] = repo.listar_atos(
        ano=ano, ato_id=ato_id, limite=limite, relevancia=relevancia)
    total_regras = 0
    ignorados = 0
    elegiveis = 0
    pauta = 0
    credito_procedimento = 0
    indeterminadas = 0
    fora_escopo = 0
    materiais = 0
    complementares = 0
    grupos: set[tuple[int, str]] = set()
    com_ncm = 0
    com_prefixo = 0
    mercadoria_sem_ncm = 0
    consulta_ncm = 0
    pendentes_vinculo = 0
    ncms_texto_completo = 0
    ncms_exatos = 0
    prefixos_texto_completo = 0
    ncms_materiais = 0
    ncms_procedimentais = 0
    ncms_nao_elegiveis = 0
    for ato in atos:
        print(f"ATO: {ato.identificacao} (ID {ato.id}, versão {ato.versao_id})")
        print(f"Fonte: {ato.url_oficial}")
        ja_processado = repo.processado(ato.versao_id, EXTRACTOR_VERSION)
        if ja_processado and not dry_run:
            print(f"Versão {ato.versao_id} já processada pelo extrator {EXTRACTOR_VERSION}.")
            ignorados += 1
            continue
        if ja_processado:
            print("Versão já processada; reavaliando somente para exibição no dry-run.")
        deteccoes = detectar_ncms(ato.texto_limpo, ato.texto_original)
        regras = extrair_regras(ato.texto_limpo, ato.texto_original)
        print(f"Regras candidatas: {len(regras)}")
        for indice, regra in enumerate(regras, 1):
            _mostrar_regra(indice, regra)
        _mostrar_grupos(ato.identificacao, regras)
        if not dry_run:
            gravadas, erros = repo.salvar(ato, regras)
            print(f"Regras gravadas: {gravadas}")
            for erro in erros:
                print(f"Erro de extração: {erro}")
        total_regras += len(regras)
        elegiveis += sum(r.elegivel_consolidacao == "SIM" for r in regras)
        pauta += sum(r.escopo_fiscal == "PAUTA_PRECO" for r in regras)
        credito_procedimento += sum(r.escopo_fiscal in {"CREDITO_TRIBUTARIO", "PROCEDIMENTO"} for r in regras)
        indeterminadas += sum(r.escopo_fiscal == "INDETERMINADO" for r in regras)
        fora_escopo += sum(r.escopo_fiscal not in {"ALIQUOTA_BENEFICIO", "INDETERMINADO"} for r in regras)
        materiais += sum(r.papel_dispositivo == "REGRA_MATERIAL" and r.elegivel_consolidacao == "SIM" for r in regras)
        complementares += sum(r.papel_dispositivo not in {"REGRA_MATERIAL", "INDETERMINADO"} for r in regras)
        grupos.update((ato.id, r.grupo_regra_id) for r in regras if r.grupo_regra_id
                      and r.papel_dispositivo == "REGRA_MATERIAL")
        com_ncm += sum(r.status_vinculo_ncm == "NCM_EXPLICITO" for r in regras)
        com_prefixo += sum(r.status_vinculo_ncm == "NCM_EXPLICITO"
                           and r.tipo_correspondencia == "PREFIXO" for r in regras)
        mercadoria_sem_ncm += sum(r.status_vinculo_ncm == "PENDENTE_VINCULO_NCM" for r in regras)
        consulta_ncm += sum(r.elegivel_consulta_ncm == "SIM" for r in regras)
        pendentes_vinculo += sum(r.status_vinculo_ncm == "PENDENTE_VINCULO_NCM" for r in regras)
        ncms_texto_completo += len(deteccoes)
        ncms_exatos += sum(d.tipo_correspondencia == "EXATO" for d in deteccoes)
        prefixos_texto_completo += sum(d.tipo_correspondencia == "PREFIXO" for d in deteccoes)
        for deteccao in deteccoes:
            vinculadas = [r for r in regras if any(
                e.tipo_evidencia == "NCM" and
                (e.posicao_inicio, e.posicao_fim) == (deteccao.inicio, deteccao.fim)
                for e in r.evidencias)]
            ncms_materiais += any(r.papel_dispositivo == "REGRA_MATERIAL" and
                                  r.elegivel_consolidacao == "SIM" for r in vinculadas)
            ncms_procedimentais += any(r.papel_dispositivo == "PROCEDIMENTO" or
                                       r.escopo_fiscal == "PROCEDIMENTO" for r in vinculadas)
            ncms_nao_elegiveis += not any(r.elegivel_consulta_ncm == "SIM" for r in vinculadas)
    print(f"Atos selecionados: {len(atos)}")
    print(f"Atos já processados: {ignorados}")
    print(f"Regras candidatas encontradas: {total_regras}")
    print(f"Regras detectadas: {total_regras}")
    print(f"Regras elegíveis para consolidação: {elegiveis}")
    print(f"Regras fora do escopo: {fora_escopo}")
    print(f"Pauta de preços: {pauta}")
    print(f"Crédito tributário/procedimento: {credito_procedimento}")
    print(f"Regras indeterminadas: {indeterminadas}")
    print(f"Regras materiais: {materiais}")
    print(f"Dispositivos complementares: {complementares}")
    print(f"Grupos NCM com complementos: {len(grupos)}")
    print(f"Regras com NCM explícito: {com_ncm}")
    print(f"Regras com prefixo NCM: {com_prefixo}")
    print(f"Regras com mercadoria sem NCM: {mercadoria_sem_ncm}")
    print(f"Regras elegíveis para consulta NCM: {consulta_ncm}")
    print(f"Regras pendentes de vínculo NCM: {pendentes_vinculo}")
    print(f"Regras fora do escopo NCM: {total_regras - consulta_ncm - pendentes_vinculo}")
    print(f"NCMs encontrados no texto completo: {ncms_texto_completo}")
    print(f"NCMs exatos encontrados: {ncms_exatos}")
    print(f"Prefixos NCM encontrados: {prefixos_texto_completo}")
    print(f"NCMs em regras materiais: {ncms_materiais}")
    print(f"NCMs em dispositivos procedimentais: {ncms_procedimentais}")
    print(f"NCMs detectados mas não elegíveis: {ncms_nao_elegiveis}")
    if dry_run:
        print("DRY-RUN: nenhuma escrita no PostgreSQL.")
    return len(atos), total_regras, ignorados


def main() -> int:
    parser = argparse.ArgumentParser(description="Extrai candidatos fiscais de atos já coletados.")
    parser.add_argument("--ato-id", type=int, help="ID do ato armazenado")
    parser.add_argument("--ano", type=int, help="Ano do ato")
    parser.add_argument("--limite", type=int, default=10, help="Máximo de atos")
    parser.add_argument("--relevancia", choices=("ALTA", "MEDIA"), default="ALTA")
    parser.add_argument("--dry-run", action="store_true", help="Somente leitura; mostra todas as regras candidatas")
    args = parser.parse_args()
    if args.limite < 1 or args.ato_id is not None and args.ato_id < 1:
        parser.error("--limite e --ato-id devem ser maiores que zero.")
    if args.ano is not None and not 1800 <= args.ano <= 9999:
        parser.error("--ano deve conter quatro dígitos válidos.")
    try:
        dados = criar_repositorio(data_source="postgres")
        assert isinstance(dados, PostgresRepository)
        executar(RepositorioExtracao(dados.engine), ato_id=args.ato_id, ano=args.ano,
                 limite=args.limite, relevancia=args.relevancia, dry_run=args.dry_run)
    except ErroConfiguracaoDados as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError):
        print("Não foi possível ler a base de monitoramento PostgreSQL. Verifique o schema e a conexão.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
