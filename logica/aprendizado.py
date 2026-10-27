"""Aprendizado de máquina: um modelo que olha um tabuleiro final e prevê a colocação.

A ideia: o alto elo ensina. Cada tabuleiro final das partidas de Challenger/Grão-Mestre
vira uma linha de números (quais campeões e com quantas estrelas, quantos de cada traço,
nível, itens) e a resposta é a colocação. O modelo (gradient boosting do scikit-learn)
aprende quais combinações colocam bem, inclusive as que ninguém jogou exatamente igual.

Cuidado ao ler o resultado: é o tabuleiro FINAL. Quem cai cedo tem tabuleiro fraco porque
caiu. Então o modelo aprende "como é um tabuleiro final forte", o que serve para comparar
comps (montadas por completo), não para dizer a chance no meio da partida.

Teste honesto: 20% das PARTIDAS ficam de fora do treino (não 20% dos tabuleiros, senão
os outros 7 jogadores da mesma partida "contariam" a resposta). Nessas partidas, o modelo
e a nota feita à mão (logica/montador.py) tentam ordenar os 8 jogadores, e comparamos.

Troca de um campeão (FICA/TROCA no overlay): o modelo não julga uma comp inventada, e sim
tabuleiros reais do alto elo parecidos com a comp, com um campeão trocado por outro. O teste
usa pares de tabuleiros das partidas separadas que diferem por um campeão só: o modelo troca
o campeão no primeiro e diz se fica melhor; conferimos com quem colocou melhor de verdade.
"""

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import joblib
import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from logica import montador

ARQUIVO_DO_MODELO = Path(__file__).resolve().parent.parent / "dados" / "modelo.joblib"
PARTE_DO_TESTE = 0.2
SEMENTE = 42                  # sorteio fixo: o mesmo banco dá sempre o mesmo teste
MINIMO_DE_PARTIDAS = 100      # menos que isso, o teste não diz nada
PARAMETROS = {"max_iter": 400, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 20,
              "l2_regularization": 1.0, "random_state": SEMENTE}
EXTRAS = ["nivel", "itens", "itens_no_carry", "estrelas", "custo"]
MARGEM_PARA_FICAR = 0.15      # o de fora da comp "fica" se a colocação prevista piorar no máximo isso
MINIMO_DE_PARECIDOS = 8       # tabuleiros reais parecidos com a comp, no mínimo, para opinar sobre uma troca
MAXIMO_DE_PARECIDOS = 150     # e no máximo (mais que isso só deixa a conta lenta)
ACERTO_MINIMO_DAS_TROCAS = 0.55  # abaixo disso no teste, o FICA/TROCA aparece como experimental


# ---------------------------------------------------------------- tabuleiro -> números

def colunas(catalogo):
    """Uma coluna por campeão (estrelas, 0 = não tem), uma por traço (quantidade) e as extras."""
    return ([f"campeao:{i}" for i in sorted(catalogo.campeoes)] +
            [f"traco:{i}" for i in sorted(catalogo.tracos)] + EXTRAS)


def _vetor(nomes_das_colunas, estrelas_por_campeao, quantidade_por_traco, extras):
    posicao = {nome: i for i, nome in enumerate(nomes_das_colunas)}
    linha = np.zeros(len(nomes_das_colunas))
    for id_campeao, estrelas in estrelas_por_campeao.items():
        if f"campeao:{id_campeao}" in posicao:
            linha[posicao[f"campeao:{id_campeao}"]] = estrelas
    for id_traco, quantidade in quantidade_por_traco.items():
        if f"traco:{id_traco}" in posicao:
            linha[posicao[f"traco:{id_traco}"]] = quantidade
    for nome, valor in extras.items():
        linha[posicao[nome]] = valor
    return linha


def vetor_do_tabuleiro(tabuleiro, nomes_das_colunas):
    estrelas = {u.campeao.id: u.estrelas for u in tabuleiro.unidades}
    tracos = {id_traco: quantidade for id_traco, (quantidade, _) in tabuleiro.tracos.items()}
    return _vetor(nomes_das_colunas, estrelas, tracos, _extras_do_tabuleiro(tabuleiro))


def _extras_do_tabuleiro(tabuleiro):
    return {
        "nivel": tabuleiro.nivel,
        "itens": sum(len(u.itens) for u in tabuleiro.unidades),
        "itens_no_carry": max((len(u.itens) for u in tabuleiro.unidades), default=0),
        "estrelas": sum(u.estrelas for u in tabuleiro.unidades),
        "custo": sum(u.campeao.custo for u in tabuleiro.unidades),
    }


def _vetor_com_troca(tabuleiro, sai, entra, nomes_das_colunas):
    """O mesmo tabuleiro com `entra` no lugar de `sai` (mesmas estrelas e itens; traços refeitos).
    Os traços partem dos do tabuleiro, então emblemas e augments continuam contando."""
    estrelas = {u.campeao.id: u.estrelas for u in tabuleiro.unidades}
    estrelas[entra.id] = estrelas.pop(sai.id)
    tracos = Counter({id_traco: quantidade for id_traco, (quantidade, _) in tabuleiro.tracos.items()})
    tracos.subtract(sai.tracos)
    tracos.update(entra.tracos)
    extras = _extras_do_tabuleiro(tabuleiro)
    extras["custo"] += entra.custo - sai.custo
    return _vetor(nomes_das_colunas, estrelas, +tracos, extras)  # o "+" tira os zeros e negativos


def vetor_da_comp(comp, modelo):
    """Uma comp sugerida vira um tabuleiro "típico" do alto elo: estrelas e itens que costumam ter no fim."""
    estrelas = {c.id: modelo.estrelas_tipicas.get(c.id, 1) for c in comp.campeoes}
    tracos = {t.traco.id: t.quantidade for t in comp.tracos}
    extras = {
        "nivel": len(comp.campeoes),
        "itens": modelo.itens_tipicos,
        "itens_no_carry": 3,
        "estrelas": sum(estrelas.values()),
        "custo": sum(c.custo for c in comp.campeoes),
    }
    return _vetor(modelo.colunas, estrelas, tracos, extras)


# ---------------------------------------------------------------- modelo

@dataclass
class Avaliacao:
    partidas_de_treino: int
    partidas_de_teste: int
    erro_do_modelo: float        # erro médio da colocação prevista (em posições)
    erro_sem_modelo: float       # chutando 4,5 para todo mundo
    acerto_top4_modelo: float    # % de tabuleiros em que acertou se ficou no top 4
    ordem_do_modelo: float       # correlação (0 a 1) entre a ordem prevista e a real, por partida
    ordem_da_regra: float        # o mesmo para a nota feita à mão (logica/montador.py)
    # troca de um campeão: % de pares (que diferem por um campeão) em que o modelo acertou quem colocou melhor
    acerto_das_trocas: float | None = None
    acerto_das_trocas_pelo_custo: float | None = None  # o mesmo chutando "o campeão mais caro é melhor"
    pares_de_trocas: int = 0


@dataclass
class Modelo:
    colunas: list
    colocacao: object            # HistGradientBoostingRegressor
    top4: object                 # HistGradientBoostingClassifier
    estrelas_tipicas: dict       # campeao_id -> estrelas mais comuns no fim (alto elo)
    itens_tipicos: float         # itens no tabuleiro final (mediana do alto elo)
    numero_set: str
    avaliacao: Avaliacao
    tabuleiros: int = 0

    def prever(self, linhas):
        """(colocação prevista, chance de top 4) para cada linha."""
        linhas = np.atleast_2d(linhas)
        return self.colocacao.predict(linhas), self.top4.predict_proba(linhas)[:, 1]

    def prever_comp(self, comp):
        colocacao, chance = self.prever(vetor_da_comp(comp, self))
        return float(colocacao[0]), float(chance[0])

    @property
    def trocas_confiaveis(self):
        acerto = self.avaliacao.acerto_das_trocas
        return acerto is not None and acerto >= ACERTO_MINIMO_DAS_TROCAS


@dataclass
class Troca:
    """O que fazer com um campeão que está em campo mas não é da comp alvo."""
    campeao: object
    fica: bool                 # True: pode ficar no time final no lugar de `no_lugar_de`
    no_lugar_de: object        # o campeão da comp que você ainda não tem e que ele substitui
    antes: float               # colocação prevista dos tabuleiros parecidos, como foram jogados
    depois: float              # e com ele no lugar de `no_lugar_de`
    tabuleiros: int            # quantos tabuleiros reais parecidos entraram na conta
    experimental: bool         # o teste das trocas não passou (ver Avaliacao.acerto_das_trocas)


def avaliar_trocas(comp, de_fora, ja_tem, modelo, tabuleiros):
    """Para cada campeão de fora da comp que está em campo: vale mantê-lo no time final?

    Pega os tabuleiros reais do alto elo (`tabuleiros`) parecidos com a comp (metade ou mais dos
    campeões dela) que têm um campeão que você ainda não tem (`ja_tem`: ids dos que você tem ou
    estão em campo). O modelo prevê cada um como foi jogado e com o seu campeão de fora no lugar.
    Cada vaga vai para quem perde menos com ela. Se a previsão média piorar até MARGEM_PARA_FICAR,
    ele FICA (você economiza o ouro do outro); senão é rotação: segure até achar `no_lugar_de`.
    Sem tabuleiros parecidos suficientes, não opina sobre aquela troca.
    """
    vagas = [c for c in comp.campeoes if c.id not in ja_tem]
    if not de_fora or not vagas:
        return []
    da_comp = {c.id for c in comp.campeoes}
    minimo_em_comum = max(3, len(da_comp) // 2)
    parecidos = [t for t in tabuleiros if len({u.campeao.id for u in t.unidades} & da_comp) >= minimo_em_comum]

    opcoes = []  # (campeão de fora, vaga, tabuleiros parecidos que têm a vaga e não têm o de fora)
    for vaga in vagas:
        com_a_vaga = [t for t in parecidos if any(u.campeao.id == vaga.id for u in t.unidades)]
        for campeao in de_fora:
            usaveis = [t for t in com_a_vaga if all(u.campeao.id != campeao.id for u in t.unidades)]
            if len(usaveis) >= MINIMO_DE_PARECIDOS:
                opcoes.append((campeao, vaga, usaveis[:MAXIMO_DE_PARECIDOS]))
    if not opcoes:
        return []

    linhas = []
    for campeao, vaga, usaveis in opcoes:
        linhas += [vetor_do_tabuleiro(t, modelo.colunas) for t in usaveis]
        linhas += [_vetor_com_troca(t, vaga, campeao, modelo.colunas) for t in usaveis]
    previstas, _ = modelo.prever(np.array(linhas))
    resultados, posicao = [], 0
    for campeao, vaga, usaveis in opcoes:
        quantos = len(usaveis)
        antes = float(previstas[posicao:posicao + quantos].mean())
        depois = float(previstas[posicao + quantos:posicao + 2 * quantos].mean())
        posicao += 2 * quantos
        resultados.append((depois - antes, campeao, vaga, antes, depois, quantos))

    trocas, usados, vagas_usadas = [], set(), set()
    for diferenca, campeao, vaga, antes, depois, quantos in sorted(resultados, key=lambda r: r[0]):
        if campeao.id in usados or vaga.id in vagas_usadas:
            continue
        usados.add(campeao.id)
        vagas_usadas.add(vaga.id)
        trocas.append(Troca(campeao, diferenca <= MARGEM_PARA_FICAR, vaga, antes, depois, quantos,
                            experimental=not modelo.trocas_confiaveis))
    return trocas


def _pares_que_diferem_por_um(tabuleiros):
    """Pares (tabuleiro A, campeão só de A, tabuleiro B, campeão só de B) de partidas diferentes,
    com colocações diferentes, em que o resto dos campeões é igual."""
    grupos = defaultdict(list)  # time sem um campeão -> [(tabuleiro, esse campeão)]
    for tabuleiro in tabuleiros:
        campeoes = {u.campeao.id: u.campeao for u in tabuleiro.unidades}
        for id_campeao, campeao in campeoes.items():
            grupos[frozenset(campeoes) - {id_campeao}].append((tabuleiro, campeao))
    pares = []
    for lista in grupos.values():
        for posicao, (a, sai) in enumerate(lista):
            for b, entra in lista[posicao + 1:]:
                if sai.id != entra.id and a.match_id != b.match_id and a.colocacao != b.colocacao:
                    pares.append((a, sai, b, entra))
    return pares


def _acerto_das_trocas(modelo_de_colocacao, teste, nomes):
    """Nos pares do teste que diferem por um campeão: o modelo troca o campeão no tabuleiro A e diz
    se melhora; acertou se B (que tem o outro campeão) colocou mesmo melhor. Também mede o chute
    "o campeão mais caro é melhor", para comparar. Devolve (acerto do modelo, acerto do chute, pares)."""
    pares = _pares_que_diferem_por_um(teste)
    if not pares:
        return None, None, 0
    linhas = [vetor_do_tabuleiro(a, nomes) for a, _, _, _ in pares]
    linhas += [_vetor_com_troca(a, sai, entra, nomes) for a, sai, _, entra in pares]
    previstas = modelo_de_colocacao.predict(np.array(linhas))
    melhora_prevista = previstas[len(pares):] < previstas[:len(pares)]   # colocação menor = melhor
    melhorou_de_verdade = np.array([b.colocacao < a.colocacao for a, _, b, _ in pares])
    mais_caro = np.array([entra.custo > sai.custo for _, sai, _, entra in pares])
    com_custo_diferente = np.array([entra.custo != sai.custo for _, sai, _, entra in pares])
    acerto_custo = float(np.mean(mais_caro[com_custo_diferente] == melhorou_de_verdade[com_custo_diferente])) \
        if com_custo_diferente.any() else None
    return float(np.mean(melhora_prevista == melhorou_de_verdade)), acerto_custo, len(pares)


def _separar_por_partida(tabuleiros):
    partidas = sorted({t.match_id for t in tabuleiros})
    random.Random(SEMENTE).shuffle(partidas)
    de_teste = set(partidas[:round(len(partidas) * PARTE_DO_TESTE)])
    treino = [t for t in tabuleiros if t.match_id not in de_teste]
    teste = [t for t in tabuleiros if t.match_id in de_teste]
    return treino, teste


def _ordem_por_partida(tabuleiros, notas):
    """Média, entre as partidas, da correlação entre a nota (menor = melhor) e a colocação real."""
    por_partida = {}
    for tabuleiro, nota in zip(tabuleiros, notas):
        por_partida.setdefault(tabuleiro.match_id, []).append((nota, tabuleiro.colocacao))
    correlacoes = []
    for pares in por_partida.values():
        if len(pares) >= 4:
            notas_da_partida, colocacoes = zip(*pares)
            rho = spearmanr(notas_da_partida, colocacoes).statistic
            if not np.isnan(rho):
                correlacoes.append(rho)
    return float(np.mean(correlacoes)) if correlacoes else 0.0


def _nota_da_regra(tabuleiro, catalogo):
    """A nota feita à mão do app (quanto maior, melhor) com sinal trocado, para 'menor = melhor'."""
    situacao = montador.Situacao(nivel=tabuleiro.nivel or 1)
    return -montador.pontuar([u.campeao for u in tabuleiro.unidades], situacao, catalogo)


def treinar(tabuleiros, catalogo, progresso=print):
    """Treina com os tabuleiros de alto elo, testa nas partidas separadas e devolve o Modelo.
    No fim, treina de novo com tudo (o teste já mediu a qualidade; mais dados = modelo melhor)."""
    partidas = len({t.match_id for t in tabuleiros})
    if partidas < MINIMO_DE_PARTIDAS:
        raise ValueError(f"Poucas partidas de alto elo ({partidas}); baixe pelo menos {MINIMO_DE_PARTIDAS}.")
    nomes = colunas(catalogo)
    treino, teste = _separar_por_partida(tabuleiros)
    x_treino = np.array([vetor_do_tabuleiro(t, nomes) for t in treino])
    x_teste = np.array([vetor_do_tabuleiro(t, nomes) for t in teste])
    y_treino = np.array([t.colocacao for t in treino])
    y_teste = np.array([t.colocacao for t in teste])

    progresso(f"Treinando com {len(treino)} tabuleiros e testando em {len(teste)}...")
    colocacao = HistGradientBoostingRegressor(**PARAMETROS).fit(x_treino, y_treino)
    top4 = HistGradientBoostingClassifier(**PARAMETROS).fit(x_treino, y_treino <= 4)

    previsto = colocacao.predict(x_teste)
    avaliacao = Avaliacao(
        partidas_de_treino=len({t.match_id for t in treino}),
        partidas_de_teste=len({t.match_id for t in teste}),
        erro_do_modelo=float(np.mean(np.abs(previsto - y_teste))),
        erro_sem_modelo=float(np.mean(np.abs(4.5 - y_teste))),
        acerto_top4_modelo=float(np.mean(top4.predict(x_teste) == (y_teste <= 4))),
        ordem_do_modelo=_ordem_por_partida(teste, previsto),
        ordem_da_regra=_ordem_por_partida(teste, [_nota_da_regra(t, catalogo) for t in teste]),
    )
    progresso("Testando a troca de um campeão...")
    avaliacao.acerto_das_trocas, avaliacao.acerto_das_trocas_pelo_custo, avaliacao.pares_de_trocas = \
        _acerto_das_trocas(colocacao, teste, nomes)

    progresso("Treinando o modelo final com todas as partidas...")
    x_tudo, y_tudo = np.vstack([x_treino, x_teste]), np.concatenate([y_treino, y_teste])
    colocacao = HistGradientBoostingRegressor(**PARAMETROS).fit(x_tudo, y_tudo)
    top4 = HistGradientBoostingClassifier(**PARAMETROS).fit(x_tudo, y_tudo <= 4)

    estrelas = {}
    for tabuleiro in tabuleiros:
        for unidade in tabuleiro.unidades:
            estrelas.setdefault(unidade.campeao.id, []).append(unidade.estrelas)
    return Modelo(
        colunas=nomes, colocacao=colocacao, top4=top4,
        estrelas_tipicas={i: round(median(lista)) for i, lista in estrelas.items()},
        itens_tipicos=float(median(sum(len(u.itens) for u in t.unidades) for t in tabuleiros)),
        numero_set=str(catalogo.numero_set), avaliacao=avaliacao, tabuleiros=len(tabuleiros),
    )


def salvar(modelo):
    joblib.dump(modelo, ARQUIVO_DO_MODELO)


def carregar(catalogo):
    """O modelo salvo, ou None se não existe ou é de outro set (aí precisa treinar de novo)."""
    if not ARQUIVO_DO_MODELO.exists():
        return None
    try:
        modelo = joblib.load(ARQUIVO_DO_MODELO)
    except Exception:  # arquivo de uma versão antiga do código
        return None
    if modelo.numero_set != str(catalogo.numero_set) or modelo.colunas != colunas(catalogo):
        return None
    return modelo
