"""Migração aditiva das datas de atos já monitorados."""

from __future__ import annotations

from sqlalchemy import Engine, text

from .modelos import AVISO_DIVERGENCIA

ERRO_ANTIGO_DIVERGENCIA = "A data do ato diverge entre a página de descoberta e o documento oficial."


def _tem_coluna(conexao, coluna: str) -> bool:
    return bool(conexao.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'atos_legislativos'
              AND column_name = :coluna
        )
    """), {"coluna": coluna}).scalar_one())


def migrar_datas_monitoramento(engine: Engine) -> None:
    """Preserva datas antigas antes de dar significado próprio a cada coluna."""

    with engine.begin() as conexao:
        if not _tem_coluna(conexao, "data_descoberta"):
            conexao.execute(text("ALTER TABLE atos_legislativos ADD COLUMN IF NOT EXISTS data_descoberta DATE"))
            conexao.execute(text("""
                UPDATE atos_legislativos
                SET data_descoberta = data_ato
                WHERE data_descoberta IS NULL
            """))
            # Antes desta versão, data_ato guardava a data lida no título da lista.
            # O valor fica em data_descoberta; o ato só recebe a data verificada no texto.
            if _tem_coluna(conexao, "data_ato_documento"):
                conexao.execute(text("UPDATE atos_legislativos SET data_ato = data_ato_documento"))
            else:
                conexao.execute(text("UPDATE atos_legislativos SET data_ato = NULL"))

        if not _tem_coluna(conexao, "divergencia_data"):
            conexao.execute(text("""
                ALTER TABLE atos_legislativos
                ADD COLUMN IF NOT EXISTS divergencia_data VARCHAR(3) NOT NULL DEFAULT 'NAO'
            """))
        if not _tem_coluna(conexao, "advertencia_data"):
            conexao.execute(text("ALTER TABLE atos_legislativos ADD COLUMN IF NOT EXISTS advertencia_data TEXT"))

        conexao.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'ck_ato_divergencia_data'
                      AND conrelid = 'atos_legislativos'::regclass
                ) THEN
                    ALTER TABLE atos_legislativos
                    ADD CONSTRAINT ck_ato_divergencia_data
                    CHECK (divergencia_data IN ('SIM', 'NAO'));
                END IF;
            END $$
        """))
        conexao.execute(text("""
            UPDATE atos_legislativos
            SET divergencia_data = CASE
                WHEN data_ato <> data_descoberta THEN 'SIM' ELSE 'NAO'
            END
            WHERE data_ato IS NOT NULL AND data_descoberta IS NOT NULL
        """))
        conexao.execute(text("""
            UPDATE atos_legislativos
            SET advertencia_data = :aviso
            WHERE divergencia_data = 'SIM' AND advertencia_data IS NULL
        """), {"aviso": AVISO_DIVERGENCIA})
        conexao.execute(text("""
            UPDATE atos_legislativos
            SET status = CASE WHEN relevancia = 'BAIXA' THEN 'IGNORADO' ELSE 'NOVO' END,
                erro_coleta = NULL
            WHERE status = 'ERRO'
              AND erro_coleta = :erro_antigo
              AND hash_conteudo IS NOT NULL
              AND divergencia_data = 'SIM'
        """), {"erro_antigo": ERRO_ANTIGO_DIVERGENCIA})


def migrar_prioridade_ncm(engine: Engine) -> None:
    """Acrescenta metadados de descoberta sem promover registros antigos."""

    with engine.begin() as conexao:
        for coluna, definicao in (
            ("relevancia_ncm", "VARCHAR(11) NOT NULL DEFAULT 'SEM_INDICIO'"),
            ("motivos_relevancia_ncm", "TEXT NOT NULL DEFAULT ''"),
            ("quantidade_ncms_texto", "INTEGER NOT NULL DEFAULT 0"),
            ("possui_ncm_explicito", "VARCHAR(3) NOT NULL DEFAULT 'NAO'"),
            ("possui_prefixo_ncm", "VARCHAR(3) NOT NULL DEFAULT 'NAO'"),
            ("possui_termo_material_icms", "VARCHAR(3) NOT NULL DEFAULT 'NAO'"),
            ("texto_consolidado", "VARCHAR(3) NOT NULL DEFAULT 'NAO'"),
        ):
            conexao.execute(text(f"ALTER TABLE atos_legislativos ADD COLUMN IF NOT EXISTS {coluna} {definicao}"))
        conexao.execute(text("ALTER TABLE versoes_ato ADD COLUMN IF NOT EXISTS url_origem TEXT"))
        conexao.execute(text("""
            ALTER TABLE versoes_ato ADD COLUMN IF NOT EXISTS texto_consolidado VARCHAR(3) NOT NULL DEFAULT 'NAO'
        """))
        conexao.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ato_relevancia_ncm'
                      AND conrelid = 'atos_legislativos'::regclass
                ) THEN
                    ALTER TABLE atos_legislativos ADD CONSTRAINT ck_ato_relevancia_ncm
                    CHECK (relevancia_ncm IN ('MUITO_ALTA', 'ALTA', 'MEDIA', 'BAIXA', 'SEM_INDICIO'));
                END IF;
            END $$
        """))


def migrar_escopo_extracao(engine: Engine) -> None:
    """Acrescenta escopo às extrações sem excluir nem promover registros legados."""

    with engine.begin() as conexao:
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS escopo_fiscal VARCHAR(24) NOT NULL DEFAULT 'INDETERMINADO'
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS elegivel_consolidacao VARCHAR(3) NOT NULL DEFAULT 'NAO'
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS motivo_elegibilidade TEXT NOT NULL DEFAULT 'Classificação de escopo pendente.'
        """))
        for nome, expressao in (
            ("ck_regra_escopo_fiscal", "escopo_fiscal IN ('ALIQUOTA_BENEFICIO', 'PAUTA_PRECO', 'CREDITO_TRIBUTARIO', 'PROCEDIMENTO', 'ADMINISTRATIVO', 'OUTRO', 'INDETERMINADO')"),
            ("ck_regra_elegibilidade", "elegivel_consolidacao IN ('SIM', 'NAO')"),
        ):
            conexao.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = '{nome}'
                          AND conrelid = 'regras_extraidas'::regclass
                    ) THEN
                        ALTER TABLE regras_extraidas ADD CONSTRAINT {nome} CHECK ({expressao});
                    END IF;
                END $$
            """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS papel_dispositivo VARCHAR(24) NOT NULL DEFAULT 'INDETERMINADO'
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS grupo_regra_id VARCHAR(32)
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS descricao_proxima_ncm TEXT
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS elegivel_consulta_ncm VARCHAR(3) NOT NULL DEFAULT 'NAO'
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS status_vinculo_ncm VARCHAR(24) NOT NULL DEFAULT 'NAO_AVALIADO'
        """))
        conexao.execute(text("""
            ALTER TABLE regras_extraidas
            ADD COLUMN IF NOT EXISTS motivo_consulta_ncm TEXT NOT NULL DEFAULT 'Vínculo com NCM não avaliado.'
        """))
        conexao.execute(text("""
            ALTER TABLE regras_consolidadas
            ADD COLUMN IF NOT EXISTS complementos_json TEXT
        """))
        conexao.execute(text("""
            ALTER TABLE regras_consolidadas
            ADD COLUMN IF NOT EXISTS grupo_regra_id VARCHAR(32)
        """))
        conexao.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_regras_extraidas_grupo
            ON regras_extraidas (grupo_regra_id)
        """))
        for nome, expressao in (
            ("ck_regra_papel_dispositivo", "papel_dispositivo IN ('REGRA_MATERIAL', 'ABRANGENCIA', 'BENEFICIARIO', 'CALCULO', 'UTILIZACAO', 'CONDICAO', 'VEDACAO', 'EXCECAO', 'CONSEQUENCIA', 'PROCEDIMENTO', 'REFERENCIA', 'INDETERMINADO')"),
            ("ck_regra_consulta_ncm", "elegivel_consulta_ncm IN ('SIM', 'NAO')"),
            ("ck_regra_status_vinculo_ncm", "status_vinculo_ncm IN ('NCM_EXPLICITO', 'PENDENTE_VINCULO_NCM', 'SEM_VINCULO_NCM', 'NAO_AVALIADO')"),
        ):
            conexao.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = '{nome}'
                          AND conrelid = 'regras_extraidas'::regclass
                    ) THEN
                        ALTER TABLE regras_extraidas ADD CONSTRAINT {nome} CHECK ({expressao});
                    END IF;
                END $$
            """))
