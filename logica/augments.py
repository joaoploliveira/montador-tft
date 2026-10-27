"""Augments: para que serve cada um (pela descrição) e qual das opções combina mais com a comp alvo.

A Riot não manda mais os augments nas partidas, então não há estatística do alto elo.
A nota vem do encaixe com o seu jogo:
  - traço: o augment fala de um traço (ex.: 'Chama Acesa' -> Inferno, emblemas, coroas).
    Vale muito se a comp alvo usa o traço; quase nada se não usa.
  - campeão: fala de um campeão. Vale se ele está na comp (mais ainda se for o carry).
  - itens: componentes, bigornas, itens prontos. Vale mais com poucos componentes.
  - economia: ouro, XP, atualizações da loja. Vale mais cedo (2-1) do que tarde (4-2).
  - combate: o resto (bônus de status para o time). Serve para qualquer comp: nota média.
As notas ficam aqui em cima, para facilitar ajustes.
"""

import re
from dataclasses import dataclass

from dados import banco
from logica import itens as modulo_itens

NOTA_TRACO_DA_COMP, NOTA_TRACO_FORA = 90, 15
BONUS_TRACO_PRINCIPAL = 5         # o traço é um dos 2 que a comp mais usa
NOTA_CAMPEAO_DA_COMP, NOTA_CAMPEAO_FORA = 80, 20
BONUS_CAMPEAO_CARRY = 10
NOTA_ITENS = 60
BONUS_POUCOS_COMPONENTES = 15     # com menos que POUCOS_COMPONENTES no banco
POUCOS_COMPONENTES = 3
NOTA_ECONOMIA_POR_ESTAGIO = {2: 70, 3: 55}  # do estágio 4 em diante: NOTA_ECONOMIA_TARDE
NOTA_ECONOMIA_TARDE = 35
NOTA_COMBATE = 50

PALAVRAS_DE_ITENS = ("componente", "bigorna", "item completo", "itens completos", "artefato", "item radiante")
PALAVRAS_DE_ECONOMIA = ("xp", "atualiza", "juros")
OURO_QUE_CONTA = 5                # "Recebe 2 de ouro" é bônus; "Recebe 20 de ouro" é economia


@dataclass
class Augment:
    id: str
    nome: str
    descricao: str
    tipo: str = "combate"         # traço, campeão, itens, economia ou combate
    tracos: tuple = ()            # ids dos traços que ele cita
    campeoes: tuple = ()          # ids dos campeões que ele cita


@dataclass
class NotaDoAugment:
    augment: Augment
    nota: int                     # 0 a 100
    motivo: str


# ---------------------------------------------------------------- catálogo

def carregar(catalogo):
    """Os augments do set (tabela augments do banco), já classificados."""
    conexao = banco.conectar()
    linhas = conexao.execute("SELECT chave, nome, descricao FROM augments").fetchall()
    conexao.close()
    return [classificar(Augment(chave, nome, descricao or ""), catalogo) for chave, nome, descricao in linhas]


def _cita(texto, nome):
    """O texto cita o nome como palavra inteira? ('Vi' não pode bater em 'Vida')."""
    return re.search(rf"(?<![\w]){re.escape(nome.lower())}(?![\w])", texto) is not None


def classificar(augment, catalogo):
    texto = f"{augment.nome} {augment.descricao}".lower()
    # traço só pela descrição: 'Lutador Profissional' dá componentes, não fala do traço Lutador
    descricao = augment.descricao.lower() or texto
    augment.tracos = tuple(t.id for t in catalogo.tracos.values() if _cita(descricao, t.nome))
    augment.campeoes = tuple(c.id for c in catalogo.campeoes.values() if _cita(texto, c.nome))
    ouros = [int(n) for n in re.findall(r"(\d+) de ouro", texto)]
    if augment.tracos:
        augment.tipo = "traço"
    elif augment.campeoes:
        augment.tipo = "campeão"
    elif any(palavra in texto for palavra in PALAVRAS_DE_ITENS):
        augment.tipo = "itens"
    elif any(_cita(texto, palavra) for palavra in PALAVRAS_DE_ECONOMIA) or max(ouros, default=0) >= OURO_QUE_CONTA:
        augment.tipo = "economia"
    else:
        augment.tipo = "combate"
    return augment


# ---------------------------------------------------------------- nota

def notas(opcoes, comp, catalogo, estagio=None, componentes=None):
    """A nota (0 a 100) e o motivo de cada opção, para a comp alvo. Da melhor para a pior.
    `estagio`: (estágio, rodada) lido da tela; `componentes`: Counter dos componentes no banco."""
    tracos_da_comp = {t.traco.id: t.quantidade for t in comp.tracos} if comp else {}
    principais = {i for i, _ in sorted(tracos_da_comp.items(), key=lambda x: -x[1])[:2]}
    da_comp = {c.id for c in comp.campeoes} if comp else set()
    carry = next(iter(modulo_itens.carregadores(comp, 1)), None) if comp else None
    numero_do_estagio = estagio[0] if estagio else 3
    resultado = []
    for augment in opcoes:
        if augment.tipo == "traço":
            usados = [t for t in augment.tracos if t in tracos_da_comp]
            nomes = " e ".join(catalogo.tracos[t].nome for t in (usados or augment.tracos))
            if usados:
                nota = NOTA_TRACO_DA_COMP + (BONUS_TRACO_PRINCIPAL if principais & set(usados) else 0)
                motivo = f"combina com {nomes} (traço da sua comp)"
            else:
                nota, motivo = NOTA_TRACO_FORA, f"{nomes} não está na sua comp"
        elif augment.tipo == "campeão":
            usados = [c for c in augment.campeoes if c in da_comp]
            nomes = " e ".join(catalogo.campeoes[c].nome for c in (usados or augment.campeoes))
            if usados:
                e_carry = carry is not None and carry.id in usados
                nota = NOTA_CAMPEAO_DA_COMP + (BONUS_CAMPEAO_CARRY if e_carry else 0)
                motivo = f"{nomes} está na sua comp" + (" (é o carry)" if e_carry else "")
            else:
                nota, motivo = NOTA_CAMPEAO_FORA, f"{nomes} não está na sua comp"
        elif augment.tipo == "itens":
            poucos = sum((componentes or {}).values()) < POUCOS_COMPONENTES
            nota = NOTA_ITENS + (BONUS_POUCOS_COMPONENTES if poucos else 0)
            motivo = "itens: você tem poucos componentes" if poucos else "itens para a comp"
        elif augment.tipo == "economia":
            nota = NOTA_ECONOMIA_POR_ESTAGIO.get(numero_do_estagio, NOTA_ECONOMIA_TARDE)
            motivo = "economia: rende mais cedo" if numero_do_estagio <= 2 else \
                "economia: no meio do jogo, ainda ajuda" if numero_do_estagio == 3 else "economia: tarde demais"
        else:
            nota, motivo = NOTA_COMBATE, "combate: serve para qualquer comp"
        resultado.append(NotaDoAugment(augment, nota, motivo))
    return sorted(resultado, key=lambda n: -n.nota)
