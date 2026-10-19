"""Planos fiscais sintéticos; nenhum teste deste módulo abre conexão."""

from datetime import date
from decimal import Decimal
import json

import pytest

from updater.consolidacao import CONSOLIDATOR_VERSION
from updater.propostas_publicacao import planejar_revisao, simular_publicacao


def evidencias(origem=12, ncm="1234.56.78"):
    return [
        {"id": 22, "regra_extraida_id": origem, "tipo_evidencia": "NCM",
         "valor_extraido": ncm, "texto_origem": f"NCM {ncm}"},
        {"id": 25, "regra_extraida_id": origem, "tipo_evidencia": "ALIQUOTA",
         "valor_extraido": "8,5", "texto_origem": "Alíquota 8,5%"},
        {"id": 26, "regra_extraida_id": origem, "tipo_evidencia": "ARTIGO",
         "valor_extraido": "3", "texto_origem": "Art. 3"},
        {"id": 29, "regra_extraida_id": origem, "tipo_evidencia": "INCISO",
         "valor_extraido": "II", "texto_origem": "Inciso II"},
        {"id": 27, "regra_extraida_id": origem, "tipo_evidencia": "VIGENCIA",
         "valor_extraido": "2025-02-01", "texto_origem": "a partir de 2025-02-01"},
        {"id": 30, "regra_extraida_id": origem, "tipo_evidencia": "VIGENCIA",
         "valor_extraido": "2028-12-31", "texto_origem": "até 2028-12-31"},
        {"id": 28, "regra_extraida_id": origem, "tipo_evidencia": "CONDICAO",
         "valor_extraido": "Somente na operação descrita no ato fictício",
         "texto_origem": "Somente na operação descrita no ato fictício"},
    ]


def proposta(**alteracoes):
    dados = {
        # Marcador exclusivo de teste: a proposta nunca representa aprovação fiscal real.
        "id": 41, "origem_sintetica": True, "status_validacao": "PENDENTE",
        "status_regra": "VIGENTE", "consolidador_versao": CONSOLIDATOR_VERSION,
        "fonte_atual": True, "fonte_verificada": True, "cadeia_origem_valida": True,
        "tipo_regra": "ALIQUOTA", "regra_origem_id": 12, "ato_origem_id": 7,
        "ncm_chave": "12345678", "tipo_correspondencia": "EXATO",
        "aliquota_icms": Decimal("8.5"), "descricao_legal": "Produto sintético condicionado",
        "tipo_ato": "LEI", "numero": "999", "ano": 2025,
        "norma_base": "Lei 999/2025", "artigo": "3", "inciso": "II",
        "url_texto_oficial": "https://goias.gov.br/ato-ficticio",
        "vigencia_inicio": date(2025, 2, 1), "vigencia_fim": date(2028, 12, 31),
        "condicoes_texto": "Somente na operação descrita no ato fictício",
        "evidencias": evidencias(),
    }
    dados.update(alteracoes)
    return dados


def test_revisao_exige_responsavel_justificativa_e_estado_pendente():
    pendente = proposta(status_validacao="PENDENTE")
    decisao = planejar_revisao(pendente, "APROVAR", responsavel="Fiscal de teste",
                              justificativa="Dispositivo sintético conferido", data=date(2025, 2, 2))
    assert decisao["situacao_simulada"] == "APROVACAO_SIMULADA"
    assert "status_validacao" not in decisao
    assert pendente["status_validacao"] == "PENDENTE"
    rejeicao = planejar_revisao(pendente, "REJEITAR", responsavel="Fiscal de teste",
                               justificativa="Vigência ambígua", data=date(2025, 2, 2))
    assert rejeicao["situacao_simulada"] == "REJEICAO_SIMULADA"
    for anterior, responsavel, justificativa in (("VALIDADA", "Fiscal", "Motivo"),
                                                  ("PENDENTE", "", "Motivo"),
                                                  ("PENDENTE", "Fiscal", "")):
        with pytest.raises(ValueError):
            planejar_revisao(proposta(status_validacao=anterior), "APROVAR",
                            responsavel=responsavel, justificativa=justificativa,
                            data=date(2025, 2, 2))
    with pytest.raises(ValueError, match="não apta"):
        planejar_revisao(proposta(status_validacao="PENDENTE", status_regra="CONFLITO"),
                        "APROVAR", responsavel="Fiscal de teste", justificativa="Motivo",
                        data=date(2025, 2, 2))
    with pytest.raises(ValueError, match="não apta"):
        planejar_revisao(proposta(status_validacao="PENDENTE", url_texto_oficial="https://invalid.example"),
                        "APROVAR", responsavel="Fiscal de teste", justificativa="Motivo",
                        data=date(2025, 2, 2))


def test_simulacao_para_revisao_traz_duas_linhas_inativas_e_rastreaveis():
    plano = simular_publicacao([proposta()])
    assert len(plano.para_revisao) == 1
    registro = plano.para_revisao[0]
    assert registro.legislacao["url_fonte"] == "https://goias.gov.br/ato-ficticio"
    assert registro.legislacao["data_verificacao"] is None
    assert registro.legislacao["ativo"] == registro.aliquota["ativo"] == "NAO"
    assert registro.origem_sintetica is True
    assert registro.aliquota["aliquota_icms"] == Decimal("8.5")
    assert registro.aliquota["regra_consolidada_id"] == 41
    assert registro.aliquota["evidencia_ncm_id"] == 22
    assert registro.aliquota["exige_descricao"] == "SIM"
    assert "operação descrita" in registro.aliquota["observacao"]
    assert registro.aliquota["vigencia_fim"] == date(2028, 12, 31)


@pytest.mark.parametrize("alteracoes", [
    {"status_validacao": "DESCARTADA"},
    {"status_regra": "CONFLITO"}, {"status_regra": "REVOGADA"},
    {"tipo_regra": "ISENCAO"}, {"alertas": "Condição não resolvida"},
    {"norma_base": "Outra norma"}, {"url_texto_oficial": "https://exemplo.invalid/ato"},
    {"artigo": None, "inciso": None},
    {"evidencias": []}, {"vigencia_inicio": None},
    {"evidencias": evidencias()[:1]},
    {"aliquota_icms": Decimal("9")},
    {"evidencias": evidencias()[:-1], "complementos_json": "[]"},
    {"vigencia_inicio": date(2030, 1, 1)},
    {"vigencia_fim": date(2025, 12, 31)},
    {"status_regra": "FUTURA"},
    {"aliquota_icms": Decimal("101")},
])
def test_simulacao_bloqueia_proposta_sem_requisitos(alteracoes):
    plano = simular_publicacao([proposta(**alteracoes)])
    assert not plano.para_revisao
    assert plano.bloqueadas[0]["motivos"]


def test_prefixo_sem_condicao_ainda_exige_validacao_da_mercadoria():
    plano = simular_publicacao([proposta(ncm_chave="1234", tipo_correspondencia="PREFIXO",
                                        condicoes_texto=None,
                                        evidencias=[dict(evidencias()[0], id=23, valor_extraido="1234",
                                                        texto_origem="NCM 1234"), *evidencias()[1:]])])
    assert plano.para_revisao[0].aliquota["tipo_correspondencia"] == "PREFIXO"
    assert plano.para_revisao[0].aliquota["exige_descricao"] == "SIM"


def test_condicao_de_dispositivo_complementar_sem_cadeia_confirmada_e_bloqueada():
    trecho = "Somente na operação descrita no ato fictício"
    complemento = [{"regra_extraida_id": 19, "papel": "CONDICAO", "trecho": trecho,
                    "evidencias": [{"tipo": "CONDICAO", "texto": trecho, "inicio": 0, "fim": 7}]}]
    plano = simular_publicacao([proposta(
        evidencias=evidencias()[:-1], complementos_json=json.dumps(complemento))])
    assert plano.bloqueadas and not plano.para_revisao


def test_repeticao_mesma_norma_e_regra_nao_gera_recadastro():
    primeira = simular_publicacao([proposta()]).para_revisao[0]
    repetida = proposta(id=42, regra_origem_id=13,
                        evidencias=[dict(evidencias(13, "12345678")[0], id=24),
                                    *evidencias(13)[1:]])
    plano = simular_publicacao([proposta(), repetida],
                              legislacoes_existentes=[dict(primeira.legislacao, ativo="SIM")],
                              aliquotas_existentes=[dict(primeira.aliquota, ativo="SIM")])
    assert not plano.para_revisao
    assert len(plano.inalteradas) == 2


def test_mesma_chave_com_percentual_divergente_e_bloqueada():
    anterior = simular_publicacao([proposta()]).para_revisao[0]
    plano = simular_publicacao([proposta(aliquota_icms=Decimal("9"))],
                              legislacoes_existentes=[dict(anterior.legislacao, ativo="SIM")],
                              aliquotas_existentes=[dict(anterior.aliquota, ativo="SIM")])
    assert not plano.para_revisao
    assert plano.bloqueadas[0]["motivos"]


def test_regra_existente_sem_legislacao_ou_inativa_nao_e_aceita_como_igual():
    anterior = simular_publicacao([proposta()]).para_revisao[0]
    sem_fundamento = simular_publicacao([proposta()],
                                       aliquotas_existentes=[anterior.aliquota])
    assert sem_fundamento.bloqueadas and not sem_fundamento.inalteradas
    inativa = simular_publicacao([proposta()],
                                legislacoes_existentes=[dict(anterior.legislacao, ativo="SIM")],
                                aliquotas_existentes=[dict(anterior.aliquota, ativo="NAO")])
    assert inativa.bloqueadas and not inativa.inalteradas


def test_cli_dry_run_sintetico_nao_abre_conexao_real(monkeypatch, capsys):
    from scripts import simular_publicacao_fiscal as cli
    from src.dados.postgres_repository import PostgresRepository

    classe = type("RepositorioFalso", (), {"dados_para_simulacao":
                  lambda self: ([proposta()], [], [])})
    monkeypatch.setattr(cli, "criar_repositorio", lambda **_: PostgresRepository(
        "postgresql+psycopg://teste:teste@localhost/sintetico", engine=object()))
    monkeypatch.setattr(cli, "RepositorioConsolidacao", lambda engine: classe())
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://teste:teste@localhost/sintetico")
    monkeypatch.setattr("sys.argv", ["simular_publicacao_fiscal"])
    assert cli.main() == 0
    saida = capsys.readouterr().out
    assert "DRY-RUN" in saida and "PARA REVISÃO" in saida
    assert "DADOS SINTÉTICOS" in saida and "nenhuma proposta autorizada" in saida
    assert "postgresql+psycopg" not in saida


def test_cli_rejeita_data_de_aprovacao_informada_em_argumento(monkeypatch):
    from scripts import simular_publicacao_fiscal as cli

    monkeypatch.setattr("sys.argv", ["simular_publicacao_fiscal",
                                    "--data-verificacao-fiscal", "2025-02-02"])
    with pytest.raises(SystemExit) as erro:
        cli.main()
    assert erro.value.code == 2


def test_fonte_superada_nao_pode_entrar_no_plano():
    assert simular_publicacao([proposta(fonte_atual=False)]).bloqueadas


def test_repositorio_simulacao_le_apenas_select_e_detecta_versao_superada():
    from updater.repositorio_consolidacao import RepositorioConsolidacao

    class Conexao:
        def __init__(self):
            self.consultas = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, comando):
            assert str(comando).lstrip().upper().startswith("SELECT")
            indice = len(self.consultas)
            self.consultas.append(comando)
            linhas = ([dict(proposta(), versao_ato_id=7, ultima_versao_id=8,
                            status_ato="NOVO", hash_atual="igual", hash_versao="igual")],
                      evidencias(), [], [])[indice]

            class Resultado:
                def mappings(self):
                    return linhas

            return Resultado()

    class Engine:
        def __init__(self):
            self.conexao = Conexao()

        def connect(self):
            return self.conexao

    engine = Engine()
    propostas, leis, aliquotas = RepositorioConsolidacao(engine).dados_para_simulacao()
    assert len(engine.conexao.consultas) == 4
    assert not propostas[0]["fonte_atual"]
    assert len(propostas[0]["evidencias"]) == len(evidencias())
    assert leis == aliquotas == []


def test_aprovacao_em_memoria_nao_se_torna_autorizacao():
    pendente = proposta(status_validacao="PENDENTE", fonte_atual=True,
                       fonte_verificada=True, cadeia_origem_valida=True)
    decisao = planejar_revisao(pendente, "APROVAR", responsavel="Revisor sintético",
                              justificativa="Somente ensaio", data=date(2025, 2, 2))
    assert decisao["situacao_simulada"] == "APROVACAO_SIMULADA"
    assert "status_validacao" not in decisao
    assert pendente["status_validacao"] == "PENDENTE"
    plano = simular_publicacao([pendente])
    assert not hasattr(plano, "autorizadas_para_publicacao")
    assert [r.proposta_id for r in plano.para_revisao] == [41]


def test_fonte_ausente_ou_nao_confirmada_bloqueia():
    for valor in (None, False):
        dados = proposta(fonte_atual=valor, fonte_verificada=valor)
        assert simular_publicacao([dados]).bloqueadas
    sem_campo = proposta(fonte_atual=True)
    sem_campo.pop("fonte_verificada")
    assert simular_publicacao([sem_campo]).bloqueadas


def test_versao_antiga_validada_nao_prevalece_sobre_pendente():
    antiga = proposta(id=41, chave_consolidacao="assunto-sintetico",
                      status_validacao="VALIDADA", fonte_atual=True,
                      fonte_verificada=True, cadeia_origem_valida=True)
    nova = proposta(id=42, chave_consolidacao="assunto-sintetico",
                   regra_anterior_id=41, status_validacao="PENDENTE",
                   fonte_atual=True, fonte_verificada=True, cadeia_origem_valida=True)
    plano = simular_publicacao([antiga, nova])
    assert any(b["proposta_id"] == 41 for b in plano.bloqueadas)
    assert all(r.proposta_id != 41 for r in plano.para_revisao)


def test_versao_antiga_do_consolidador_permanece_bloqueada():
    plano = simular_publicacao([proposta(consolidador_versao="versao-sintetica-antiga",
                                         status_validacao="VALIDADA")])
    assert plano.bloqueadas and not plano.para_revisao


def test_vigencia_divergente_e_dispositivo_sem_evidencia_bloqueiam():
    base = proposta(fonte_atual=True, fonte_verificada=True, cadeia_origem_valida=True)
    divergente = dict(base, vigencia_inicio=date(2025, 3, 1))
    assert simular_publicacao([divergente]).bloqueadas
    sem_inciso = dict(base, evidencias=[e for e in evidencias() if e["tipo_evidencia"] != "INCISO"])
    assert simular_publicacao([sem_inciso]).bloqueadas


def test_rejeicao_persistente_e_historico_intacto():
    rejeitada = proposta(status_validacao="DESCARTADA", fonte_atual=True,
                        fonte_verificada=True, cadeia_origem_valida=True)
    original = dict(rejeitada)
    plano = simular_publicacao([rejeitada])
    assert plano.bloqueadas and not plano.para_revisao
    assert rejeitada == original


def test_rejeicao_posterior_bloqueia_proposta_antiga_validada():
    antiga = proposta(id=41, chave_consolidacao="chave-sintetica",
                      status_validacao="VALIDADA")
    posterior = proposta(id=42, chave_consolidacao="chave-sintetica",
                         regra_anterior_id=41, status_validacao="DESCARTADA")
    registros = [dict(antiga), dict(posterior)]
    plano = simular_publicacao([antiga, posterior])
    assert {b["proposta_id"] for b in plano.bloqueadas} == {41, 42}
    assert not plano.para_revisao
    assert [antiga, posterior] == registros


def test_repositorio_bloqueia_extracao_ligada_a_ato_diferente():
    from updater.repositorio_consolidacao import RepositorioConsolidacao

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, comando):
            assert str(comando).lstrip().upper().startswith("SELECT")
            if "FROM regras_consolidadas" in str(comando):
                linhas = [dict(proposta(), ato_extracao_id=999, ato_versao_id=7,
                              versao_ato_id=3, ultima_versao_id=3, status_ato="PROCESSADO",
                              hash_atual="hash", hash_versao="hash")]
            elif "FROM evidencias_extracao" in str(comando):
                linhas = evidencias()
            else:
                linhas = []

            class Resultado:
                def mappings(self):
                    return linhas

            return Resultado()

    class Engine:
        def connect(self):
            return Conexao()

    propostas, _, _ = RepositorioConsolidacao(Engine()).dados_para_simulacao()
    assert propostas[0]["cadeia_origem_valida"] is False
    assert simular_publicacao(propostas).bloqueadas


def test_regra_materialmente_equivalente_com_ids_legados_nao_e_reproposta():
    previsao = simular_publicacao([proposta()]).para_revisao[0]
    lei = dict(previsao.legislacao, id_legislacao="LEGADO-1", ativo="SIM")
    aliquota = dict(previsao.aliquota, id_regra="LEGADO-2",
                    id_legislacao="LEGADO-1", ativo="SIM")
    plano = simular_publicacao([proposta()], legislacoes_existentes=[lei],
                              aliquotas_existentes=[aliquota])
    assert plano.inalteradas == [41]
    assert not plano.para_revisao


def test_periodos_sobrepostos_bloqueiam_nova_regra_sem_apagar_historico():
    previsao = simular_publicacao([proposta()]).para_revisao[0]
    lei = dict(previsao.legislacao, ativo="SIM")
    aliquota = dict(previsao.aliquota, ativo="SIM")
    evidencia_inicio = {"id": 50, "regra_extraida_id": 12, "tipo_evidencia": "VIGENCIA",
                        "valor_extraido": "2026-01-01", "texto_origem": "a partir de 2026-01-01"}
    nova = proposta(id=43, numero="1000", norma_base="LEI 1000/2025",
                    vigencia_inicio=date(2026, 1, 1),
                    evidencias=[e for e in evidencias() if e["id"] != 27] + [evidencia_inicio])
    plano = simular_publicacao([nova], legislacoes_existentes=[lei],
                              aliquotas_existentes=[aliquota])
    assert plano.bloqueadas and "sobreposição" in str(plano.bloqueadas)
    assert lei["ativo"] == aliquota["ativo"] == "SIM"


def test_evidencia_parcial_de_dispositivo_ou_condicao_nao_confere():
    inciso_errado = [dict(e, valor_extraido="III", texto_origem="Inciso III")
                    if e["tipo_evidencia"] == "INCISO" else e for e in evidencias()]
    assert simular_publicacao([proposta(evidencias=inciso_errado)]).bloqueadas
    condicao_parcial = [dict(e, valor_extraido="Somente", texto_origem="Somente")
                       if e["tipo_evidencia"] == "CONDICAO" else e for e in evidencias()]
    assert simular_publicacao([proposta(evidencias=condicao_parcial)]).bloqueadas
    trecho_errado = [dict(e, texto_origem="Inciso III")
                     if e["tipo_evidencia"] == "INCISO" else e for e in evidencias()]
    assert simular_publicacao([proposta(evidencias=trecho_errado)]).bloqueadas


def test_duas_propostas_identicas_no_mesmo_lote_nao_duplicam_projecao():
    primeira = proposta()
    segunda = proposta(id=42, regra_origem_id=13, chave_consolidacao=None,
                       evidencias=[dict(e, regra_extraida_id=13) for e in evidencias()])
    plano = simular_publicacao([primeira, segunda])
    assert len(plano.para_revisao) == 1
    assert plano.duplicadas_no_lote == [42]


def test_fonte_de_banco_sem_confirmacao_explicita_permanece_bloqueada():
    from updater.repositorio_consolidacao import RepositorioConsolidacao

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, comando):
            if "FROM regras_consolidadas" in str(comando):
                linhas = [dict(proposta(), ato_extracao_id=7, ato_versao_id=7,
                              versao_ato_id=3, ultima_versao_id=3,
                              processamento_id=9, extrator_versao="2.5.4-recovery.1",
                              elegivel_consolidacao="SIM", elegivel_consulta_ncm="SIM",
                              papel_dispositivo="REGRA_MATERIAL",
                              status_ato="PROCESSADO", status_extracao="VALIDADO",
                              hash_atual="hash", hash_versao="hash")]
            elif "FROM processamentos_extracao" in str(comando):
                linhas = [{"id": 9, "ato_id": 7, "versao_ato_id": 3,
                           "extrator_versao": "2.5.4-recovery.1", "status": "COMPLETO"}]
            elif "FROM evidencias_extracao" in str(comando):
                linhas = evidencias()
            else:
                linhas = []

            class Resultado:
                def mappings(self):
                    return linhas

            return Resultado()

    class Engine:
        def connect(self):
            return Conexao()

    propostas, _, _ = RepositorioConsolidacao(Engine()).dados_para_simulacao()
    assert propostas[0]["fonte_atual"] is True
    assert propostas[0]["fonte_verificada"] is False
    assert simular_publicacao(propostas).bloqueadas
