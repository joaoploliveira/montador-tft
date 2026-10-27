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
"""

import random
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
    extras = {
        "nivel": tabuleiro.nivel,
        "itens": sum(len(u.itens) for u in tabuleiro.unidades),
        "itens_no_carry": max((len(u.itens) for u in tabuleiro.unidades), default=0),
        "estrelas": sum(u.estrelas for u in tabuleiro.unidades),
        "custo": sum(u.campeao.custo for u in tabuleiro.unidades),
    }
    return _vetor(nomes_das_colunas, estrelas, tracos, extras)


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
