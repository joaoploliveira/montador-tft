"""Seu desempenho: as suas partidas ranqueadas comparadas com o alto elo jogando a mesma comp.

Cada tabuleiro final (seu e do alto elo) recebe o nome da comp do mesmo jeito que as
comps meta ('Carry — Traço + Traço'); assim dá para comparar comp com comp.
"""

from collections import defaultdict
from dataclasses import dataclass

from logica import meta, taticas


@dataclass
class Resumo:
    jogos: int
    colocacao_media: float
    top4: float
    vitorias: float
    nivel_medio: float
    nivel_medio_alto_elo: float


@dataclass
class LinhaDaConta:
    conta: str
    jogos: int
    colocacao_media: float
    top4: float
    vitorias: float


@dataclass
class LinhaDaComp:
    nome: str
    jogos: int
    sua_colocacao: float
    seu_top4: float
    seu_nivel: float
    alto_elo_colocacao: float | None   # média ajustada do alto elo na mesma comp (None se ninguém jogou)
    alto_elo_jogos: int
    alto_elo_nivel: float | None


def _media(valores):
    valores = [v for v in valores if v]
    return sum(valores) / len(valores) if valores else 0.0


def resumo(meus, alto_elo):
    desempenho = taticas.Desempenho([t.colocacao for t in meus])
    return Resumo(
        jogos=desempenho.jogos,
        colocacao_media=desempenho.media,
        top4=desempenho.top4,
        vitorias=desempenho.vitorias,
        nivel_medio=_media(t.nivel for t in meus),
        nivel_medio_alto_elo=_media(t.nivel for t in alto_elo),
    )


def por_conta(meus, contas):
    """Uma linha por conta sua (`contas`: {Riot ID: puuid}), na ordem das contas."""
    linhas = []
    for riot_id, puuid in contas.items():
        desempenho = taticas.Desempenho([t.colocacao for t in meus if t.puuid == puuid])
        if desempenho.jogos:
            linhas.append(LinhaDaConta(riot_id, desempenho.jogos, desempenho.media, desempenho.top4,
                                       desempenho.vitorias))
    return linhas


def por_comp(meus, alto_elo, catalogo):
    """Uma linha por comp que você jogou, da mais jogada para a menos jogada."""
    do_alto_elo = defaultdict(list)
    for tabuleiro in alto_elo:
        do_alto_elo[meta.nome_da_comp(tabuleiro, catalogo)].append(tabuleiro)
    seus = defaultdict(list)
    for tabuleiro in meus:
        seus[meta.nome_da_comp(tabuleiro, catalogo) or "Sem itens (sem comp definida)"].append(tabuleiro)

    linhas = []
    for nome, tabuleiros in seus.items():
        seu = taticas.Desempenho([t.colocacao for t in tabuleiros])
        deles = do_alto_elo.get(nome, [])
        linhas.append(LinhaDaComp(
            nome=nome, jogos=seu.jogos, sua_colocacao=seu.media, seu_top4=seu.top4,
            seu_nivel=_media(t.nivel for t in tabuleiros),
            alto_elo_colocacao=taticas.Desempenho([t.colocacao for t in deles]).ajustada if deles else None,
            alto_elo_jogos=len(deles),
            alto_elo_nivel=_media(t.nivel for t in deles) if deles else None,
        ))
    return sorted(linhas, key=lambda linha: (-linha.jogos, linha.sua_colocacao))
