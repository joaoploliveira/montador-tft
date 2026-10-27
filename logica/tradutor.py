"""Liga nomes de fora aos campeões, traços e itens do catálogo.

Serve para dois casos:
  - nomes internos da Riot nas partidas (ex.: 'DA_18_Varus'): são os próprios ids do catálogo;
  - textos lidos da tela pelo OCR, em português (ex.: 'Gume do Infinito', 'Krugue'),
    que podem vir com pequenos erros de leitura.
"""

from collections import Counter
from difflib import get_close_matches

SEMELHANCA_MINIMA = 0.75  # para textos do OCR com erro de leitura


def normalizar(texto):
    """'Kog'Maw' -> 'kogmaw' ; 'Gume do Infinito' -> 'gumedoinfinito'."""
    return "".join(letra for letra in (texto or "").lower() if letra.isalnum())


class _Tabela:
    """Índice de um tipo de objeto (campeões, traços ou itens): pelo id e pelo nome."""

    def __init__(self, objetos):
        objetos = list(objetos)
        self.por_id = {o.id: o for o in objetos}
        self.por_nome = {}
        for objeto in objetos:
            self.por_nome.setdefault(normalizar(objeto.nome), objeto)

    def buscar_texto(self, texto):
        chave = normalizar(texto)
        if not chave:
            return None
        if chave in self.por_nome:
            return self.por_nome[chave]
        parecidos = get_close_matches(chave, self.por_nome, n=1, cutoff=SEMELHANCA_MINIMA)
        return self.por_nome[parecidos[0]] if parecidos else None


class Tradutor:
    def __init__(self, catalogo):
        self.campeoes = _Tabela(catalogo.campeoes.values())
        self.tracos = _Tabela(catalogo.tracos.values())
        self.itens = _Tabela(catalogo.itens.values())
        self.nao_encontrados = Counter()

    def _anotar(self, achado, id_riot):
        if not achado:
            self.nao_encontrados[id_riot] += 1
        return achado

    # nomes internos (partidas da Riot)
    def campeao(self, id_riot):
        return self._anotar(self.campeoes.por_id.get(id_riot), id_riot)

    def traco(self, id_riot):
        return self._anotar(self.tracos.por_id.get(id_riot), id_riot)

    def item(self, id_riot):
        return self._anotar(self.itens.por_id.get(id_riot), id_riot)

    # textos da tela (OCR)
    def campeao_do_texto(self, texto):
        return self.campeoes.buscar_texto(texto)

    def traco_do_texto(self, texto):
        return self.tracos.buscar_texto(texto)

    def item_do_texto(self, texto):
        return self.itens.buscar_texto(texto)
