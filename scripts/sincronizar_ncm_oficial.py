"""Sincroniza somente a tabela ncm com o JSON público vigente do Classif."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.schema import ncm as tabela_ncm

URL_CLASSIF = "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json"
TAMANHO_LOTE = 1000
CAMINHO_CACHE = Path(__file__).resolve().parents[1] / "base" / "cache_ncm_oficial.json"
MIN_NCMS_CACHE = 10000
VERSAO_CACHE = 2


class ErroSincronizacao(ValueError):
    """Fonte oficial indisponível ou conteúdo incompatível com a carga segura."""


@dataclass
class EstatisticasFonte:
    invalidos: int = 0
    duplicidades: int = 0


@dataclass
class Plano:
    inserir: list[dict[str, str]]
    atualizar: list[tuple[dict[str, Any], dict[str, str]]]
    iguais: int
    registros_atuais: int
    somente_no_banco: list[str]


def _descricao_com_espacos_normalizados(valor: str | None) -> str:
    return " ".join((valor or "").split())


def campos_diferentes(atual: dict[str, Any], oficial: dict[str, str]) -> list[str]:
    """Compara conteúdo oficial e hierarquia sem usar observação como critério."""

    campos = ("descricao_oficial", "capitulo", "posicao", "subposicao", "ativo")
    return [
        campo for campo in campos
        if (_descricao_com_espacos_normalizados(atual.get(campo)) if campo == "descricao_oficial" else atual.get(campo))
        != oficial[campo]
    ]


def baixar_json(cliente: httpx.Client) -> Any:
    """Conclui download e interpretação antes de qualquer acesso de escrita."""

    try:
        resposta = cliente.get(URL_CLASSIF, headers={"Accept": "application/json"})
        resposta.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ErroSincronizacao("Tempo esgotado ao baixar a NCM oficial.") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            try:
                mensagem = exc.response.json().get("message", "")
            except (ValueError, AttributeError):
                mensagem = ""
            if "limite de" in str(mensagem).lower() and "acessos" in str(mensagem).lower():
                raise ErroSincronizacao("O Classif limitou temporariamente os downloads (HTTP 422); tente novamente após a janela de acesso.") from exc
        raise ErroSincronizacao(f"Download da NCM oficial retornou HTTP {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise ErroSincronizacao("Falha de conexão ao baixar a NCM oficial.") from exc
    try:
        return resposta.json()
    except ValueError as exc:
        raise ErroSincronizacao("A fonte oficial retornou JSON inválido.") from exc


def _descricao_visual(valor: str) -> str:
    """Remove somente marcação visual; preserva palavras e hífens internos."""

    if "<" in valor or "&" in valor:
        html = BeautifulSoup(valor, "html.parser")
        for quebra in html.find_all("br"):
            quebra.replace_with(" ")
        valor = html.get_text()
    return " ".join(re.sub(r"^\s*-+\s*", "", valor).split())


def _dependente(descricao: str) -> bool:
    return bool(re.match(r"^(?:Outr[oa]s?|Com|Sem|De|Do|Da|Dos|Das|Não|Que|Para|Em)\b", descricao, re.I))


def _compor_segmentos(segmentos: list[str]) -> str:
    """Remove sobreposição literal entre níveis vizinhos, sem resumir o texto."""

    partes = [segmento.strip().rstrip(".:").strip() for segmento in segmentos]
    for indice, ancestral in enumerate(partes[:-1]):
        for descendente in range(indice + 1, len(partes)):
            folha = partes[descendente]
            # "mesmo X" no ancestral inclui X; quando X é a escolha final,
            # conserva a observação entre parênteses e evita repetir X.
            padrao = rf",\s*mesmo\s+{re.escape(folha)}(\s*\([^)]*\))?\s*$"
            sobreposicao = re.search(padrao, ancestral, re.I)
            if sobreposicao:
                partes[indice] = ancestral[:sobreposicao.start()].rstrip()
                nota = (sobreposicao.group(1) or "").strip()
                if nota:
                    partes[descendente] = f"{folha} {nota}"
                break
    compostos: list[str] = []
    for atual in partes:
        if not atual:
            continue
        if compostos:
            anterior = compostos[-1]
            a, b = anterior.casefold(), atual.casefold()
            if a == b or a.endswith(" " + b):
                continue
            if b.startswith(a + " "):
                compostos[-1] = atual
                continue
        compostos.append(atual)
    return " — ".join(compostos)


def _descricao_hierarquica(codigo: str, entradas: dict[str, str]) -> str:
    """Composição baseada apenas nos prefixos e descrições da árvore oficial."""

    caminho = [(prefixo, entradas[prefixo]) for tamanho in (4, 5, 6, 7, 8)
               if (prefixo := codigo[:tamanho]) in entradas]
    if len(caminho) == 1:
        return _descricao_visual(caminho[0][1])
    ancora = None
    for indice in range(len(caminho) - 2, -1, -1):
        bruto = caminho[indice][1]
        if re.match(r"^\s*-+\s*", bruto) and not _dependente(_descricao_visual(bruto)):
            ancora = indice
            break
    folha_bruta = caminho[-1][1]
    folha = _descricao_visual(folha_bruta)
    if ancora is None:
        if re.match(r"^\s*-+\s*", folha_bruta) or _dependente(folha) or any(
            re.match(r"^\s*-+\s*", bruto) for _, bruto in caminho[:-1]
        ):
            ancora = 0
        else:
            ancora = len(caminho) - 1
    return _compor_segmentos([_descricao_visual(bruto) for _, bruto in caminho[ancora:]])


def _validar_hierarquia_cache(documento: Any, quantidade_folhas: int) -> None:
    """Recusa carga final-only de produção, que não permite refazer a descrição."""

    if quantidade_folhas < 10000:
        return  # Fixtures sintéticas pequenas não representam uma tabela oficial inteira.
    codigos = {item["Codigo"].replace(".", "") for item in documento["Nomenclaturas"]
               if isinstance(item, dict) and isinstance(item.get("Codigo"), str)
               and re.fullmatch(r"[0-9.]+", item["Codigo"])}
    ancestrais = {codigo for codigo in codigos if len(codigo) < 8}
    folhas = {codigo for codigo in codigos if len(codigo) == 8}
    cobertos = sum(any(codigo[:tamanho] in ancestrais for tamanho in (4, 5, 6, 7))
                   for codigo in folhas)
    if len(ancestrais) < 1000 or cobertos < quantidade_folhas * 0.9:
        raise ErroSincronizacao(
            "Cache NCM antigo não contém hierarquia suficiente. Faça novo download oficial."
        )


def extrair_ncms(documento: Any) -> tuple[dict[str, dict[str, str]], EstatisticasFonte]:
    """Interpreta a árvore oficial e emite apenas NCMs finais com descrição completa."""

    if not isinstance(documento, dict) or not isinstance(documento.get("Nomenclaturas"), list):
        raise ErroSincronizacao("JSON oficial sem lista Nomenclaturas.")
    entradas = documento["Nomenclaturas"]
    if not entradas:
        raise ErroSincronizacao("A lista Nomenclaturas está vazia; carga abortada.")

    oficiais: dict[str, dict[str, str]] = {}
    estatisticas = EstatisticasFonte()
    hierarquia: dict[str, str] = {}
    folhas: list[str] = []
    for indice, entrada in enumerate(entradas, 1):
        if not isinstance(entrada, dict):
            raise ErroSincronizacao(f"Item {indice} da fonte oficial não é um objeto.")
        bruto = entrada.get("Codigo")
        if not isinstance(bruto, str) or not re.fullmatch(r"[0-9.]+", bruto):
            estatisticas.invalidos += 1
            continue
        codigo = bruto.replace(".", "")
        if not re.fullmatch(r"[0-9]{2,8}", codigo):
            estatisticas.invalidos += 1
            continue
        descricao_bruta = entrada.get("Descricao")
        if not isinstance(descricao_bruta, str) or not descricao_bruta.strip():
            raise ErroSincronizacao(f"NCM {codigo} sem descrição oficial válida; carga abortada.")
        descricao = _descricao_visual(descricao_bruta)
        if not descricao:
            raise ErroSincronizacao(f"NCM {codigo} sem texto de descrição após remover HTML; carga abortada.")
        anterior = hierarquia.get(codigo)
        if anterior is not None:
            marcador_anterior = re.match(r"^\s*(-+)", anterior)
            marcador_novo = re.match(r"^\s*(-+)", descricao_bruta)
            if (_descricao_visual(anterior) != descricao
                    or (len(marcador_anterior.group(1)) if marcador_anterior else 0)
                    != (len(marcador_novo.group(1)) if marcador_novo else 0)):
                raise ErroSincronizacao(f"NCM {codigo} duplicado com descrições oficiais divergentes; carga abortada.")
            if len(codigo) == 8:
                estatisticas.duplicidades += 1
            continue
        hierarquia[codigo] = descricao_bruta
        if len(codigo) != 8:
            estatisticas.invalidos += 1
            continue
        folhas.append(codigo)
    if not folhas:
        raise ErroSincronizacao("Nenhum NCM final válido encontrado; carga abortada.")
    for codigo in folhas:
        descricao = _descricao_hierarquica(codigo, hierarquia)
        oficiais[codigo] = {
            "ncm": codigo,
            "descricao_oficial": descricao,
            "capitulo": codigo[:2],
            "posicao": codigo[:4],
            "subposicao": codigo[:6],
            "ativo": "SIM",
        }
    return oficiais, estatisticas


def _conteudo_normalizado(documento: Any) -> bytes:
    try:
        return json.dumps(documento, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ErroSincronizacao("JSON oficial não pode ser armazenado no cache.") from exc


def salvar_cache(documento: Any, caminho: Path | None = None) -> dict[str, Any]:
    """Grava somente uma fonte validada; substitui o arquivo antigo atomicamente."""

    caminho = caminho or CAMINHO_CACHE
    oficiais, _ = extrair_ncms(documento)
    _validar_hierarquia_cache(documento, len(oficiais))
    if len(oficiais) < MIN_NCMS_CACHE:
        raise ErroSincronizacao(
            f"Download oficial possivelmente incompleto: {len(oficiais)} NCMs finais; "
            f"mínimo para cache: {MIN_NCMS_CACHE}."
        )
    cache_anterior_invalido = False
    try:
        anteriores, _, _ = carregar_cache(caminho)
    except ErroSincronizacao:
        anteriores = None
        cache_anterior_invalido = caminho.is_file()
    if anteriores is not None and len(oficiais) < len(anteriores):
        raise ErroSincronizacao(
            f"Download oficial possivelmente incompleto: {len(oficiais)} NCMs finais "
            f"contra {len(anteriores)} no cache válido; cache preservado."
        )
    metadados = {
        "versao_cache": VERSAO_CACHE,
        "download_em": datetime.now(timezone.utc).isoformat(),
        "url_origem": URL_CLASSIF,
        "quantidade_recebida": len(documento["Nomenclaturas"]),
        "ncms_finais": len(oficiais),
        "sha256": hashlib.sha256(_conteudo_normalizado(documento)).hexdigest(),
    }
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with temporario.open("w", encoding="utf-8") as arquivo:
            json.dump({"metadados": metadados, "documento": documento}, arquivo,
                      ensure_ascii=False, allow_nan=False)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        if cache_anterior_invalido:
            backup = caminho.with_name(caminho.name + ".legacy")
            indice = 1
            while backup.exists():
                backup = caminho.with_name(caminho.name + f".legacy.{indice}")
                indice += 1
            with caminho.open("rb") as origem, backup.open("xb") as destino:
                shutil.copyfileobj(origem, destino)
                destino.flush()
                os.fsync(destino.fileno())
        os.replace(temporario, caminho)
    except OSError as exc:
        raise ErroSincronizacao("Não foi possível gravar o cache oficial local.") from exc
    finally:
        temporario.unlink(missing_ok=True)
    return metadados


def carregar_cache(caminho: Path | None = None) -> tuple[dict[str, dict[str, str]], EstatisticasFonte, dict[str, Any]]:
    """Revalida origem, integridade e NCMs antes de usar o cache."""

    caminho = caminho or CAMINHO_CACHE
    if not caminho.is_file():
        raise ErroSincronizacao("Cache oficial local não encontrado; será necessário um novo download oficial.")
    try:
        with caminho.open(encoding="utf-8") as arquivo:
            cache = json.load(arquivo)
        if not isinstance(cache, dict) or not isinstance(cache.get("metadados"), dict):
            raise ValueError("estrutura")
        metadados = cache["metadados"]
        versao = metadados.get("versao_cache", 1)
        if type(versao) is not int or versao not in (1, VERSAO_CACHE):
            raise ValueError("versão de cache incompatível")
        if metadados.get("url_origem") != URL_CLASSIF:
            raise ValueError("origem")
        instante = datetime.fromisoformat(metadados["download_em"])
        if instante.tzinfo is None:
            raise ValueError("data sem fuso")
        documento = cache["documento"]
        hash_atual = hashlib.sha256(_conteudo_normalizado(documento)).hexdigest()
        if metadados.get("sha256") != hash_atual:
            raise ValueError("SHA-256 divergente")
        oficiais, estatisticas = extrair_ncms(documento)
        _validar_hierarquia_cache(documento, len(oficiais))
        if versao == VERSAO_CACHE and (type(metadados.get("quantidade_recebida")) is not int
                                      or metadados["quantidade_recebida"] != len(documento["Nomenclaturas"])):
            raise ValueError("quantidade recebida divergente")
        if type(metadados.get("ncms_finais")) is not int or metadados["ncms_finais"] != len(oficiais):
            raise ValueError("contagem divergente")
        if len(oficiais) < MIN_NCMS_CACHE:
            raise ValueError("quantidade insuficiente de NCMs finais")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ErroSincronizacao(f"Cache oficial local inválido: {exc}.") from exc
    return oficiais, estatisticas, metadados


def _aviso_cache_disponivel() -> None:
    try:
        _, _, metadados = carregar_cache()
    except ErroSincronizacao:
        return
    data = datetime.fromisoformat(metadados["download_em"]).strftime("%d/%m/%Y")
    print(f"Fonte oficial indisponível. Existe cache oficial local de {data}. "
          "Use --usar-cache explicitamente se desejar continuar.")


def planejar(oficiais: dict[str, dict[str, str]], existentes: dict[str, dict[str, Any]]) -> Plano:
    """Compara descrição, hierarquia e ativo; preserva códigos fora da fonte."""

    inserir: list[dict[str, str]] = []
    atualizar: list[tuple[dict[str, Any], dict[str, str]]] = []
    iguais = 0
    for codigo, oficial in oficiais.items():
        atual = existentes.get(codigo)
        if atual is None:
            inserir.append(oficial)
        elif campos_diferentes(atual, oficial):
            atualizar.append((atual, oficial))
        else:
            iguais += 1
    if len(inserir) + len(atualizar) + iguais != len(oficiais):
        raise ErroSincronizacao("A soma INSERIR + IGUAL + ATUALIZAR difere do total oficial; carga abortada.")
    return Plano(inserir=inserir, atualizar=atualizar, iguais=iguais,
                 registros_atuais=len(existentes),
                 somente_no_banco=sorted(existentes.keys() - oficiais.keys()))


def sincronizar(engine: Engine, oficiais: dict[str, dict[str, str]], *, dry_run: bool) -> Plano:
    """Compara e, quando autorizado, grava tudo em uma única transação."""

    with engine.begin() as conexao:
        registros = conexao.execute(select(
            tabela_ncm.c.ncm, tabela_ncm.c.descricao_oficial,
            tabela_ncm.c.capitulo, tabela_ncm.c.posicao, tabela_ncm.c.subposicao,
            tabela_ncm.c.ativo,
        )).mappings()
        existentes = {linha["ncm"]: dict(linha) for linha in registros}
        plano = planejar(oficiais, existentes)
        if not dry_run:
            for inicio in range(0, len(plano.inserir), TAMANHO_LOTE):
                conexao.execute(tabela_ncm.insert(), plano.inserir[inicio:inicio + TAMANHO_LOTE])
            for _, oficial in plano.atualizar:
                conexao.execute(
                    tabela_ncm.update().where(tabela_ncm.c.ncm == oficial["ncm"]).values(
                        descricao_oficial=oficial["descricao_oficial"],
                        capitulo=oficial["capitulo"],
                        posicao=oficial["posicao"],
                        subposicao=oficial["subposicao"],
                        ativo="SIM",
                    )
                )
    return plano


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza NCMs oficiais do Classif na tabela ncm.")
    parser.add_argument("--dry-run", action="store_true", help="Compara sem escrever no PostgreSQL")
    parser.add_argument("--usar-cache", action="store_true", help="Usa explicitamente o último download oficial validado, sem HTTP")
    args = parser.parse_args()
    if args.usar_cache and not args.dry_run:
        parser.error("--usar-cache exige --dry-run para comparação sem escrita")
    try:
        if args.usar_cache:
            oficiais, estatisticas, metadados = carregar_cache()
            repositorio = criar_repositorio(data_source="postgres")
        else:
            # Falha de configuração antes do download evita consumir a cota da fonte.
            repositorio = criar_repositorio(data_source="postgres")
            try:
                with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=True) as cliente:
                    documento = baixar_json(cliente)
            except ErroSincronizacao:
                _aviso_cache_disponivel()
                raise
            oficiais, estatisticas = extrair_ncms(documento)
            metadados = salvar_cache(documento)
        print("=== SINCRONIZAÇÃO NCM OFICIAL ===")
        if args.usar_cache:
            print("Fonte: cache de download oficial")
            print(f"Data do download: {metadados['download_em']}")
            print(f"NCMs finais: {metadados['ncms_finais']}")
            print(f"SHA-256: {metadados['sha256']}")
        else:
            print(f"NCMs finais oficiais: {len(oficiais)}")
        plano = sincronizar(repositorio.engine, oficiais, dry_run=args.dry_run)
    except ErroConfiguracaoDados as exc:
        if "DATABASE_URL não foi configurada" in str(exc):
            print("Não foi possível comparar com PostgreSQL: DATABASE_URL não configurada.")
        else:
            print(f"Não foi possível comparar com PostgreSQL: {exc}")
        return 1
    except ErroSincronizacao as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError) as exc:
        origem = getattr(exc, "orig", None)
        detalhe = type(origem).__name__ if origem is not None else type(exc).__name__
        sqlstate = getattr(origem, "sqlstate", None)
        codigo = f" (SQLSTATE {sqlstate})" if sqlstate else ""
        print(f"Não foi possível comparar com PostgreSQL: {type(exc).__name__} / {detalhe}{codigo}.")
        print("Nenhuma alteração parcial foi mantida.")
        return 1

    print("PostgreSQL:")
    print(f"Registros atuais: {plano.registros_atuais}")
    print(f"Inserir: {len(plano.inserir)}")
    print(f"Iguais: {plano.iguais}")
    print(f"Atualizar: {len(plano.atualizar)}")
    print(f"Somente no banco: {len(plano.somente_no_banco)}")
    if plano.somente_no_banco:
        print("Amostra somente no banco: " + ", ".join(plano.somente_no_banco[:20]))
    print(f"Ignorados da fonte: {estatisticas.invalidos}")
    print("Duplicidades conflitantes: 0")
    if estatisticas.duplicidades:
        print(f"Duplicidades idênticas: {estatisticas.duplicidades}")
    for anterior, oficial in plano.atualizar[:20]:
        print(f"NCM: {oficial['ncm']}\nBanco: {anterior['descricao_oficial']}\n"
              f"Oficial: {oficial['descricao_oficial']}\nCampos diferentes: {', '.join(campos_diferentes(anterior, oficial))}")
    if args.dry_run:
        print("DRY-RUN: nenhuma escrita realizada.")
    else:
        print("Sincronização concluída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
