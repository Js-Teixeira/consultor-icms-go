"""Descoberta de atos nos posts tributários da Secretaria da Economia."""

from __future__ import annotations

from bs4 import BeautifulSoup

from .fontes import ClienteOficial, ErroColeta, validar_url_oficial
from .modelos import AtoDescoberto
from .normalizacao import identificar_ato

URL_CATEGORIA = "https://goias.gov.br/economia/categoria/institucional/legislacao/"
MAX_PAGINAS = 10
LIMITE_MAX_PAGINAS = 100


def _posts_tributarios(html: str) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[str] = []
    for artigo in soup.select("article"):
        classes = artigo.get("class", [])
        if "category-tributaria" not in classes:
            continue
        link = artigo.select_one("h2.entry-title a[href]")
        if link:
            url = str(link["href"])
            validar_url_oficial(url)
            posts.append(url)
    proximo = soup.select_one("a.next.page-numbers[href]")
    url_proxima = str(proximo["href"]) if proximo else None
    if url_proxima:
        validar_url_oficial(url_proxima)
    return posts, url_proxima


def _atos_do_post(html: str, url_post: str) -> list[AtoDescoberto]:
    soup = BeautifulSoup(html, "html.parser")
    atos: list[AtoDescoberto] = []
    for paragrafo in soup.select("article .entry-content p"):
        for ancora in paragrafo.select("a[href]"):
            titulo = ancora.get_text(" ", strip=True)
            url_arquivo = str(ancora["href"])
            if not titulo:
                continue
            try:
                validar_url_oficial(url_arquivo)
            except ErroColeta:
                continue
            texto_paragrafo = paragrafo.get_text(" ", strip=True)
            ementa = texto_paragrafo[len(titulo):].strip() if texto_paragrafo.startswith(titulo) else ""
            ato = identificar_ato(titulo, ementa, url_post, url_arquivo)
            if ato:
                atos.append(ato)
    return atos


def descobrir_atos(cliente: ClienteOficial, *, ano: int | None = None, limite: int = 20,
                   max_paginas: int = MAX_PAGINAS) -> list[AtoDescoberto]:
    """Percorre páginas finitas da categoria oficial e deduplica identidades."""

    if limite < 1:
        raise ValueError("O limite deve ser maior que zero.")
    if not 1 <= max_paginas <= LIMITE_MAX_PAGINAS:
        raise ValueError(f"O número de páginas deve estar entre 1 e {LIMITE_MAX_PAGINAS}.")
    pagina: str | None = URL_CATEGORIA
    paginas_vistas: set[str] = set()
    vistos: set[tuple[str, str, int]] = set()
    encontrados: list[AtoDescoberto] = []
    while pagina and pagina not in paginas_vistas and len(paginas_vistas) < max_paginas:
        paginas_vistas.add(pagina)
        posts, pagina = _posts_tributarios(cliente.html(pagina))
        for url_post in posts:
            for ato in _atos_do_post(cliente.html(url_post), url_post):
                chave = (ato.tipo_ato, ato.numero, ato.ano)
                if chave in vistos or ano is not None and ato.ano != ano:
                    continue
                vistos.add(chave)
                encontrados.append(ato)
                if len(encontrados) >= limite:
                    return encontrados
    return encontrados
