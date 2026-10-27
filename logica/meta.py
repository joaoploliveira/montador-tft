"""Comps meta: agrupa os tabuleiros finais das partidas de alto elo e calcula o desempenho.

Cada tabuleiro é identificado pelo "carry" (o campeão com mais itens) mais os 2
traços principais. Tabuleiros com a mesma identidade viram uma comp, com
colocação média, % de top 4, % de vitória, os campeões mais frequentes, a build
do carry e o plano de jogo (reroll, jogar no 8 ou subir para o 9).
"""

from collections import Counter, defaultdict

from logica import taticas
from logica.montador import avaliar

MINIMO_DE_JOGOS = 5          # comps com menos jogos que isso ficam de fora
FREQUENCIA_MINIMA = 0.4      # campeão entra na comp se aparece em 40% dos tabuleiros dela
ESSENCIAL = 0.75             # aparece em 75% ou mais: é peça central da comp
MAXIMO_DE_CAMPEOES = 9


def _identidade(tabuleiro, catalogo):
    """(id do carry, 2 traços principais) ou None se o tabuleiro não tem itens."""
    carry = tabuleiro.carry()
    if not carry:
        return None
    ativos = []
    for id_traco, (quantidade, nivel) in tabuleiro.tracos.items():
        traco = catalogo.tracos[id_traco]
        if nivel and not traco.unico:
            estilo = traco.estilos[traco.niveis.index(nivel)]
            ativos.append((estilo, quantidade, id_traco))
    principais = tuple(sorted(id_traco for _, _, id_traco in sorted(ativos, reverse=True)[:2]))
    return carry.campeao.id, principais


def nome_da_comp(tabuleiro, catalogo):
    """O nome da comp de um tabuleiro, igual ao das comps meta ('Carry — Traço + Traço'), ou None."""
    identidade = _identidade(tabuleiro, catalogo)
    if not identidade:
        return None
    id_carry, ids_tracos = identidade
    nomes_tracos = " + ".join(catalogo.tracos[i].nome for i in ids_tracos)
    carry = catalogo.campeoes[id_carry]
    return f"{carry.nome} — {nomes_tracos}" if nomes_tracos else carry.nome


def _build_do_carry(do_grupo, carry):
    """A build de 3 itens que o carry mais usou nessa comp (nomes dos itens)."""
    builds = Counter()
    for tabuleiro in do_grupo:
        unidade = next(u for u in tabuleiro.unidades if u.campeao.id == carry.id)
        if len(unidade.itens_de_build) == taticas.ITENS_POR_BUILD:
            builds[tuple(sorted(i.nome for i in unidade.itens_de_build))] += 1
    return list(builds.most_common(1)[0][0]) if builds else []


def comps_meta(situacao, catalogo):
    """Devolve (comps avaliadas contra o que você tem, resumo dos dados)."""
    tabuleiros = taticas.ler_tabuleiros(catalogo)
    grupos = defaultdict(list)
    for tabuleiro in tabuleiros:
        identidade = _identidade(tabuleiro, catalogo)
        if identidade:
            grupos[identidade].append(tabuleiro)

    comps = []
    for (id_carry, ids_tracos), do_grupo in grupos.items():
        jogos = len(do_grupo)
        if jogos < MINIMO_DE_JOGOS:
            continue
        frequencia = Counter(i for t in do_grupo for i in {u.campeao.id for u in t.unidades})
        frequentes = [i for i, n in frequencia.most_common(MAXIMO_DE_CAMPEOES) if n / jogos >= FREQUENCIA_MINIMA]

        carry = catalogo.campeoes[id_carry]
        nomes_tracos = " + ".join(catalogo.tracos[i].nome for i in ids_tracos)
        comp = avaliar(
            [catalogo.campeoes[i] for i in frequentes], situacao, catalogo,
            nome=f"{carry.nome} — {nomes_tracos}" if nomes_tracos else carry.nome, origem="Meta",
        )
        desempenho = taticas.Desempenho([t.colocacao for t in do_grupo])
        comp.estatisticas = {
            "jogos": jogos,
            "colocacao_media": round(desempenho.media, 2),
            "media_ajustada": round(desempenho.ajustada, 2),
            "top4": desempenho.top4,
            "vitoria": desempenho.vitorias,
            "carry": carry.nome,
            "itens_do_carry": _build_do_carry(do_grupo, carry),
            "essenciais": [catalogo.campeoes[i].nome for i in frequentes if frequencia[i] / jogos >= ESSENCIAL],
            "plano": taticas.plano_da_comp(do_grupo),
        }
        comps.append(comp)

    comps.sort(key=lambda comp: comp.estatisticas["media_ajustada"])
    resumo = {"tabuleiros": len(tabuleiros), "partidas": len(tabuleiros) // 8}
    return comps, resumo
