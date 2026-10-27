"""Táticas tiradas das partidas de alto elo (Challenger/Grão-Mestre do BR).

A API da Riot mostra como cada jogador terminou a partida: colocação, nível final,
ouro que sobrou e o tabuleiro final (campeões, estrelas, itens e traços). Daqui sai:

- força de cada campeão e de cada traço: colocação média de quem terminou com ele;
- melhores itens de cada campeão: as builds de 3 itens com melhor colocação;
- quem costuma carregar os itens (para saber o "carry" de uma comp);
- o plano de jogo de uma comp: reroll (e em que nível), jogar no 8 ou subir para o 9.

Toda média usa a "média ajustada": com poucos jogos ela é puxada para 4,5 (a média
de qualquer partida), para um campeão com 2 jogos e 2 vitórias não parecer o melhor do jogo.
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from dados import banco
from logica.tracos import situacao_do_traco

FILA_RANQUEADA = 1100
COLOCACAO_NEUTRA = 4.5
JOGOS_DE_CONFIANCA = 10       # peso da média neutra na média ajustada
TIPOS_DE_BUILD = {"Completo"}  # itens que contam numa build (radiantes e artefatos não se montam)
MINIMO_DE_JOGOS_DA_BUILD = 3
ITENS_POR_BUILD = 3
REROLL_SE = 0.5               # metade dos tabuleiros com um campeão barato 3★ = comp de reroll
NIVEL_DO_REROLL = {1: 5, 2: 6, 3: 7}  # campeão de custo 1 rola no 5, de custo 2 no 6, de custo 3 no 7
SOBE_PARA_O_9_SE = 0.5        # metade terminando no 9+ = plano é chegar no 9


# ---------------------------------------------------------------- estatística

@dataclass
class Desempenho:
    """Colocações de um grupo de tabuleiros."""
    colocacoes: list = field(default_factory=list)

    def somar(self, colocacao):
        self.colocacoes.append(colocacao)

    @property
    def jogos(self):
        return len(self.colocacoes)

    @property
    def media(self):
        return sum(self.colocacoes) / self.jogos if self.jogos else COLOCACAO_NEUTRA

    @property
    def ajustada(self):
        soma = sum(self.colocacoes) + COLOCACAO_NEUTRA * JOGOS_DE_CONFIANCA
        return soma / (self.jogos + JOGOS_DE_CONFIANCA)

    @property
    def impacto(self):
        """Positivo = coloca melhor que a média. 1.0 = uma posição acima."""
        return COLOCACAO_NEUTRA - self.ajustada

    @property
    def top4(self):
        return sum(1 for c in self.colocacoes if c <= 4) / self.jogos if self.jogos else 0

    @property
    def vitorias(self):
        return sum(1 for c in self.colocacoes if c == 1) / self.jogos if self.jogos else 0


# ---------------------------------------------------------------- tabuleiros

@dataclass
class Unidade:
    campeao: object
    estrelas: int
    itens: list               # objetos Item (só os que existem no catálogo)

    @property
    def itens_de_build(self):
        return [i for i in self.itens if i.tipo in TIPOS_DE_BUILD]


@dataclass
class Tabuleiro:
    colocacao: int
    nivel: int
    ouro_restante: int | None
    ultima_rodada: int | None
    unidades: list            # Unidade
    tracos: dict              # traco_id -> (quantidade, nivel_ativo ou None)
    match_id: str = ""        # para separar partidas inteiras (treino x teste do modelo)
    puuid: str = ""

    def carry(self):
        """A unidade com mais itens (empate: a mais cara)."""
        com_itens = [u for u in self.unidades if u.itens]
        if not com_itens:
            return None
        return max(com_itens, key=lambda u: (len(u.itens), u.campeao.custo, u.estrelas))


_cache = {}


def ler_tabuleiros(catalogo):
    """Todos os tabuleiros ranqueados de alto elo do set. Fica guardado até chegarem partidas novas.
    As suas partidas (origem "minhas") ficam de fora: os outros jogadores dos seus lobbies não são alto elo."""
    conexao = banco.conectar()
    numero_set = int(float(catalogo.numero_set))
    total = conexao.execute(
        "SELECT COUNT(*) FROM partidas WHERE fila=? AND set_numero=? AND origem=?",
        (FILA_RANQUEADA, numero_set, banco.ORIGEM_ALTO_ELO),
    ).fetchone()[0]
    chave = (numero_set, total, len(catalogo.campeoes))
    if chave in _cache:
        conexao.close()
        return _cache[chave]

    linhas = conexao.execute(
        """SELECT p.* FROM participacoes p JOIN partidas m ON m.match_id = p.match_id
           WHERE m.fila = ? AND m.set_numero = ? AND m.origem = ?""",
        (FILA_RANQUEADA, numero_set, banco.ORIGEM_ALTO_ELO),
    ).fetchall()
    conexao.close()

    tabuleiros = _montar_tabuleiros(linhas, catalogo)
    _cache.clear()
    _cache[chave] = tabuleiros
    return tabuleiros


def meus_tabuleiros(catalogo):
    """Os seus tabuleiros finais nas ranqueadas do set, de todas as suas contas (do mais recente
    para o mais antigo). Vazio se você ainda não baixou suas partidas (aba Aprendizado)."""
    conexao = banco.conectar()
    puuids = list(banco.minhas_contas(conexao).values())
    if not puuids:
        conexao.close()
        return []
    linhas = conexao.execute(
        f"""SELECT p.* FROM participacoes p JOIN partidas m ON m.match_id = p.match_id
            WHERE p.puuid IN ({",".join("?" * len(puuids))}) AND m.fila = ? AND m.set_numero = ?
            ORDER BY m.data DESC""",
        (*puuids, FILA_RANQUEADA, int(float(catalogo.numero_set))),
    ).fetchall()
    conexao.close()
    return _montar_tabuleiros(linhas, catalogo)


def _montar_tabuleiros(linhas, catalogo):
    """Linhas da tabela participacoes -> Tabuleiro (só com o que existe no catálogo do set)."""
    tabuleiros = []
    for linha in linhas:
        unidades = []
        for unidade in json.loads(linha["unidades"]):
            campeao = catalogo.campeoes.get(unidade["id"])
            if campeao:
                itens = [catalogo.itens[i] for i in unidade.get("itens", []) if i in catalogo.itens]
                unidades.append(Unidade(campeao, unidade.get("estrelas") or 1, itens))
        tracos = {}
        for traco_riot in json.loads(linha["tracos"]):
            traco = catalogo.tracos.get(traco_riot["id"])
            if traco and traco.niveis:
                quantidade = traco_riot.get("unidades") or 0
                tracos[traco.id] = (quantidade, situacao_do_traco(traco, quantidade).nivel_ativo)
        tabuleiros.append(Tabuleiro(
            linha["colocacao"], linha["nivel"], linha["ouro_restante"], linha["ultima_rodada"], unidades, tracos,
            linha["match_id"], linha["puuid"],
        ))
    return tabuleiros


# ---------------------------------------------------------------- campeões e traços

def forca_dos_campeoes(catalogo, tabuleiros=None):
    """{campeao_id: Desempenho} de quem terminou com o campeão no tabuleiro."""
    resultado = defaultdict(Desempenho)
    for tabuleiro in tabuleiros if tabuleiros is not None else ler_tabuleiros(catalogo):
        for id_campeao in {u.campeao.id for u in tabuleiro.unidades}:
            resultado[id_campeao].somar(tabuleiro.colocacao)
    return dict(resultado)


def forca_dos_tracos(catalogo, tabuleiros=None):
    """{(traco_id, nivel_ativo): Desempenho}. Só traços ativos."""
    resultado = defaultdict(Desempenho)
    for tabuleiro in tabuleiros if tabuleiros is not None else ler_tabuleiros(catalogo):
        for id_traco, (_quantidade, nivel) in tabuleiro.tracos.items():
            if nivel:
                resultado[(id_traco, nivel)].somar(tabuleiro.colocacao)
    return dict(resultado)


def taxa_de_carry(catalogo, tabuleiros=None):
    """{campeao_id: fração dos tabuleiros em que ele segura 3 itens}. Alta = é carry."""
    com_tres, total = Counter(), Counter()
    for tabuleiro in tabuleiros if tabuleiros is not None else ler_tabuleiros(catalogo):
        for unidade in tabuleiro.unidades:
            total[unidade.campeao.id] += 1
            if len(unidade.itens) >= 3:
                com_tres[unidade.campeao.id] += 1
    return {id_: com_tres[id_] / total[id_] for id_ in total}


def desempenho_por_nivel(catalogo, tabuleiros=None):
    """{nivel_final: Desempenho}: mostra quanto vale chegar no 8, no 9..."""
    resultado = defaultdict(Desempenho)
    for tabuleiro in tabuleiros if tabuleiros is not None else ler_tabuleiros(catalogo):
        resultado[tabuleiro.nivel].somar(tabuleiro.colocacao)
    return dict(sorted(resultado.items()))


# ---------------------------------------------------------------- itens

@dataclass
class Build:
    itens: tuple              # ids dos itens (pode repetir, ex.: 2 Placas Gargolíticas)
    desempenho: Desempenho


def builds_do_campeao(catalogo, id_campeao, tabuleiros=None, quantidade=5):
    """As builds de 3 itens mais fortes do campeão, da melhor para a pior."""
    por_build = defaultdict(Desempenho)
    for tabuleiro in tabuleiros if tabuleiros is not None else ler_tabuleiros(catalogo):
        for unidade in tabuleiro.unidades:
            build = unidade.itens_de_build
            if unidade.campeao.id == id_campeao and len(build) == ITENS_POR_BUILD:
                por_build[tuple(sorted(i.id for i in build))].somar(tabuleiro.colocacao)
    confiaveis = [Build(itens, d) for itens, d in por_build.items() if d.jogos >= MINIMO_DE_JOGOS_DA_BUILD]
    return sorted(confiaveis, key=lambda b: b.desempenho.ajustada)[:quantidade]


def itens_do_campeao(catalogo, id_campeao, tabuleiros=None):
    """{item_id: Desempenho} de cada item no campeão (contando cada cópia uma vez por tabuleiro)."""
    resultado = defaultdict(Desempenho)
    for tabuleiro in tabuleiros if tabuleiros is not None else ler_tabuleiros(catalogo):
        for unidade in tabuleiro.unidades:
            if unidade.campeao.id == id_campeao:
                for id_item in {i.id for i in unidade.itens_de_build}:
                    resultado[id_item].somar(tabuleiro.colocacao)
    return dict(resultado)


def itens_recomendados(catalogo):
    """{campeao_id: [3 itens]}: a melhor build; sem build confiável, os 3 itens mais usados nele."""
    tabuleiros = ler_tabuleiros(catalogo)
    if not tabuleiros:
        return {}
    builds = defaultdict(lambda: defaultdict(Desempenho))
    usos = defaultdict(Counter)
    for tabuleiro in tabuleiros:
        for unidade in tabuleiro.unidades:
            build = unidade.itens_de_build
            usos[unidade.campeao.id].update(i.id for i in build)
            if len(build) == ITENS_POR_BUILD:
                builds[unidade.campeao.id][tuple(sorted(i.id for i in build))].somar(tabuleiro.colocacao)

    recomendados = {}
    for id_campeao in catalogo.campeoes:
        confiaveis = [(d.ajustada, itens) for itens, d in builds[id_campeao].items()
                      if d.jogos >= MINIMO_DE_JOGOS_DA_BUILD]
        if confiaveis:
            recomendados[id_campeao] = list(min(confiaveis)[1])
        elif usos[id_campeao]:
            recomendados[id_campeao] = [i for i, _ in usos[id_campeao].most_common(ITENS_POR_BUILD)]
    return recomendados


# ---------------------------------------------------------------- plano de jogo de uma comp

@dataclass
class Plano:
    estilo: str               # "Reroll", "Jogar no 8" ou "Subir para o 9"
    nivel_alvo: int           # nível em que a comp gasta o ouro (rola)
    tres_estrelas: list       # campeões que a comp costuma levar a 3★
    nivel_final_medio: float
    chegam_no_9: float        # fração que termina no nível 9 ou mais
    texto: str


def plano_da_comp(tabuleiros):
    """Olha como os tabuleiros de uma comp terminaram e descreve como jogar com ela."""
    jogos = len(tabuleiros)
    baratos_3 = Counter()
    com_reroll = 0
    for tabuleiro in tabuleiros:
        tres = {u.campeao.id: u.campeao for u in tabuleiro.unidades if u.estrelas >= 3 and u.campeao.custo <= 3}
        baratos_3.update(tres.values())
        com_reroll += bool(tres)
    nivel_medio = sum(t.nivel for t in tabuleiros) / jogos
    no_9 = sum(1 for t in tabuleiros if t.nivel >= 9) / jogos

    if com_reroll / jogos >= REROLL_SE:
        alvos = [c for c, n in baratos_3.most_common(3) if n / jogos >= 0.3] or [baratos_3.most_common(1)[0][0]]
        nivel = NIVEL_DO_REROLL[max(c.custo for c in alvos)]
        nomes = " e ".join(c.nome for c in alvos)
        return Plano("Reroll", nivel, alvos, nivel_medio, no_9,
                     f"Reroll no nível {nivel}: role devagar, só o ouro acima de 50, até {nomes} 3★. "
                     f"Depois suba de nível para fechar o time (nível final médio {nivel_medio:.1f}).")
    if no_9 >= SOBE_PARA_O_9_SE:
        return Plano("Subir para o 9", 9, [], nivel_medio, no_9,
                     f"Jogue forte no 8 (role em 4-1/4-2 para estabilizar) e suba para o 9 em 5-1/5-2 "
                     f"atrás dos 5 de custo: {no_9:.0%} dos jogadores chegaram ao 9.")
    return Plano("Jogar no 8", 8, [], nivel_medio, no_9,
                 f"Suba para o 8 em 4-1/4-2 e role até achar os 4 de custo 2★. "
                 f"Só {no_9:.0%} chegaram ao 9: não precisa forçar o nível 9.")
