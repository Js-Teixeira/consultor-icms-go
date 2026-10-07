"""Extração opcional de texto de arquivos Word oficiais legados."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .fontes import ErroColeta


def extrair_doc(conteudo: bytes) -> str:
    """Converte .doc com LibreOffice, em diretório temporário e tempo limitado."""

    executavel = shutil.which("libreoffice") or shutil.which("soffice")
    if executavel is None:
        raise ErroColeta("Conversor de arquivo .doc indisponível neste ambiente.")
    with tempfile.TemporaryDirectory(prefix="consulta-icms-doc-") as temporario:
        pasta = Path(temporario)
        origem = pasta / "ato.doc"
        destino = pasta / "ato.txt"
        origem.write_bytes(conteudo)
        try:
            resultado = subprocess.run(
                [executavel, f"-env:UserInstallation={ (pasta / 'perfil').as_uri() }",
                 "--headless", "--convert-to", "txt:Text (encoded):UTF8",
                 "--outdir", str(pasta), str(origem)],
                capture_output=True, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErroColeta("Falha ou tempo esgotado na conversão do arquivo .doc.") from exc
        if resultado.returncode != 0 or not destino.is_file():
            raise ErroColeta("Não foi possível extrair texto do arquivo .doc oficial.")
        try:
            texto = destino.read_text(encoding="utf-8-sig").strip()
        except UnicodeError as exc:
            raise ErroColeta("Texto convertido do arquivo .doc é inválido.") from exc
        if not texto:
            raise ErroColeta("Arquivo .doc oficial sem texto extraível.")
        return texto
