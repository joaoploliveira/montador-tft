"""Onde fica cada coisa no HUD do TFT.

As posições foram medidas em prints 2560x1440 (QHD) e são convertidas para a
resolução da tela na hora, então funcionam em qualquer monitor 16:9.
Caixas no formato (x0, y0, x1, y1) em pixels de 2560x1440.
"""

REFERENCIA = (2560, 1440)

# "Nv. 5   6/20": o OCR não lê bem o número grande do nível, então usamos o XP ("6/20")
NIVEL_E_XP = (300, 1165, 560, 1222)
# estágio e rodada ("4-3"), no topo; a faixa é larga porque a barra muda de tamanho com a rodada
ESTAGIO = (900, 4, 1250, 46)
OURO = (1222, 1178, 1275, 1214)     # "40", no centro, acima da loja (sem o ícone da moeda)

# nome do campeão em cada carta da loja (sem o custo, que fica à direita)
LOJA_NOMES = [
    (600, 1393, 790, 1428),
    (870, 1393, 1060, 1428),
    (1140, 1393, 1330, 1428),
    (1408, 1393, 1598, 1428),
    (1678, 1393, 1868, 1428),
]

# carta inteira da loja, da borda verde de fora (o overlay desenha a moldura em volta)
# medido num print de 2026-10-27: as cartas têm 256 de largura e ficam a cada ~269,3 pixels
CARTAS_DA_LOJA = [(x0, 1237, x0 + 256, 1432) for x0 in (598, 867, 1137, 1406, 1675)]

# bigorna (escolher 1 item entre vários): aparece no lugar da loja, com o nome de cada opção no meio da carta.
# Com menos opções as cartas continuam centradas na tela, então a carta é achada pelo centro do nome.
BIGORNA_NOMES = (400, 1280, 2180, 1335)   # faixa com os nomes das opções
BIGORNA_CARTA_LARGURA = 328
BIGORNA_CARTA_Y0, BIGORNA_CARTA_Y1 = 1200, 1412
BIGORNA_ICONE_Y0 = 1176                    # o ícone do item passa um pouco da borda de cima da carta
# faixa logo abaixo das cartas: fundo azul-esverdeado liso com a bigorna aberta, loja quando ela fecha.
# (o título "Escolha um" não serve: os balões de dica do jogo passam por cima dele)
BIGORNA_FAIXA_DE_BAIXO = (420, 1418, 2140, 1436)

# painel de traços (lado esquerdo): uma linha por traço, com número + nome + breakpoints
TRACO_X0, TRACO_X1 = 140, 340
TRACO_CENTRO_Y = 375               # centro da primeira linha
TRACO_PASSO = 71
TRACO_MEIA_ALTURA = 32
TRACO_LINHAS = 10
HEXAGONO_X0, HEXAGONO_X1 = 88, 132  # ícone do traço: colorido se ativo, cinza se inativo
HEXAGONO_MEIA_ALTURA = 20
TRACO_NUMERO_X0, TRACO_NUMERO_X1 = 148, 178  # caixinha com a quantidade ("5"), antes do nome
TRACO_NUMERO_MEIA_ALTURA = 18

# banco de itens: coluna de 10 quadrados na borda esquerda
ITEM_X0, ITEM_X1 = 18, 67           # parte de dentro do quadrado (sem a moldura)
ITEM_Y0 = 356                       # topo do primeiro quadrado (sem a moldura)
ITEM_ALTURA = 49
ITEM_PASSO = 72                     # distância entre um quadrado e o próximo
ITEM_QUANTIDADE = 10


def caixas_dos_itens():
    return [
        (ITEM_X0, ITEM_Y0 + i * ITEM_PASSO, ITEM_X1, ITEM_Y0 + i * ITEM_PASSO + ITEM_ALTURA)
        for i in range(ITEM_QUANTIDADE)
    ]


def caixas_dos_tracos():
    return [
        (TRACO_X0, TRACO_CENTRO_Y + i * TRACO_PASSO - TRACO_MEIA_ALTURA,
         TRACO_X1, TRACO_CENTRO_Y + i * TRACO_PASSO + TRACO_MEIA_ALTURA)
        for i in range(TRACO_LINHAS)
    ]


def caixas_dos_hexagonos():
    return [
        (HEXAGONO_X0, TRACO_CENTRO_Y + i * TRACO_PASSO - HEXAGONO_MEIA_ALTURA,
         HEXAGONO_X1, TRACO_CENTRO_Y + i * TRACO_PASSO + HEXAGONO_MEIA_ALTURA)
        for i in range(TRACO_LINHAS)
    ]


def caixas_dos_numeros_dos_tracos():
    return [
        (TRACO_NUMERO_X0, TRACO_CENTRO_Y + i * TRACO_PASSO - TRACO_NUMERO_MEIA_ALTURA,
         TRACO_NUMERO_X1, TRACO_CENTRO_Y + i * TRACO_PASSO + TRACO_NUMERO_MEIA_ALTURA)
        for i in range(TRACO_LINHAS)
    ]


def em_fracao(caixa):
    """Caixa em pixels de 2560x1440 -> frações (0 a 1), para recortar qualquer resolução."""
    largura, altura = REFERENCIA
    x0, y0, x1, y1 = caixa
    return (x0 / largura, y0 / altura, x1 / largura, y1 / altura)
