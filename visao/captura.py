"""Tira print da tela e recorta as regiões do HUD do TFT.

As regiões ficam em frações da tela (0 a 1), então funcionam em qualquer resolução
16:9. Elas foram calibradas com prints em 2560x1440.
"""

from PIL import Image

try:
    import mss
except ImportError:  # sem o pacote dá para usar só com prints salvos
    mss = None


def _abrir_mss():
    return (getattr(mss, "MSS", None) or mss.mss)()  # versões novas do mss usam MSS


def monitor_do_jogo():
    """O maior monitor, quando há mais de um: {'left', 'top', 'width', 'height'}."""
    with _abrir_mss() as tela:
        return max(tela.monitors[1:], key=lambda m: m["width"] * m["height"])


def capturar_tela():
    """Print do monitor do jogo como imagem PIL."""
    monitor = monitor_do_jogo()
    with _abrir_mss() as tela:
        bruto = tela.grab(monitor)
        return Image.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")


def capturar_regiao(esquerda, topo, largura, altura):
    """Print de um pedaço da tela (em pixels da tela), como imagem PIL. Bem mais rápido que a tela toda."""
    with _abrir_mss() as tela:
        bruto = tela.grab({"left": esquerda, "top": topo, "width": largura, "height": altura})
        return Image.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")


def abrir_print(caminho):
    return Image.open(caminho).convert("RGB")


def recortar(imagem, regiao):
    """regiao = (x0, y0, x1, y1) em frações da largura/altura."""
    largura, altura = imagem.size
    x0, y0, x1, y1 = regiao
    return imagem.crop((round(x0 * largura), round(y0 * altura), round(x1 * largura), round(y1 * altura)))
