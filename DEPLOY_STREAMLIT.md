# Publicação do consultor Streamlit

1. Versione o código no GitHub e crie a aplicação no Streamlit Community Cloud com `app.py` como arquivo principal. As dependências vêm de `requirements.txt`.
2. No painel de secrets da aplicação, configure sem versionar credenciais reais:

   ```toml
   DATA_SOURCE = "postgres"
   DATABASE_URL = "postgresql+psycopg://USUARIO_READ_ONLY:SENHA@HOST/BANCO"
   ```

3. Use um usuário PostgreSQL **somente leitura** nas tabelas necessárias. A credencial pública deve ter `SELECT` e não ter `INSERT`, `UPDATE` nem `DELETE`; não use `neondb_owner`.
4. Antes de publicar, aplique as migrações necessárias por fluxo administrativo autorizado, confira a sincronização oficial da NCM e rode `python -m scripts.verificar_prontidao_producao` em ambiente com acesso ao PostgreSQL. O comando apenas consulta o banco e sai com código diferente de zero enquanto houver bloqueadores.

O `app.py` é a interface pública de consulta. Não publique `admin.py` como entrada da aplicação pública.
