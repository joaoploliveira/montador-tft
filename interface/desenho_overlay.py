"""Desenha o painel e as marcações da loja do overlay como imagens (PIL).

Só desenho: recebe os dados simples de dados/overlay.json e devolve imagens RGBA.
O overlay.py só coloca essas imagens na tela; a prévia usa as mesmas funções.

Cuidado com transparência: o overlay é uma janela em que uma cor (a "invisível") vira
buraco. Pixel meio transparente não vira buraco, vira uma mistura escura. Por isso as
bordas de fora (painel e molduras) são desenhadas sem suavização.
Medidas em pixels de 2560x1440; o Pincel converte para a resolução da tela.
"""

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from dados import cdragon

PASTA_FONTES = "C:/Windows/Fonts/"
FONTES = {"normal": "segoeui.ttf", "seminegrito": "seguisb.ttf", "negrito": "segoeuib.ttf", "simbolos": "seguisym.ttf"}

FUNDO, FUNDO_CLARO = (18, 21, 28, 255), (30, 35, 46, 255)
BORDA, SEPARADOR = (232, 185, 65, 255), (52, 58, 72, 255)
TEXTO, APAGADO = (242, 242, 242, 255), (138, 147, 163, 255)
COR_FRASE = {"montar": (127, 227, 160, 255), "quase": (232, 201, 90, 255), "util": (143, 186, 245, 255)}
COR_DICA = (127, 227, 160, 255)
COR_CUSTO = {1: "#9aa0a6", 2: "#1fa34a", 3: "#2f7ae5", 4: "#b14be0", 5: "#f0b429"}
COR_TRACO = {1: ("#8c5a3c", "#ffffff"), 2: ("#aebdca", "#17202a"), 3: ("#e8b941", "#2a1d00"), 4: ("#d9b8ff", "#1b1b2a")}
COR_ORIGEM = {"Meta": ("#e8b941", "#2a1d00", "META"), "Algoritmo": ("#2f7ae5", "#ffffff", "PARA VOCÊ"),
              "Minhas comps": ("#b14be0", "#ffffff", "MINHA")}
COR_STATUS_ITEM = {"Pode montar": "#2fb35a", "Falta 1 componente": "#e8b941"}  # bolinha no ícone do item
COR_SELO = {"COMPRE": ("#2fb35a", "#ffffff"), "SOBE ★": ("#e8b941", "#2a1d00")}

MARGEM = 14
RETRATO_MAXIMO, RETRATO_ESPACO = 52, 7
ICONE_ITEM = 26


class Pincel:
    """Guarda a escala da tela, as fontes e os ícones já carregados (para não reler a cada segundo)."""

    def __init__(self, escala):
        self.escala = escala
        self._fontes, self._icones = {}, {}

    def px(self, valor):
        return max(1, round(valor * self.escala))

    def fonte(self, tamanho, peso="normal"):
        chave = (tamanho, peso)
        if chave not in self._fontes:
            try:
                self._fontes[chave] = ImageFont.truetype(PASTA_FONTES + FONTES[peso], self.px(tamanho))
            except OSError:
                self._fontes[chave] = ImageFont.load_default()
        return self._fontes[chave]

    def icone(self, tipo, chave, tamanho, apagado=False):
        """Ícone quadrado com cantos arredondados; `apagado` = cinza e escuro (campeão que falta)."""
        lado = self.px(tamanho)
        memoria = (tipo, chave, lado, apagado)
        if memoria not in self._icones:
            caminho = cdragon.caminho_do_icone(tipo, chave) if chave else None
            if caminho:
                imagem = ImageOps.fit(Image.open(caminho).convert("RGB"), (lado, lado), Image.LANCZOS)
            else:
                imagem = Image.new("RGB", (lado, lado), FUNDO_CLARO[:3])
            if apagado:
                imagem = ImageEnhance.Brightness(ImageOps.grayscale(imagem).convert("RGB")).enhance(0.45)
            imagem.putalpha(_mascara_arredondada(lado, lado, max(2, lado // 7)))
            self._icones[memoria] = imagem
        return self._icones[memoria]


def _mascara_arredondada(largura, altura, raio):
    """Máscara suavizada (desenha 4x maior e reduz). Só para coisas por dentro do painel."""
    grande = Image.new("L", (largura * 4, altura * 4), 0)
    ImageDraw.Draw(grande).rounded_rectangle((0, 0, largura * 4 - 1, altura * 4 - 1), raio * 4, fill=255)
    return grande.resize((largura, altura), Image.LANCZOS)


def _etiqueta(desenho, x, y, texto, fonte, fundo, cor_texto, pincel, contorno=None):
    """Etiqueta arredondada com texto; devolve (largura, altura)."""
    folga_x, folga_y = pincel.px(8), pincel.px(3)
    x0, y0, x1, y1 = desenho.textbbox((0, 0), texto, font=fonte)
    largura, altura = (x1 - x0) + 2 * folga_x, (y1 - y0) + 2 * folga_y
    desenho.rounded_rectangle((x, y, x + largura, y + altura), altura // 2, fill=fundo,
                              outline=contorno, width=pincel.px(2) if contorno else 0)
    desenho.text((x + folga_x - x0, y + folga_y - y0), texto, font=fonte, fill=cor_texto)
    return largura, altura


def _quebrar(texto, fonte, largura):
    """Quebra o texto em linhas que caibam na largura."""
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if atual and fonte.getlength(tentativa) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = tentativa
    return linhas + ([atual] if atual else [])


def _cortar(texto, fonte, largura):
    """Corta o texto com '…' se não couber."""
    if fonte.getlength(texto) <= largura:
        return texto
    while texto and fonte.getlength(texto + "…") > largura:
        texto = texto[:-1]
    return texto.rstrip() + "…"


# ---------------------------------------------------------------- painel da comp alvo

def painel(comp, dicas, itens_agora, pincel, largura, com_tracos=True, com_itens=True):
    """O painel inteiro. Desenha numa imagem alta e corta na altura usada."""
    px = pincel.px
    largura = px(largura)
    imagem = Image.new("RGBA", (largura, px(900)), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    esquerda, direita = px(MARGEM), largura - px(MARGEM)

    y = _cabecalho(imagem, desenho, comp, pincel, esquerda, direita, px(MARGEM))
    y = _retratos(imagem, desenho, comp["campeoes"], pincel, esquerda, direita, y + px(8))
    if com_tracos and comp["tracos"]:
        y = _tracos(desenho, comp["tracos"], pincel, esquerda, direita, y + px(6))
    if com_itens and (itens_agora or comp["itens"]):
        y += px(7)
        desenho.line((esquerda, y, direita, y), fill=SEPARADOR, width=px(1))
        if itens_agora:
            y = _frases_de_itens(imagem, desenho, itens_agora, pincel, esquerda, direita, y + px(6))
        else:
            y = _build_do_carry(imagem, desenho, comp, pincel, esquerda, y + px(6))
    y = _dicas(desenho, dicas, pincel, esquerda, direita, y + px(2))

    altura = y + px(MARGEM) - px(6)
    fundo = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    # borda de fora sem suavização (ver o aviso no topo do arquivo)
    ImageDraw.Draw(fundo).rounded_rectangle((0, 0, largura - 1, altura - 1), px(14), fill=FUNDO,
                                            outline=BORDA, width=px(2))
    fundo.alpha_composite(imagem.crop((0, 0, largura, altura)))
    return fundo


def _cabecalho(imagem, desenho, comp, pincel, esquerda, direita, y):
    """Nome da comp e, à direita, a origem (META / PARA VOCÊ / MINHA) e quantos você tem."""
    px = pincel.px
    fundo, cor, rotulo = COR_ORIGEM.get(comp["origem"], ("#444b5a", "#ffffff", comp["origem"].upper()))
    fonte_pequena = pincel.fonte(12, "negrito")
    contador = f"{comp['tem']}/{comp['total']}"
    largura_contador = fonte_pequena.getlength(contador) + px(16)
    largura_rotulo = fonte_pequena.getlength(rotulo) + px(16)
    x_rotulo = direita - largura_contador - px(6) - largura_rotulo

    fonte_titulo = pincel.fonte(20, "negrito")
    nome = _cortar(comp["nome"], fonte_titulo, x_rotulo - esquerda - px(10))
    desenho.text((esquerda, y - px(3)), nome, font=fonte_titulo, fill=TEXTO)
    altura_titulo = px(26)
    y_etiqueta = y + px(3)
    _etiqueta(desenho, x_rotulo, y_etiqueta, rotulo, fonte_pequena, fundo, cor, pincel)
    _etiqueta(desenho, direita - largura_contador, y_etiqueta, contador, fonte_pequena, FUNDO_CLARO, TEXTO, pincel)
    return y + altura_titulo


def _retratos(imagem, desenho, campeoes, pincel, esquerda, direita, y):
    """Uma foto por campeão, borda na cor do custo; quem falta fica cinza; estrelas embaixo."""
    px = pincel.px
    quantos = max(1, len(campeoes))
    lado_ref = min(RETRATO_MAXIMO, ((direita - esquerda) / pincel.escala - (quantos - 1) * RETRATO_ESPACO) / quantos)
    lado, espaco, borda = px(lado_ref), px(RETRATO_ESPACO), px(3)
    estrelas_fonte = pincel.fonte(13, "simbolos")
    x = esquerda
    for campeao in campeoes:
        tem = campeao["estrelas"] > 0
        cor = COR_CUSTO.get(campeao["custo"], "#888888")
        desenho.rounded_rectangle((x, y, x + lado, y + lado), max(3, lado // 6), fill=cor if tem else FUNDO_CLARO,
                                  outline=cor, width=borda)
        foto = pincel.icone("campeao", campeao.get("chave"), (lado - 2 * borda) / pincel.escala, apagado=not tem)
        imagem.alpha_composite(foto, (x + borda, y + borda))
        if tem:
            estrelas = "★" * campeao["estrelas"]
            largura_estrelas = estrelas_fonte.getlength(estrelas)
            caixa = (x + (lado - largura_estrelas) / 2 - px(4), y + lado - px(13),
                     x + (lado + largura_estrelas) / 2 + px(4), y + lado + px(4))
            desenho.rounded_rectangle(caixa, px(6), fill=(18, 21, 28, 235))
            desenho.text((x + lado / 2, y + lado - px(5)), estrelas, font=estrelas_fonte, fill="#f6c945", anchor="mm")
        x += lado + espaco
    return y + lado + px(4)


def _tracos(desenho, tracos, pincel, esquerda, direita, y):
    """Traços ativos como etiquetas na cor do nível (bronze, prata, ouro, prismático)."""
    fonte = pincel.fonte(12, "seminegrito")
    x, altura = esquerda, 0
    for traco in tracos:
        fundo, cor = COR_TRACO.get(traco["estilo"], ("#666666", "#ffffff"))
        largura = fonte.getlength(traco["texto"]) + pincel.px(16)
        if x > esquerda and x + largura > direita:
            break  # uma linha só: o resto não cabe sem empurrar o painel para baixo
        largura, altura = _etiqueta(desenho, x, y, traco["texto"], fonte, fundo, cor, pincel)
        x += largura + pincel.px(5)
    return y + altura


def _frases_de_itens(imagem, desenho, frases, pincel, esquerda, direita, y):
    """Uma linha por frase, com ícones: [comp] + [comp] → [item] Nome → [campeão]."""
    px = pincel.px
    lado = px(ICONE_ITEM)
    fonte = pincel.fonte(14, "seminegrito")
    fonte_sinal = pincel.fonte(14, "normal")
    for frase in frases:
        cor = COR_FRASE.get(frase["tipo"], TEXTO)
        x, meio = esquerda, y + lado / 2

        def icone(tipo, chave):
            nonlocal x
            imagem.alpha_composite(pincel.icone(tipo, chave, ICONE_ITEM), (round(x), y))
            x += lado + px(5)

        def texto(conteudo, fonte_usada=fonte, cor_usada=cor):
            nonlocal x
            desenho.text((x, meio), conteudo, font=fonte_usada, fill=cor_usada, anchor="lm")
            x += fonte_usada.getlength(conteudo) + px(6)

        if frase["tipo"] == "montar":
            for posicao, componente in enumerate(frase["componentes"]):
                if posicao:
                    texto("+", fonte_sinal, APAGADO)
                icone("item", componente)
            texto("→", fonte_sinal, APAGADO)
            icone("item", frase["item_chave"])
            texto(frase["item"])
            texto("→", fonte_sinal, APAGADO)
            icone("campeao", frase["campeao_chave"])
        elif frase["tipo"] == "quase":
            texto("Quase:", fonte_sinal, APAGADO)
            icone("item", frase["item_chave"])
            texto(frase["item"])
            texto("· falta", fonte_sinal, APAGADO)
            icone("item", frase["falta_chave"])
        else:
            texto("Carrossel/bigorna:", fonte_sinal, APAGADO)
            icone("item", frase["item_chave"])
            texto(frase["item"])
        y += lado + px(4)
    return y - px(4)


def _build_do_carry(imagem, desenho, comp, pincel, esquerda, y):
    """Sem componentes: a build do carry, com uma bolinha (verde = dá para montar, amarela = falta 1)."""
    px = pincel.px
    lado = px(ICONE_ITEM)
    fonte = pincel.fonte(13, "normal")
    rotulo = f"Build de {comp['carry']}:"
    desenho.text((esquerda, y + lado / 2), rotulo, font=fonte, fill=APAGADO, anchor="lm")
    x = esquerda + fonte.getlength(rotulo) + px(8)
    for item in comp["itens"]:
        imagem.alpha_composite(pincel.icone("item", item.get("chave"), ICONE_ITEM), (round(x), y))
        cor = COR_STATUS_ITEM.get(item["status"])
        if cor:
            r = px(5)
            desenho.ellipse((x + lado - r * 2 + px(2), y - px(2), x + lado + px(2), y + r * 2 - px(2)),
                            fill=cor, outline=FUNDO, width=px(1))
        x += lado + px(6)
    return y + lado


def _dicas(desenho, dicas, pincel, esquerda, direita, y):
    """Dicas do momento (nível, rolagem, juros), com bolinha verde e quebra de linha."""
    px = pincel.px
    fonte = pincel.fonte(13, "normal")
    altura_linha = px(18)
    for dica in dicas:
        y += px(4)
        desenho.ellipse((esquerda, y + px(6), esquerda + px(6), y + px(12)), fill=COR_DICA)
        for linha in _quebrar(dica, fonte, direita - esquerda - px(14)):
            desenho.text((esquerda + px(14), y), linha, font=fonte, fill=COR_DICA)
            y += altura_linha
    return y


# ---------------------------------------------------------------- loja

def marcacao_da_loja(selo, largura_carta, altura_carta, folga, pincel):
    """Moldura em volta da carta e a etiqueta (COMPRE / SOBE ★) no meio da borda de cima.

    A imagem começa `folga + linha` antes da carta e a etiqueta sobe `metade da etiqueta`;
    devolve (imagem, deslocamento_x, deslocamento_y) para o overlay saber onde colocar.
    """
    px = pincel.px
    linha = px(5)
    fundo, cor_texto = COR_SELO.get(selo, ("#2fb35a", "#ffffff"))
    fonte, fonte_estrela = pincel.fonte(15, "negrito"), pincel.fonte(15, "simbolos")  # a negrito não tem ★
    texto, estrela = selo.replace("★", "").strip(), "★" if "★" in selo else ""
    altura_etiqueta = px(26)
    sobe = altura_etiqueta // 2

    largura = px(largura_carta) + 2 * (px(folga) + linha)
    altura = px(altura_carta) + 2 * (px(folga) + linha) + sobe
    imagem = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    desenho.rounded_rectangle((0, sobe, largura - 1, altura - 1), px(12), outline=fundo, width=linha)

    espaco = px(4) if estrela else 0
    largura_texto = fonte.getlength(texto) + espaco + fonte_estrela.getlength(estrela)
    largura_etiqueta = largura_texto + px(22)
    x0 = (largura - largura_etiqueta) / 2
    desenho.rounded_rectangle((x0, 0, x0 + largura_etiqueta, altura_etiqueta), altura_etiqueta // 2,
                              fill=fundo, outline=FUNDO, width=px(2))
    x_texto = x0 + px(11)
    desenho.text((x_texto, altura_etiqueta / 2), texto, font=fonte, fill=cor_texto, anchor="lm")
    if estrela:
        x_estrela = x_texto + fonte.getlength(texto) + espaco
        desenho.text((x_estrela, altura_etiqueta / 2), estrela, font=fonte_estrela, fill=cor_texto, anchor="lm")
    return imagem, -(px(folga) + linha), -(px(folga) + linha) - sobe
