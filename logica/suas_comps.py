"""Suas comps: as comps que você repete, aprendidas das suas partidas (de todas as suas contas).

As comps meta são agrupadas por carry + 2 traços. Para as suas isso não serve: na mesma comp, quem
carrega muda de uma partida para outra (ex.: na "peidao", às vezes a Nidalee, às vezes o Master Yi ou
o Kog'Maw). Aqui dois tabuleiros são da mesma comp quando dividem a maior parte dos campeões.

Os nomes que você dá ficam no banco junto com os campeões da comp naquele momento. Uma comp recebe o
nome se ainda for parecida com esses campeões: assim o nome continua valendo quando a comp muda um pouco.
"""

from collections import Counter
from dataclasses import dataclass, field

from logica import meta, taticas
from logica.montador import avaliar

SEMELHANCA_MINIMA = 0.5   # campeões em comum / campeões somados dos dois lados: daqui para cima é a mesma comp
NUCLEO = 0.5              # o campeão faz parte da comp se aparece em pelo menos metade dos tabuleiros dela
ESSENCIAL = 0.75          # aparece em 75% ou mais: peça central
MINIMO_DE_JOGOS = 3       # menos que isso não é "uma comp que você repete"
MAXIMO_DE_CAMPEOES = 9
ORIGEM = "Suas comps"


@dataclass
class SuaComp:
    nome: str                                        # o nome que você deu, ou o automático
    nome_automatico: str                             # "Carry — Traço + Traço", o mais comum entre os tabuleiros
    nucleo: list                                     # Campeao, do mais frequente para o menos
    tabuleiros: list                                 # seus tabuleiros finais dessa comp
    outros: list = field(default_factory=list)       # tabuleiros do alto elo parecidos com o núcleo

    @property
    def desempenho(self):
        return taticas.Desempenho([t.colocacao for t in self.tabuleiros])

    @property
    def desempenho_dos_outros(self):
        return taticas.Desempenho([t.colocacao for t in self.outros])

    @property
    def nivel_medio(self):
        return sum(t.nivel for t in self.tabuleiros) / len(self.tabuleiros)

    def montada(self, tabuleiro):
        """O tabuleiro tem todos os campeões principais da comp? (Na peidao, bate em 33 de 36 partidas
        com "Adaptador 4 + Nidalee"; montada: média 3,42; não montada: 6,00.)"""
        return {c.id for c in self.nucleo} <= _ids(tabuleiro)

    @property
    def montadas(self):
        return [t for t in self.tabuleiros if self.montada(t)]

    @property
    def nao_montadas(self):
        return [t for t in self.tabuleiros if not self.montada(t)]

    def o_que_faltou(self):
        """[(Campeao, em quantas partidas não montadas ele faltou)], do que mais falta para o que menos."""
        faltas = Counter(c.id for t in self.nao_montadas for c in self.nucleo if c.id not in _ids(t))
        por_id = {c.id: c for c in self.nucleo}
        return [(por_id[i], n) for i, n in faltas.most_common()]


def semelhanca(ids_a, ids_b):
    """Campeões em comum / campeões somados dos dois lados (0 a 1)."""
    ids_a, ids_b = set(ids_a), set(ids_b)
    return len(ids_a & ids_b) / len(ids_a | ids_b) if ids_a | ids_b else 0.0


def _ids(tabuleiro):
    return {u.campeao.id for u in tabuleiro.unidades}


def nucleo(tabuleiros):
    """Os ids dos campeões que aparecem em pelo menos NUCLEO dos tabuleiros, do mais frequente para o menos."""
    contagem = Counter(i for t in tabuleiros for i in _ids(t))
    return [i for i, n in contagem.most_common(MAXIMO_DE_CAMPEOES) if n / len(tabuleiros) >= NUCLEO]


def agrupar(tabuleiros):
    """Junta os tabuleiros parecidos: cada um entra no grupo de núcleo mais parecido, se passar do mínimo;
    senão começa um grupo novo. Do mais antigo para o mais recente, para a comp "nascer" da primeira vez."""
    grupos = []
    for tabuleiro in tabuleiros:
        ids = _ids(tabuleiro)
        notas = [(semelhanca(ids, nucleo(grupo)), grupo) for grupo in grupos]
        nota, melhor = max(notas, key=lambda par: par[0], default=(0.0, None))
        if melhor is not None and nota >= SEMELHANCA_MINIMA:
            melhor.append(tabuleiro)
        else:
            grupos.append([tabuleiro])
    return grupos


def _nome_dado(ids_do_nucleo, nomes):
    """O nome que você deu a uma comp parecida com esse núcleo, ou None."""
    parecidos = [(semelhanca(ids_do_nucleo, n["campeoes"]), n["nome"]) for n in nomes]
    nota, nome = max(parecidos, default=(0.0, None))
    return nome if nota >= SEMELHANCA_MINIMA else None


def suas_comps(meus, alto_elo, catalogo, nomes=()):
    """As comps que você jogou pelo menos MINIMO_DE_JOGOS vezes, da mais jogada para a menos.
    `meus`: seus tabuleiros finais; `alto_elo`: os do alto elo (para comparar); `nomes`: banco.nomes_das_comps."""
    comps = []
    for grupo in agrupar(list(reversed(meus))):  # meus_tabuleiros vem do mais recente para o mais antigo
        if len(grupo) < MINIMO_DE_JOGOS:
            continue
        ids = nucleo(grupo)
        automatico = Counter(meta.nome_da_comp(t, catalogo) for t in grupo).most_common(1)[0][0] or "Sem itens"
        comps.append(SuaComp(
            nome=_nome_dado(ids, nomes) or automatico,
            nome_automatico=automatico,
            nucleo=[catalogo.campeoes[i] for i in ids],
            tabuleiros=grupo,
            outros=[t for t in alto_elo if semelhanca(_ids(t), ids) >= SEMELHANCA_MINIMA],
        ))
    return sorted(comps, key=lambda comp: -len(comp.tabuleiros))


def da_comp(tabuleiro, comps):
    """A sua comp de um tabuleiro (a de núcleo mais parecido), ou None."""
    notas = [(semelhanca(_ids(tabuleiro), [c.id for c in comp.nucleo]), comp) for comp in comps]
    nota, comp = max(notas, key=lambda par: par[0], default=(0.0, None))
    return comp if nota >= SEMELHANCA_MINIMA else None


def para_o_app(sua, situacao, catalogo):
    """A sua comp como as outras da lista (comp alvo, overlay e cartão), com os seus números."""
    comp = avaliar(sua.nucleo, situacao, catalogo, nome=sua.nome, origem=ORIGEM)
    carregadores = Counter(t.carry().campeao.id for t in sua.tabuleiros if t.carry())
    carry = catalogo.campeoes[carregadores.most_common(1)[0][0]] if carregadores else None
    com_o_carry = [t for t in sua.tabuleiros if carry and carry.id in _ids(t)]
    frequencia = Counter(i for t in sua.tabuleiros for i in _ids(t))
    d = sua.desempenho
    comp.estatisticas = {
        "jogos": d.jogos,
        "colocacao_media": round(d.media, 2),
        "media_ajustada": round(d.ajustada, 2),
        "top4": d.top4,
        "vitoria": d.vitorias,
        "carry": carry.nome if carry else "",
        "itens_do_carry": meta.build_do_carry(com_o_carry, carry) if carry else [],
        "essenciais": [c.nome for c in sua.nucleo if frequencia[c.id] / d.jogos >= ESSENCIAL],
        "plano": taticas.plano_da_comp(sua.tabuleiros),
    }
    return comp
