"""Guarda um print da tela quando a leitura dá algo que não fecha, para conferir depois.

Os prints ficam em dados/diagnostico/ (fora do git), com um .txt do que foi lido.
No máximo um por minuto, e só os mais recentes ficam guardados.
"""

import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "dados" / "diagnostico"
INTERVALO = 60          # segundos entre um print e outro
MAXIMO_DE_PRINTS = 30   # os mais antigos são apagados

_ultimo = 0.0


def guardar(imagem, motivo, detalhes):
    """Salva `imagem` (PIL) e `detalhes` (texto). Devolve o caminho do print, ou None se não salvou agora."""
    global _ultimo
    if imagem is None or time.time() - _ultimo < INTERVALO:
        return None
    _ultimo = time.time()
    PASTA.mkdir(parents=True, exist_ok=True)
    nome = f"{time.strftime('%Y%m%d-%H%M%S')}-{motivo}"
    imagem.save(PASTA / f"{nome}.png")
    (PASTA / f"{nome}.txt").write_text(detalhes, encoding="utf-8")
    for antigo in sorted(PASTA.glob("*.png"))[:-MAXIMO_DE_PRINTS]:
        antigo.unlink(missing_ok=True)
        antigo.with_suffix(".txt").unlink(missing_ok=True)
    return PASTA / f"{nome}.png"
