"""Schema PostgreSQL alinhado às colunas da planilha, sem dados fiscais."""

from sqlalchemy import Column, Date, Index, Integer, MetaData, Numeric, String, Table, Text

metadata = MetaData()

ncm = Table(
    "ncm", metadata,
    Column("ncm", String(8), primary_key=True),
    Column("descricao_oficial", Text),
    Column("capitulo", Text),
    Column("posicao", Text),
    Column("subposicao", Text),
    Column("observacao", Text),
    Column("ativo", String(3), nullable=False),
)

legislacao = Table(
    "legislacao", metadata,
    Column("id_legislacao", Text, primary_key=True),
    Column("norma", Text),
    Column("numero", Text),
    Column("ano", Text),
    Column("anexo", Text),
    Column("artigo", Text),
    Column("paragrafo", Text),
    Column("inciso", Text),
    Column("alinea", Text),
    Column("item", Text),
    Column("resumo", Text),
    Column("texto_relevante", Text),
    Column("url_fonte", Text),
    Column("vigencia_inicio", Date),
    Column("vigencia_fim", Date),
    Column("data_verificacao", Date),
    Column("ativo", String(3), nullable=False),
)

aliquotas = Table(
    "aliquotas", metadata,
    Column("id_regra", Text, primary_key=True),
    Column("chave_ncm", String(8), nullable=False),
    Column("tipo_correspondencia", String(7), nullable=False),
    Column("descricao_regra", Text),
    Column("palavras_chave", Text),
    Column("aliquota_icms", Numeric(asdecimal=True)),
    Column("adicional_percentual", Numeric(asdecimal=True)),
    Column("id_legislacao", Text),
    Column("regra_consolidada_id", Integer),
    Column("evidencia_ncm_id", Integer),
    Column("vigencia_inicio", Date),
    Column("vigencia_fim", Date),
    Column("observacao", Text),
    Column("ativo", String(3), nullable=False),
    Column("exige_descricao", String(3), nullable=False),
)

beneficios = Table(
    "beneficios", metadata,
    Column("id_beneficio", Text, primary_key=True),
    Column("chave_ncm", String(8), nullable=False),
    Column("tipo_correspondencia", String(7), nullable=False),
    Column("descricao_regra", Text),
    Column("palavras_chave", Text),
    Column("tipo_beneficio", Text),
    Column("percentual_reducao_bc", Numeric(asdecimal=True)),
    Column("carga_efetiva", Numeric(asdecimal=True)),
    Column("credito_outorgado_percentual", Numeric(asdecimal=True)),
    Column("condicoes", Text),
    Column("id_legislacao", Text),
    Column("regra_consolidada_id", Integer),
    Column("evidencia_ncm_id", Integer),
    Column("vigencia_inicio", Date),
    Column("vigencia_fim", Date),
    Column("observacao", Text),
    Column("ativo", String(3), nullable=False),
    Column("exige_descricao", String(3), nullable=False),
    Column("grupo_beneficio", Text),
    Column("aplicacao", String(12)),
    Column("escopo_operacao", String(14)),
    Column("cbenef", Text),
)

for tabela in (aliquotas, beneficios):
    Index(f"ix_{tabela.name}_chave_ativo", tabela.c.chave_ncm, tabela.c.ativo)
    Index(f"ix_{tabela.name}_vigencia", tabela.c.vigencia_inicio, tabela.c.vigencia_fim)
    Index(f"ix_{tabela.name}_legislacao", tabela.c.id_legislacao)

TABELAS = {
    "NCM": ncm,
    "Legislacao": legislacao,
    "Aliquotas": aliquotas,
    "Beneficios": beneficios,
}
