"""Leitura de texto com o OCR que já vem no Windows (sem instalar programa)."""

from dataclasses import dataclass

import winocr
from PIL import Image, ImageOps

IDIOMA = "pt-BR"
AMPLIAR = 2  # texto pequeno do HUD é lido melhor ampliado


@dataclass
class Linha:
    texto: str
    x: float  # posição dentro da imagem recortada (em pixels da imagem original)
    y: float
    largura: float = 0  # do começo da 1ª palavra ao fim da última


MARGEM = 30  # o OCR do Windows erra menos quando o texto não encosta na borda


def preparar(imagem, inverter=False, ampliar=AMPLIAR, limiar=0):
    """Cinza, ampliado e com margem.

    inverter: texto claro em fundo escuro vira escuro em fundo claro.
    limiar: se > 0, vira preto e branco (pixels mais claros que o limiar viram texto preto).
    """
    imagem = ImageOps.grayscale(imagem)
    imagem = imagem.resize((imagem.width * ampliar, imagem.height * ampliar), Image.LANCZOS)
    if limiar:
        imagem = imagem.point(lambda valor: 0 if valor > limiar else 255)
    elif inverter:
        imagem = ImageOps.invert(imagem)
    imagem = ImageOps.expand(imagem, border=MARGEM, fill=255 if (limiar or inverter) else 0)
    return imagem.convert("RGB")


def ler_linhas(imagem, inverter=False, ampliar=AMPLIAR, limiar=0):
    resultado = winocr.recognize_pil_sync(preparar(imagem, inverter, ampliar, limiar), IDIOMA)
    linhas = []
    for linha in resultado.get("lines", []):
        palavras = linha.get("words") or [{"bounding_rect": {"x": MARGEM, "y": MARGEM, "width": 0}}]
        primeira, ultima = palavras[0]["bounding_rect"], palavras[-1]["bounding_rect"]
        largura = (ultima["x"] + ultima.get("width", 0) - primeira["x"]) / ampliar
        linhas.append(Linha(linha["text"], (primeira["x"] - MARGEM) / ampliar, (primeira["y"] - MARGEM) / ampliar,
                            largura))
    return linhas


def ler_texto(imagem, inverter=False, ampliar=AMPLIAR, limiar=0):
    return " ".join(linha.texto for linha in ler_linhas(imagem, inverter, ampliar, limiar))
