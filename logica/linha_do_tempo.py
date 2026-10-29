"""Linha do tempo das partidas gravadas (visao/gravacao.py): nível, ouro e tabuleiro estágio por estágio.

Cada gravação é ligada à partida da Riot pelo horário em que acabou; pela partida, chega-se à sua comp
(logica/suas_comps.py). Com várias partidas da mesma comp, dá para ver o caminho que você costuma fazer.
"""

from collections import Counter
from dataclasses import dataclass

MINUTOS_DE_TOLERANCIA = 10   # entre o fim da gravação e o fim da partida na API da Riot


@dataclass
class Momento:
    estagio: tuple       # (estágio, rodada) gravado, ex.: (4, 1)
    nivel: int | None
    ouro: int | None
    campeoes: list       # [(Campeao, estrelas)]: quem lutou na rodada anterior (painel de dano)


@dataclass
class LinhaDoEstagio:
    estagio: int
    partidas: int
    nivel_medio: float | None
    ouro_medio: float | None
    do_nucleo: float            # campeões da comp em campo, em média
    comuns: list                # [(nome, % das partidas)] dos campeões mais comuns em campo


def partida_da_gravacao(linhas, fim_das_partidas):
    """O match_id da partida que acabou perto do fim da gravação, ou None.
    `fim_das_partidas`: {match_id: fim em milissegundos} (banco.datas_das_partidas)."""
    fim_da_gravacao = linhas[-1]["hora"] * 1000
    perto = [(abs(fim - fim_da_gravacao), match_id) for match_id, fim in fim_das_partidas.items() if fim]
    distancia, match_id = min(perto, default=(None, None))
    return match_id if distancia is not None and distancia <= MINUTOS_DE_TOLERANCIA * 60_000 else None


def momentos(linhas, catalogo):
    """Um momento por estágio: a primeira rodada gravada de cada um (o planejamento do começo do estágio)."""
    por_estagio = {}
    for linha in linhas:
        estagio = tuple(linha["estagio"])
        if estagio[0] not in por_estagio:
            campeoes = [(catalogo.campeoes[i], e) for i, e in linha["painel"] if i in catalogo.campeoes]
            por_estagio[estagio[0]] = Momento(estagio, linha.get("nivel"), linha.get("ouro"), campeoes)
    return [por_estagio[e] for e in sorted(por_estagio)]


def _media(valores):
    valores = [v for v in valores if v is not None]
    return sum(valores) / len(valores) if valores else None


def por_estagio(partidas, nucleo, comuns=4):
    """Resumo de várias partidas da mesma comp, estágio por estágio.
    `partidas`: [[Momento]] (uma lista por partida gravada); `nucleo`: os Campeao da comp."""
    ids_do_nucleo = {c.id for c in nucleo}
    linhas = []
    for estagio in sorted({m.estagio[0] for partida in partidas for m in partida}):
        do_estagio = [m for partida in partidas for m in partida if m.estagio[0] == estagio]
        presenca = Counter(nome for m in do_estagio for nome in {c.nome for c, _ in m.campeoes})
        linhas.append(LinhaDoEstagio(
            estagio=estagio,
            partidas=len(do_estagio),
            nivel_medio=_media(m.nivel for m in do_estagio),
            ouro_medio=_media(m.ouro for m in do_estagio),
            do_nucleo=sum(len({c.id for c, _ in m.campeoes} & ids_do_nucleo) for m in do_estagio) / len(do_estagio),
            comuns=[(nome, n / len(do_estagio)) for nome, n in presenca.most_common(comuns)],
        ))
    return linhas
