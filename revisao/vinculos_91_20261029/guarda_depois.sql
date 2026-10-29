DO $guarda91$
BEGIN
 IF (SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY id_beneficio)::text) FROM public.beneficios b) IS DISTINCT FROM '43ad39da58caa4f675731d636eee06e9'
 OR (SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY id_legislacao)::text) FROM public.legislacao b) IS DISTINCT FROM '1f3db645bb2639000e1092c91df30e33'
 OR (SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY id_regra)::text) FROM public.aliquotas b) IS DISTINCT FROM '468a85a8096be4e9f5431f275570adf9'
 THEN RAISE EXCEPTION 'Resultado91 difere do ensaio; transação cancelada'; END IF;
END $guarda91$;
