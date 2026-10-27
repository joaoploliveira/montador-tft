"""Itens: o que dá para montar com os componentes que você tem e em quem colocar."""

from collections import Counter
from dataclasses import dataclass

TIPOS_DE_ITEM_UTEIS = {"Completo", "Emblema"}


@dataclass
class ItemParaCampeao:
    item: object
    status: str           # "Pode montar", "Falta 1 componente" ou "Faltam 2 componentes"
    faltando: list        # componentes que faltam


def tem_componentes(componentes, receita):
    """componentes: Counter {id_componente: quantidade}. Considera receitas com 2 iguais."""
    return all(componentes[c] >= n for c, n in Counter(receita).items())


def itens_que_pode_montar(componentes, catalogo):
    """Todos os itens que dá para montar agora (cada um isoladamente)."""
    possiveis = [
        item for item in catalogo.receitas()
        if item.tipo in TIPOS_DE_ITEM_UTEIS and tem_componentes(componentes, item.componentes)
    ]
    return sorted(possiveis, key=lambda item: (item.tipo, item.nome))


def _usar_componentes(sobra, receita):
    """Gasta da `sobra` os componentes da receita que tiver e devolve os que faltaram."""
    faltando = []
    for componente in receita:
        if sobra[componente] > 0:
            sobra[componente] -= 1
        else:
            faltando.append(componente)
    return faltando


def itens_para_campeao(campeao, componentes, catalogo):
    """Itens recomendados do campeão, com o que falta para cada um.

    Os itens são vistos em ordem e cada um gasta os componentes que usa; assim,
    num item repetido (ex.: 2 Gargoyle), o segundo só conta o que sobrou do primeiro.
    """
    sobra = Counter(componentes)
    resultado = []
    for id_item in campeao.itens_recomendados:
        item = catalogo.itens.get(id_item)
        if not item or len(item.componentes) != 2:
            continue
        faltando = [catalogo.itens[c] for c in _usar_componentes(sobra, item.componentes) if c in catalogo.itens]
        status = {0: "Pode montar", 1: "Falta 1 componente"}.get(len(faltando), "Faltam 2 componentes")
        resultado.append(ItemParaCampeao(item, status, faltando))
    return resultado


def carregadores(comp, quantidade=2):
    """Os campeões que mais merecem itens no time.

    Quem mais segura 3 itens nas partidas de alto elo (taxa_de_itens); sem dados, os mais caros.
    """
    return sorted(comp.campeoes, key=lambda c: (-c.taxa_de_itens, -c.custo, c.nome))[:quantidade]


# ---------------------------------------------------------------- plano de itens da comp alvo

CARREGADORES_NO_PLANO = 3  # carry principal, segundo carry e (em geral) o tanque


@dataclass
class PlanoDeItens:
    montar: list      # (item, campeão): dá para montar agora, cada componente usado uma vez só
    quase: list       # (item, campeão, componente que falta)
    mais_util: object  # componente que mais ajuda a fechar itens (para carrossel e bigorna), ou None
    sobrando: list    # componentes que não entram em nenhum item do plano


def itens_pedidos(comp, catalogo):
    """Os itens da build de cada carregador, em ordem de prioridade: (item, campeão).
    Repetidos ficam (ex.: 2 Gargoyle), porque alguns campeões usam."""
    pedidos = []
    for campeao in carregadores(comp, CARREGADORES_NO_PLANO):
        for id_item in campeao.itens_recomendados:
            item = catalogo.itens.get(id_item)
            if item and len(item.componentes) == 2:
                pedidos.append((item, campeao))
    return pedidos


def plano_de_itens(comp, componentes, catalogo):
    """Divide os componentes que você tem entre os itens da comp.

    1. Primeiro, o que já dá para montar, na ordem de prioridade (carry principal antes).
    2. Depois, os itens que faltam guardam os componentes que já têm, também em ordem;
       assim um componente nunca é prometido para dois itens.
    """
    sobra = Counter(componentes)
    montar, restantes = [], []
    for item, campeao in itens_pedidos(comp, catalogo):
        if tem_componentes(sobra, item.componentes):
            sobra.subtract(item.componentes)
            montar.append((item, campeao))
        else:
            restantes.append((item, campeao))

    quase, falta_contagem = [], Counter()
    for item, campeao in restantes:
        faltando = _usar_componentes(sobra, item.componentes)
        if len(faltando) == 1:
            quase.append((item, campeao, catalogo.itens.get(faltando[0])))
        # o que falta para itens "quase" pesa mais do que para itens começando do zero
        for componente in faltando:
            falta_contagem[componente] += 2 if len(faltando) == 1 else 1

    mais_util = catalogo.itens.get(falta_contagem.most_common(1)[0][0]) if falta_contagem else None
    sobrando = [catalogo.itens[c] for c, n in sobra.items() for _ in range(n) if n > 0 and c in catalogo.itens]
    return PlanoDeItens(montar, quase, mais_util, sobrando)


# ---------------------------------------------------------------- escolha na bigorna

@dataclass
class Escolha:
    item: object
    motivo: str


def melhor_opcao(opcoes, comp, componentes, catalogo):
    """Qual opção pegar numa bigorna (ou no carrossel), entre itens completos e componentes.

    Ordem de preferência:
      1. item completo que está na build de um carregador e ainda não dá para montar
      2. componente que já fecha um item da build
      3. item completo da build (mesmo que já desse para montar: poupa componentes)
      4. o componente que mais ajuda a fechar itens (plano.mais_util)
      5. componente que entra em alguma receita da build
      6. qualquer item completo (fora da build, mas é um item pronto)
    Devolve uma Escolha, ou None se não houver opções.
    """
    plano = plano_de_itens(comp, componentes, catalogo)
    pedidos = itens_pedidos(comp, catalogo)
    dono = {}  # id do item -> primeiro carregador que pede
    for item, campeao in pedidos:
        dono.setdefault(item.id, campeao)
    faltam_montar = {item.id for item, _ in pedidos} - {item.id for item, _ in plano.montar}
    # componente -> (posição na prioridade, item, campeão) do 1º item ainda não montado que o usa
    primeiro_que_usa = {}
    for posicao, (item, campeao) in enumerate(pedidos):
        if item.id in faltam_montar:
            for componente in item.componentes:
                primeiro_que_usa.setdefault(componente, (posicao, item, campeao))

    def prioridade(opcao):
        """No empate, ganha a opção que serve ao item mais importante (carry principal primeiro)."""
        return primeiro_que_usa.get(opcao.id, (len(pedidos),))[0]

    def avaliar(opcao):
        if opcao.tipo != "Componente":
            if opcao.id in faltam_montar:
                return 6, f"Item da build de {dono[opcao.id].nome}"
            if opcao.id in dono:
                return 4, f"Item da build de {dono[opcao.id].nome} (poupa componentes)"
            return 1, "Item pronto, mas fora da build da comp"
        com_ela = plano_de_itens(comp, componentes + Counter([opcao.id]), catalogo)
        ja_montava = list(plano.montar)  # com repetidos (2 Gargoyle), cada par já montado só "cancela" um
        novos = []
        for par in com_ela.montar:
            if par in ja_montava:
                ja_montava.remove(par)
            else:
                novos.append(par)
        if novos:
            item, campeao = novos[0]
            return 5, f"Fecha {item.nome} para {campeao.nome}"
        if plano.mais_util and opcao.id == plano.mais_util.id:
            return 3, "O componente que mais falta nos itens da comp"
        if opcao.id in primeiro_que_usa:
            _, item, campeao = primeiro_que_usa[opcao.id]
            return 2, f"Entra em {item.nome} para {campeao.nome}"
        return 0, "Não entra em nenhum item da comp"

    avaliadas = [(avaliar(opcao), prioridade(opcao), posicao, opcao) for posicao, opcao in enumerate(opcoes) if opcao]
    if not avaliadas:
        return None
    (_, motivo), _, _, opcao = max(avaliadas, key=lambda a: (a[0][0], -a[1], -a[2]))
    return Escolha(opcao, motivo)


@dataclass
class Frase:
    tipo: str             # montar, quase ou util
    texto: str
    item: object          # o item (montar/quase) ou o componente (util)
    campeao: object = None
    falta: object = None  # componente que falta (quase)


def frases_do_plano(plano):
    """O plano em frases curtas, para o app e o overlay (que usa também os itens, para os ícones)."""
    frases = [Frase("montar", f"Monte {item.nome} → {campeao.nome}", item, campeao)
              for item, campeao in plano.montar]
    frases += [Frase("quase", f"Quase: {item.nome} → {campeao.nome} (falta {falta.nome})", item, campeao, falta)
               for item, campeao, falta in plano.quase if falta]
    if plano.mais_util:
        frases.append(Frase("util", f"Carrossel/bigorna: prefira {plano.mais_util.nome}", plano.mais_util))
    return frases
