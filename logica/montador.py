"""Sugere composições a partir do que o jogador tem em jogo.

Ideia: monta times campeão por campeão (busca em feixe), dando nota para cada time.
A nota soma:
  + traços ativos (quanto mais alto o nível do traço, mais pontos)
  + campeões que você já tem (mais ainda se estiverem com 2★ ou 3★)
  + o que as partidas de alto elo mostram: campeões e traços que colocam bem valem mais
  - campeões que faltam, pesando pela chance de achar no seu nível
Os pesos ficam todos aqui em cima, para facilitar ajustes.
"""

from collections import Counter
from dataclasses import dataclass, field

from logica.loja import chance_na_loja, copias_por_estrela
from logica.tracos import situacao_do_traco, tracos_do_time

# ---------------------------------------------------------------- pesos

PONTOS_POR_ESTILO = {1: 1.0, 2: 2.0, 3: 3.5, 4: 5.0}  # bronze, prata, ouro, prismático
PONTOS_TRACO_UNICO = 0.5        # traços de um campeão só ativam sozinhos, valem pouco
PESO_PROGRESSO = 0.4            # crédito parcial por estar perto do próximo nível
BONUS_JA_TEM = 1.5              # por campeão que você já tem
BONUS_POR_ESTRELA = 0.75        # extra por estrela acima de 1★
PONTOS_POR_CUSTO = 0.15         # campeões mais caros são mais fortes
PENALIDADE_FALTANDO = 0.5       # base por campeão que falta comprar
PENALIDADE_RARIDADE = 2.0       # extra para custos que aparecem pouco na loja no seu nível
PENALIDADE_INDISPONIVEL = 3.0   # campeão que ainda não aparece na loja no seu nível
PESO_DADOS_CAMPEAO = 0.8        # x impacto do campeão no alto elo (posições acima da média)
PESO_DADOS_TRACO = 1.0          # x impacto do traço naquele nível no alto elo
PASSOS_DA_BUSCA_FORA_DA_COMP = 300_000  # combinações testadas, no máximo, para achar quem mais está em campo
FOLGA_MAXIMA_FORA_DA_COMP = 2           # traços no painel sem campeão (emblema equipado, augment de traço)

LARGURA_DO_FEIXE = 60
PENALIDADE_REPETIDO = 1.2       # para variar: campeão (que você não tem) já usado numa sugestão anterior
DIFERENCA_MINIMA = 2            # comps sugeridas precisam diferir em pelo menos 2 campeões


@dataclass
class Situacao:
    """O que o jogador tem agora."""
    nivel: int
    unidades: dict = field(default_factory=dict)   # campeao_id -> estrelas
    emblemas: list = field(default_factory=list)   # ids dos traços dos emblemas que tem
    fixos: list = field(default_factory=list)      # campeões que quer obrigatoriamente no time


@dataclass
class CompAvaliada:
    nome: str
    campeoes: list
    tracos: list          # TracoNoTime
    pontuacao: float
    tem: list             # campeões que você já tem
    faltam: list          # campeões que faltam comprar
    origem: str = "Algoritmo"
    estatisticas: dict = field(default_factory=dict)  # comps meta: colocação média, plano de jogo etc.

    @property
    def porcentagem_que_tem(self):
        return len(self.tem) / len(self.campeoes) if self.campeoes else 0


# ---------------------------------------------------------------- nota de um time

class _Notas:
    """Pontos de cada campeão e de cada traço, calculados uma vez por situação.

    Assim a busca só soma valores prontos em vez de recontar o time inteiro a cada passo.
    """

    def __init__(self, situacao, catalogo):
        self.situacao, self.catalogo = situacao, catalogo
        self.do_campeao = {id_: self._campeao(c) for id_, c in catalogo.campeoes.items()}
        self._dos_tracos = {}

    def _campeao(self, campeao):
        situacao, catalogo = self.situacao, self.catalogo
        pontos = PONTOS_POR_CUSTO * campeao.custo + PESO_DADOS_CAMPEAO * campeao.impacto
        estrelas = situacao.unidades.get(campeao.id)
        if estrelas:
            return pontos + BONUS_JA_TEM + BONUS_POR_ESTRELA * (estrelas - 1)
        chances = catalogo.chances_no_nivel(situacao.nivel)
        chance_do_custo = chances.get(campeao.custo, 0.0)
        if chance_do_custo == 0:
            return pontos - PENALIDADE_INDISPONIVEL
        # comparado ao custo mais comum no seu nível: 1.0 = o mais fácil de achar
        facilidade = chance_do_custo / max(chances.values())
        return pontos - PENALIDADE_FALTANDO - PENALIDADE_RARIDADE * (1 - facilidade)

    def traco(self, id_traco, quantidade):
        chave = (id_traco, quantidade)
        if chave not in self._dos_tracos:
            self._dos_tracos[chave] = self._traco(id_traco, quantidade)
        return self._dos_tracos[chave]

    def _traco(self, id_traco, quantidade):
        traco = self.catalogo.tracos.get(id_traco)
        if not traco or not traco.niveis or quantidade <= 0:
            return 0.0
        situacao = situacao_do_traco(traco, quantidade)
        pontos = 0.0
        if situacao.ativo:
            pontos += PONTOS_TRACO_UNICO if traco.unico else PONTOS_POR_ESTILO.get(situacao.estilo, 1.0)
            pontos += PESO_DADOS_TRACO * self.catalogo.impacto_dos_tracos.get((traco.id, situacao.nivel_ativo), 0.0)
        if situacao.proximo_nivel:
            estilo_seguinte = traco.estilos[traco.niveis.index(situacao.proximo_nivel)]
            pontos += PESO_PROGRESSO * PONTOS_POR_ESTILO.get(estilo_seguinte, 1.0) * quantidade / situacao.proximo_nivel
        return pontos

    def contagem(self, ids):
        """Traços do time (cada campeão conta uma vez) mais os emblemas."""
        contagem = Counter(self.situacao.emblemas)
        for id_ in set(ids):
            contagem.update(self.catalogo.campeoes[id_].tracos)
        return contagem

    def do_time(self, ids):
        contagem = self.contagem(ids)
        return sum(self.do_campeao[i] for i in set(ids)) + sum(self.traco(t, q) for t, q in contagem.items())

    def ganho(self, contagem, id_campeao):
        """Quanto a nota sobe ao colocar o campeão num time com essa contagem de traços."""
        ganho = self.do_campeao[id_campeao]
        for id_traco in self.catalogo.campeoes[id_campeao].tracos:
            atual = contagem.get(id_traco, 0)
            ganho += self.traco(id_traco, atual + 1) - self.traco(id_traco, atual)
        return ganho


def pontuar(campeoes, situacao, catalogo):
    return _Notas(situacao, catalogo).do_time([c.id for c in campeoes])


def avaliar(campeoes, situacao, catalogo, nome=None, origem="Algoritmo", notas=None):
    """Monta o resumo de um time: traços, o que você tem, o que falta e a nota."""
    campeoes = sorted(campeoes, key=lambda c: (c.custo, c.nome))
    tracos = tracos_do_time(campeoes, catalogo, situacao.emblemas)
    if nome is None:
        principais = [t.traco.nome for t in tracos if t.ativo and not t.traco.unico][:2]
        nome = " + ".join(principais) or "Time sem traços"
    notas = notas or _Notas(situacao, catalogo)
    return CompAvaliada(
        nome=nome,
        campeoes=campeoes,
        tracos=tracos,
        pontuacao=round(notas.do_time([c.id for c in campeoes]), 1),
        tem=[c for c in campeoes if c.id in situacao.unidades],
        faltam=[c for c in campeoes if c.id not in situacao.unidades],
        origem=origem,
    )


# ---------------------------------------------------------------- busca

def _buscar_time(notas, tamanho, ja_usados):
    """Uma busca em feixe. Devolve os times finais, do melhor pro pior.

    Cada time do feixe guarda a contagem de traços e a nota; ao tentar um campeão novo,
    só se soma o ganho dele (`notas.ganho`), sem recalcular o time todo.
    """
    situacao, campeoes = notas.situacao, notas.catalogo.campeoes
    fixos = frozenset(i for i in situacao.fixos if i in campeoes)

    def penalidade(id_campeao):
        return PENALIDADE_REPETIDO if id_campeao in ja_usados and id_campeao not in situacao.unidades else 0.0

    feixe = [(fixos, notas.contagem(fixos), notas.do_time(fixos) - sum(map(penalidade, fixos)))]
    for _passo in range(tamanho - len(fixos)):
        candidatos = {}
        for time, contagem, nota in feixe:
            for id_campeao in campeoes:
                if id_campeao in time:
                    continue
                novo = time | {id_campeao}
                if novo not in candidatos:
                    candidatos[novo] = (nota + notas.ganho(contagem, id_campeao) - penalidade(id_campeao),
                                        contagem, id_campeao)
        melhores = sorted(candidatos.items(), key=lambda item: item[1][0], reverse=True)[:LARGURA_DO_FEIXE]
        feixe = []
        for time, (nota, contagem, id_campeao) in melhores:
            nova_contagem = Counter(contagem)
            nova_contagem.update(campeoes[id_campeao].tracos)
            feixe.append((time, nova_contagem, nota))
    return [time for time, _, _ in feixe]


def sugerir_comps(situacao, catalogo, quantidade=5, tamanho=None):
    """Devolve as melhores comps para a situação, diferentes entre si.

    Roda uma busca por sugestão; a cada rodada, os campeões já sugeridos perdem
    pontos, para a próxima busca explorar outros caminhos.
    """
    tamanho = tamanho or max(situacao.nivel, len(situacao.fixos), 1)
    notas = _Notas(situacao, catalogo)
    escolhidos, ja_usados = [], set()
    for _rodada in range(quantidade):
        for time in _buscar_time(notas, tamanho, ja_usados):
            if all(len(time - outro) >= DIFERENCA_MINIMA for outro in escolhidos):
                escolhidos.append(time)
                ja_usados |= time
                break

    comps = [avaliar([catalogo.campeoes[i] for i in time], situacao, catalogo, notas=notas) for time in escolhidos]
    return sorted(comps, key=lambda comp: comp.pontuacao, reverse=True)


def combina_com_tabuleiro(comp, tracos_lidos):
    """Quanto a comp combina com os traços do seu tabuleiro (lidos do jogo). Devolve (pontos, nomes dos traços).

    Cada traço conta até a quantidade que você tem: com Florescer 3 na tela, uma comp com
    Florescer 5 soma 3 e uma com Florescer 2 soma 2. Traços de um campeão só não contam.
    """
    pontos, nomes = 0, []
    for traco_no_time in comp.tracos:
        quantidade = tracos_lidos.get(traco_no_time.traco.id, 0)
        if quantidade and not traco_no_time.traco.unico:
            pontos += min(quantidade, traco_no_time.quantidade)
            nomes.append(traco_no_time.traco.nome)
    return pontos, nomes


def mais_parecida_com_tabuleiro(comps, tracos_lidos):
    """A comp que mais combina com o seu tabuleiro, ou None se nenhuma usa os seus traços.

    No empate, ganha a que leva esses traços mais longe (ex.: Florescer 5 em vez de 3,
    porque ali ele é o foco e não um detalhe); se ainda empatar, a que vem primeiro.
    """
    melhor, melhor_nota = None, (0, 0)
    for comp in comps:
        pontos, _ = combina_com_tabuleiro(comp, tracos_lidos)
        investimento = sum(t.quantidade for t in comp.tracos if t.traco.id in tracos_lidos and not t.traco.unico)
        if pontos and (pontos, investimento) > melhor_nota:
            melhor, melhor_nota = comp, (pontos, investimento)
    return melhor


def provaveis_no_tabuleiro(campeoes, tracos_lidos, catalogo):
    """Dos `campeoes` (os da comp alvo), quais provavelmente estão no seu tabuleiro, pelos traços lidos.

    O painel de traços do jogo conta cada campeão uma vez em cada traço dele. Então um
    campeão só pode estar em campo se todos os traços dele aparecem lá com contagem sobrando.
    Vai do mais certo para o menos certo (traço exclusivo lido primeiro, depois quem tem mais
    traços) e desconta da contagem cada um que entra. É um palpite: não dá para saber as estrelas.
    """
    sobra = dict(tracos_lidos)

    def certeza(campeao):
        exclusivo = any(catalogo.tracos[t].unico and t in sobra for t in _tracos_de(campeao, catalogo))
        return exclusivo, len(_tracos_de(campeao, catalogo))

    provaveis = []
    for campeao in sorted(campeoes, key=certeza, reverse=True):
        tracos = _tracos_de(campeao, catalogo)
        if tracos and all(sobra.get(t, 0) > 0 for t in tracos):
            for t in tracos:
                sobra[t] -= 1
            provaveis.append(campeao)
    return provaveis


def _tracos_de(campeao, catalogo):
    return [t for t in campeao.tracos if t in catalogo.tracos]


def quem_esta_em_campo(comp, tracos_lidos, catalogo, nivel, tracos_escondidos=0, do_painel=()):
    """Quem está no seu tabuleiro: (prováveis da comp alvo, ForaDaComp).

    `do_painel`: campeões lidos no painel de dano, os que lutaram na última rodada (certos, mas de
    antes do planejamento). Continua em campo quem ainda cabe nos traços lidos; quem não cabe foi
    vendido ou voltou para o banco. Traço que não aparece no painel de traços não conta contra: pode
    estar escondido no "N+". A dedução pelos traços só procura o resto: quem entrou depois.
    """
    sobra = Counter(tracos_lidos)
    confirmados = []
    for campeao in do_painel:
        lidos = [t for t in _tracos_de(campeao, catalogo) if t in tracos_lidos]
        if all(sobra[t] > 0 for t in lidos):
            sobra.subtract(lidos)
            confirmados.append(campeao)
    ids_confirmados = {c.id for c in confirmados}
    da_comp = {c.id for c in comp.campeoes}
    provaveis = [c for c in confirmados if c.id in da_comp] + provaveis_no_tabuleiro(
        [c for c in comp.campeoes if c.id not in ids_confirmados], sobra, catalogo)
    ja_em_campo = provaveis + [c for c in confirmados if c.id not in da_comp]
    fora = fora_da_comp(ja_em_campo, tracos_lidos, catalogo, nivel, tracos_escondidos)
    fora.certos = [c for c in confirmados if c.id not in da_comp] + fora.certos
    return provaveis, fora


@dataclass
class ForaDaComp:
    certos: list = field(default_factory=list)     # estão em campo em todas as combinações que fecham os traços
    pode_ser: list = field(default_factory=list)   # aparecem em alguma combinação, mas não em todas
    vagas_em_duvida: int = 0                       # quantos do tabuleiro ficaram sem nome certo
    folga: int = 0                                 # traços que sobraram sem campeão (emblema/augment)
    sem_combinacao: bool = False                   # nenhuma combinação fecha os traços: leitura errada?


def fora_da_comp(provaveis, tracos_lidos, catalogo, nivel, tracos_escondidos=0):
    """Quem mais está no seu tabuleiro, além dos `provaveis` da comp alvo, pelos traços que sobram.

    Procura as combinações de campeões (cada um no máximo uma vez, como no painel do jogo) que
    fecham exatamente a contagem que sobra de cada traço lido. Um traço que não está no painel só
    pode ser um dos escondidos no "N+" (`tracos_escondidos`, cada um com 1 campeão). O tabuleiro
    tem até `nivel` campeões; se não fechar com todos, tenta com menos (tabuleiro incompleto).
    Se não fechar de jeito nenhum, aceita até FOLGA_MAXIMA_FORA_DA_COMP traços sobrando: um
    emblema equipado ou um augment de traço somam no painel sem ter campeão.
    Quem aparece em todas as combinações é certo; o resto vira "pode ser".
    Se houver combinações demais para testar, desiste e devolve vazio (melhor que chutar).
    """
    sobra = Counter(tracos_lidos)
    for campeao in provaveis:
        sobra.subtract(_tracos_de(campeao, catalogo))
    ids_provaveis = {c.id for c in provaveis}

    def cabe(campeao):
        tracos = _tracos_de(campeao, catalogo)
        escondidos = [t for t in tracos if t not in tracos_lidos]
        return (tracos and len(escondidos) <= tracos_escondidos
                and all(sobra[t] > 0 for t in tracos if t in tracos_lidos))

    candidatos = sorted((c for c in catalogo.campeoes.values() if c.id not in ids_provaveis and cabe(c)),
                        key=lambda c: (c.custo, c.nome))
    passos = [PASSOS_DA_BUSCA_FORA_DA_COMP]  # um limite só para todas as tentativas
    for folga in range(FOLGA_MAXIMA_FORA_DA_COMP + 1):
        for quantos in range(max(0, (nivel or 0) - len(provaveis)), 0, -1):
            combinacoes = _combinacoes_que_fecham(candidatos, sobra, quantos, tracos_lidos, tracos_escondidos,
                                                  catalogo, folga, passos)
            if combinacoes is None:
                return ForaDaComp()
            if combinacoes:
                return _resumir(combinacoes, quantos, folga)
    sobrando = sum((+sobra).values())  # o "+" tira os zeros
    if sobrando <= FOLGA_MAXIMA_FORA_DA_COMP:  # ninguém mais cabe (ex.: tabuleiro completo): é emblema ou augment
        return ForaDaComp(folga=sobrando)
    return ForaDaComp(sem_combinacao=True)  # sobrou traço demais sem explicação: leitura errada?


def _resumir(combinacoes, quantos, folga):
    em_todas = set.intersection(*({c.id for c in combinacao} for combinacao in combinacoes))
    certos = [c for c in combinacoes[0] if c.id in em_todas]
    pode_ser = sorted({c.id: c for combinacao in combinacoes for c in combinacao if c.id not in em_todas}.values(),
                      key=lambda c: (c.custo, c.nome))
    return ForaDaComp(certos, pode_ser, quantos - len(certos), folga)


def _combinacoes_que_fecham(candidatos, sobra, quantos, tracos_lidos, tracos_escondidos, catalogo, folga, passos):
    """Todas as combinações de `quantos` candidatos que deixam no máximo `folga` na `sobra`,
    ou None se a busca passar do limite (`passos`: lista com os passos que ainda restam)."""
    restante = Counter({t: n for t, n in sobra.items() if n > 0})
    escondidos_usados = set()   # traços fora do painel: cada um só pode ter 1 campeão
    escolhidos, achadas = [], []

    def buscar(inicio):
        passos[0] -= 1
        if passos[0] < 0:
            return False
        if len(escolhidos) == quantos:
            if sum((+restante).values()) <= folga:  # o "+" tira os zeros
                achadas.append(list(escolhidos))
            return True
        for posicao in range(inicio, len(candidatos)):
            tracos = _tracos_de(candidatos[posicao], catalogo)
            lidos = [t for t in tracos if t in tracos_lidos]
            escondidos = [t for t in tracos if t not in tracos_lidos]
            if any(restante[t] <= 0 for t in lidos) or escondidos_usados.intersection(escondidos) \
                    or len(escondidos_usados) + len(escondidos) > tracos_escondidos:
                continue
            restante.subtract(lidos)
            escondidos_usados.update(escondidos)
            escolhidos.append(candidatos[posicao])
            terminou = buscar(posicao + 1)
            escolhidos.pop()
            escondidos_usados.difference_update(escondidos)
            restante.update(lidos)
            if not terminou:
                return False
        return True

    return achadas if buscar(0) else None


def copias_que_voce_tem(campeao, situacao):
    return copias_por_estrela(situacao.unidades[campeao.id]) if campeao.id in situacao.unidades else 0


def chance_dos_que_faltam(comp, situacao, catalogo):
    """Para cada campeão que falta: chance de vê-lo numa loja no seu nível."""
    return {
        c.id: chance_na_loja(c, situacao.nivel, catalogo, copias_suas=copias_que_voce_tem(c, situacao))
        for c in comp.faltam
    }
