"""Cliente HTTP limitado às fontes oficiais configuradas."""

from __future__ import annotations

import time
from urllib.parse import urljoin, urlparse

import httpx

HOSTS_OFICIAIS = {"goias.gov.br", "legisla.casacivil.go.gov.br"}
USER_AGENT = "ConsultaICMSGoias/1.0 (monitoramento legislativo; execucao manual)"
MAX_BYTES = 8_000_000


class ErroColeta(RuntimeError):
    """Falha controlada ao ler uma fonte oficial."""


def validar_url_oficial(url: str) -> None:
    """Impede que links da página desviem o coletor a endereços externos."""

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS_OFICIAIS or parsed.username or parsed.password:
        raise ErroColeta("URL fora das fontes oficiais autorizadas.")


class ClienteOficial:
    """HTTP com timeout, retry limitado e validação de redirects."""

    def __init__(self, client: httpx.Client | None = None, *, tentativas: int = 3) -> None:
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0), follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html, application/json;q=0.9, */*;q=0.5"},
        )
        self._proprio = client is None
        self.tentativas = max(1, min(tentativas, 3))

    def __enter__(self) -> ClienteOficial:
        return self

    def __exit__(self, *_: object) -> None:
        if self._proprio:
            self._client.close()

    def obter(self, url: str, *, params: dict[str, object] | None = None) -> httpx.Response:
        validar_url_oficial(url)
        for indice in range(self.tentativas):
            try:
                endereco = url
                parametros = params
                for _ in range(4):
                    resposta = self._client.get(endereco, params=parametros, follow_redirects=False)
                    validar_url_oficial(str(resposta.url))
                    if resposta.status_code not in {301, 302, 303, 307, 308}:
                        break
                    destino = resposta.headers.get("location")
                    if not destino:
                        raise ErroColeta("Redirect oficial sem destino.")
                    endereco = urljoin(str(resposta.url), destino)
                    validar_url_oficial(endereco)
                    parametros = None
                else:
                    raise ErroColeta("Fonte oficial excedeu o limite de redirects.")
                if len(resposta.content) > MAX_BYTES:
                    raise ErroColeta("Resposta oficial excede o tamanho permitido.")
                if resposta.status_code in {429, 500, 502, 503, 504} and indice + 1 < self.tentativas:
                    time.sleep(0.5 * (indice + 1))
                    continue
                resposta.raise_for_status()
                return resposta
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if indice + 1 >= self.tentativas:
                    raise ErroColeta("Tempo de resposta esgotado ou falha de rede na fonte oficial.") from exc
                time.sleep(0.5 * (indice + 1))
            except httpx.HTTPStatusError as exc:
                raise ErroColeta(f"Fonte oficial retornou HTTP {exc.response.status_code}.") from exc
        raise ErroColeta("Não foi possível ler a fonte oficial.")

    def html(self, url: str) -> str:
        resposta = self.obter(url)
        if "html" not in resposta.headers.get("content-type", "").lower():
            raise ErroColeta("Texto integral oficial não está disponível em HTML.")
        if not resposta.text.strip():
            raise ErroColeta("Página oficial vazia.")
        return resposta.text

    def json(self, url: str, *, params: dict[str, object] | None = None) -> dict:
        resposta = self.obter(url, params=params)
        try:
            dados = resposta.json()
        except ValueError as exc:
            raise ErroColeta("Resposta JSON inválida da fonte oficial.") from exc
        if not isinstance(dados, dict):
            raise ErroColeta("Resposta JSON inesperada da fonte oficial.")
        return dados
