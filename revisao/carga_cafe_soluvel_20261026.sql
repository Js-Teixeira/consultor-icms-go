DO $carga12$
DECLARE
    carga jsonb := '{"lote":"CAND12_20261026","legislacao":[{"id_legislacao":"LEG_CAND12_20261026_A","norma":"Lei nº 11.651/1991 - Código Tributário do Estado de Goiás","numero":"11.651","ano":"1991","anexo":null,"artigo":"27","paragrafo":null,"inciso":"II","alinea":"a","item":null,"resumo":"Referência legal para possibilidades condicionais de 12%; não confirma vínculo NCM/produto.","texto_relevante":"açúcar; arroz; café; farinhas de mandioca, de milho e de trigo; feijão; fubá; iogurte; macarrão; margarina vegetal; manteiga de leite; milho; óleo vegetal comestível, exceto de oliva; queijo, inclusive requeijão; rapadura; sal iodado e vinagre;","url_fonte":"https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm","vigencia_inicio":"2021-01-01","vigencia_fim":null,"data_verificacao":"2026-10-26","ativo":"SIM"}],"aliquotas":[{"id_regra":"CAND12_20261026_CAFE_SOLUVEL_21011110","chave_ncm":"21011110","tipo_correspondencia":"EXATO","descricao_regra":"Possibilidade condicionada de 12% — Café solúvel puro, inclusive descafeinado","palavras_chave":"Café solúvel puro, inclusive descafeinado","aliquota_icms":12,"adicional_percentual":null,"id_legislacao":"LEG_CAND12_20261026_A","regra_consolidada_id":null,"evidencia_ncm_id":null,"vigencia_inicio":"2026-10-26","vigencia_fim":null,"observacao":"CANDIDATO CONDICIONAL. Cadastro autorizado como possibilidade, sem confirmação de enquadramento fiscal por NCM. Confirmar produto puro, 100% café, inclusive descafeinado; não estender a cappuccino, café com leite, misturas ou outros extratos. O vínculo aos 12% é proposta técnica a partir do termo café no art. 27, II, a, do CTE e depende de revisão fiscal. O Parecer GO 225/2022 trata de redução de base de cálculo para café solúvel puro e não confirma a alíquota nominal de 12% nem sua aplicação atual. Benefício e condições devem ser verificados separadamente. Parecer: https://appasp.economia.go.gov.br/pareceres/arquivos/Benef%C3%ADcio%20Fiscal/Redu%C3%A7%C3%A3o%20de%20BC%20concedida%20por%20prazo%20indeterminado%20-%20Art.%208%C2%B0/XXXIII/P_225_2022_SEI.docx Início do cadastro: 2026-10-26; redação legal desde 2021-01-01. Vínculo técnico por nomenclatura; proposta CTE27II_CAFE_SOLUVEL_21011110. Conferir benefícios, ST, adicionais e demais condições da operação. Lote CAND12_20261026.","ativo":"SIM","exige_descricao":"SIM"}]}'::jsonb;
BEGIN
    LOCK TABLE public.ncm IN SHARE MODE;
    LOCK TABLE public.legislacao, public.aliquotas IN SHARE ROW EXCLUSIVE MODE;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(carga->'aliquotas') p
        LEFT JOIN public.ncm n ON n.ncm = p->>'chave_ncm' AND upper(trim(n.ativo))='SIM'
        WHERE n.ncm IS NULL OR p->>'exige_descricao' <> 'SIM'
           OR p->>'tipo_correspondencia' <> 'EXATO' OR p->>'ativo' <> 'SIM'
           OR (p->>'aliquota_icms')::numeric <> 12
    ) THEN RAISE EXCEPTION 'Carga incompatível: NCM ou condição não autorizada'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(carga->'legislacao') p
        JOIN public.legislacao l ON l.id_legislacao=p->>'id_legislacao'
        WHERE NOT to_jsonb(l) @> p
    ) THEN RAISE EXCEPTION 'Conflito no fundamento; nenhum registro foi sobrescrito'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(carga->'aliquotas') p
        JOIN public.aliquotas a ON a.id_regra=p->>'id_regra'
        WHERE NOT to_jsonb(a) @> p
    ) THEN RAISE EXCEPTION 'Conflito na regra; nenhum registro foi sobrescrito'; END IF;
    IF EXISTS (
        SELECT 1 FROM public.aliquotas a
        WHERE a.chave_ncm IN (SELECT p->>'chave_ncm' FROM jsonb_array_elements(carga->'aliquotas') p)
          AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(carga->'aliquotas') p
                          WHERE p->>'id_regra'=a.id_regra)
    ) THEN RAISE EXCEPTION 'NCM alvo já possui outro cadastro; revisar mudança concorrente'; END IF;
    INSERT INTO public.legislacao
        SELECT * FROM jsonb_populate_recordset(NULL::public.legislacao, carga->'legislacao')
        ON CONFLICT (id_legislacao) DO NOTHING;
    INSERT INTO public.aliquotas
        SELECT * FROM jsonb_populate_recordset(NULL::public.aliquotas, carga->'aliquotas')
        ON CONFLICT (id_regra) DO NOTHING;
END
$carga12$;
