DO $guarda91$
DECLARE hb text; hl text; ha text;
BEGIN
 LOCK TABLE public.ncm IN SHARE MODE;
 LOCK TABLE public.legislacao, public.aliquotas, public.beneficios IN SHARE ROW EXCLUSIVE MODE;
 SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY id_beneficio)::text) INTO hb FROM public.beneficios b;
 SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY id_legislacao)::text) INTO hl FROM public.legislacao b;
 SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY id_regra)::text) INTO ha FROM public.aliquotas b;
 IF NOT ((hb='8b015cb71282bae978a5485d74ae75a2' AND hl='21c15967bc1cde206b815885f3bb4ac4' AND ha='468a85a8096be4e9f5431f275570adf9')
      OR (hb='43ad39da58caa4f675731d636eee06e9' AND hl='1f3db645bb2639000e1092c91df30e33' AND ha='468a85a8096be4e9f5431f275570adf9'))
 THEN RAISE EXCEPTION 'Estado global mudou; interromper e revisar antes da carga91'; END IF;
END $guarda91$;
