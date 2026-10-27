"""Lê o HUD do TFT a partir de um print: loja, nível, ouro, traços e itens no banco."""

import re
from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from dados import cdragon
from logica import augments as modulo_augments
from logica.tradutor import Tradutor
from visao import ocr, regioes
from visao.captura import recortar

TAMANHO_COMPARACAO = 40     # px; ícones são comparados nesse tamanho
SEMELHANCA_MINIMA = 0.55    # abaixo disso, o ícone do banco não é considerado reconhecido
BRILHO_DE_VAZIO = 18        # quadrado de item quase preto = vazio
SATURACAO_DE_ATIVO = 25     # hexágono do traço colorido (bronze/ouro) = traço ativo; cinza ~4
BRILHO_DE_ATIVO = 80        # a prata tem pouca cor (~40), mas é clara (~120); o cinza do inativo fica ~42
TIPOS_NO_BANCO = ("Componente", "Completo", "Emblema", "Radiante", "Artefato")


@dataclass
class LeituraDaTela:
    nivel: int | None = None
    xp: tuple | None = None                            # (XP atual, XP para subir), ex.: (2, 56)
    estagio: tuple | None = None                       # (estágio, rodada), ex.: (4, 3)
    ouro: int | None = None
    loja: list = field(default_factory=list)          # 5 posições: Campeao ou None (vazia/comprada)
    tracos: dict = field(default_factory=dict)        # traco_id -> quantidade (do painel)
    tracos_escondidos: int = 0                         # o "2+" no fim do painel: traços que não couberam
    itens: Counter = field(default_factory=Counter)   # item_id -> quantidade no banco
    bigorna: list = field(default_factory=list)       # bigorna aberta: [(Item, caixa da carta)], senão []
    augments: list = field(default_factory=list)      # escolha de augment: [(Augment, x do centro do nome)], senão []
    textos_crus: dict = field(default_factory=dict)   # o que o OCR leu, para conferir


def _recorte(imagem, caixa):
    return recortar(imagem, regioes.em_fracao(caixa))


def _numero(texto):
    achado = re.search(r"\d+", texto.replace("O", "0").replace("o", "0"))
    return int(achado.group()) if achado else None


REPETICOES_DO_NUMERO = 3


def _numero_da_caixinha(recorte):
    """O número da caixinha do traço ("5"). O OCR do Windows não lê um caractere sozinho,
    então a caixinha é repetida lado a lado ("5 5 5") e o resultado ("555") é dividido de volta."""
    espaco = 6
    fileira = Image.new("RGB", (recorte.width * REPETICOES_DO_NUMERO + espaco * (REPETICOES_DO_NUMERO - 1),
                                recorte.height), recorte.getpixel((1, 1)))
    for k in range(REPETICOES_DO_NUMERO):
        fileira.paste(recorte, (k * (recorte.width + espaco), 0))
    for ampliar in (2, 3):
        texto = re.sub(r"\s", "", ocr.ler_texto(fileira, ampliar=ampliar))
        tamanho = len(texto) // REPETICOES_DO_NUMERO
        if tamanho and texto.isdigit() and texto == texto[:tamanho] * REPETICOES_DO_NUMERO:
            return int(texto[:tamanho])
    return None


def tracos_tapados(novos, anteriores):
    """Os traços lidos agora parecem tapados por um balão (ex.: o mouse em cima de um item)?
    Sinal: só sumiram traços, e todos os que sobraram têm a mesma contagem de antes. Vender um
    campeão quase sempre muda a contagem de algum traço que fica."""
    return len(novos) < len(anteriores) and all(anteriores.get(traco) == n for traco, n in novos.items())


def _tracos_escondidos(recorte):
    """O "2+" que o jogo põe no fim do painel de traços quando não cabem todos. 0 se não tem."""
    achado = re.fullmatch(r"(\d)\s*\+", ocr.ler_texto(recorte, ampliar=4).strip())
    return int(achado.group(1)) if achado else 0


class Leitor:
    def __init__(self, catalogo):
        self.catalogo = catalogo
        self.tradutor = Tradutor(catalogo, modulo_augments.carregar(catalogo))
        self.modelos = self._carregar_modelos_de_itens()

    def _carregar_modelos_de_itens(self):
        modelos = {}
        for item in self.catalogo.itens.values():
            caminho = cdragon.caminho_do_icone("item", item.chave)
            if item.tipo in TIPOS_NO_BANCO and caminho:
                icone = cv2.imdecode(np.fromfile(str(caminho), dtype=np.uint8), cv2.IMREAD_COLOR)
                modelos[item.id] = cv2.resize(icone, (TAMANHO_COMPARACAO, TAMANHO_COMPARACAO), interpolation=cv2.INTER_AREA)
        return modelos

    # ------------------------------------------------------------ partes do HUD

    def ler_nivel(self, imagem):
        """Devolve (texto, nível, (xp atual, xp para subir)).

        O número grande do nível o OCR lê mal; o XP ('6/20') resolve: só o nível 5 pede 20 para subir.
        """
        texto = ocr.ler_texto(_recorte(imagem, regioes.NIVEL_E_XP))
        achado = re.search(r"(\d+)\s*/\s*(\d+)", texto)
        xp = (int(achado.group(1)), int(achado.group(2))) if achado else None
        escrito = re.search(r"Nv\.?\s*(\d+)", texto)
        if escrito:
            return texto, int(escrito.group(1)), xp
        if xp:
            niveis = [nivel for nivel, total in self.catalogo.xp_para_subir.items() if total == xp[1]]
            if niveis:
                return texto, min(niveis), xp  # se dois níveis pedem o mesmo XP, fica o menor
        return texto, None, xp

    TENTATIVAS_ESTAGIO = [(3, 0), (2, 0), (2, 120)]

    def ler_estagio(self, imagem):
        """'4-3' no topo da tela -> (4, 3)."""
        recorte = _recorte(imagem, regioes.ESTAGIO)
        texto = ""
        for ampliar, limiar in self.TENTATIVAS_ESTAGIO:
            texto = ocr.ler_texto(recorte, ampliar=ampliar, limiar=limiar)
            achado = re.search(r"([1-7])\s*[-–—]\s*([1-7])", texto)
            if achado:
                return texto, (int(achado.group(1)), int(achado.group(2)))
        return texto, None

    def ler_ouro(self, imagem):
        texto = ocr.ler_texto(_recorte(imagem, regioes.OURO))
        return texto, _numero(texto)

    # tratamentos de imagem tentados em ordem até reconhecer o texto: (ampliar, limiar)
    TENTATIVAS_LOJA = [(2, 0), (3, 0), (2, 150)]
    TENTATIVAS_TRACO = [(2, 140), (3, 170), (3, 0)]

    def ler_loja(self, imagem):
        """Nome de cada carta da loja. Cartas vazias ou especiais (ex.: 'Solitude') ficam None."""
        textos, campeoes = [], []
        for caixa in regioes.LOJA_NOMES:
            recorte = _recorte(imagem, caixa)
            texto, campeao = "", None
            for ampliar, limiar in self.TENTATIVAS_LOJA:
                texto = ocr.ler_texto(recorte, ampliar=ampliar, limiar=limiar)
                campeao = self.tradutor.campeao_do_texto(texto)
                if campeao:
                    break
            textos.append(texto)
            campeoes.append(campeao)
        return textos, campeoes

    def ler_tracos(self, imagem):
        """Painel da esquerda, linha por linha: '3 Solar 3/3', '2 Fumegante 2 > 3 > 4', '1 Defendente 1/2'.

        O nome sai quase sempre; o número às vezes some no OCR. Sem ele, usamos o '1/2'
        (traço inativo: o primeiro número é a quantidade) ou o primeiro breakpoint.
        Com traços demais, o jogo mostra "2+" no lugar do hexágono da linha seguinte: são os escondidos.
        Devolve (textos, tracos, quantos escondidos).
        """
        textos, tracos, linhas_vazias, escondidos = [], {}, 0, 0
        linhas = zip(regioes.caixas_dos_tracos(), regioes.caixas_dos_hexagonos(),
                     regioes.caixas_dos_numeros_dos_tracos())
        for caixa, hexagono, caixa_do_numero in linhas:
            recorte = _recorte(imagem, caixa)
            hsv = np.asarray(_recorte(imagem, hexagono).convert("HSV"))
            ativo = hsv[:, :, 1].mean() > SATURACAO_DE_ATIVO or hsv[:, :, 2].mean() > BRILHO_DE_ATIVO
            traco, quantidade = None, None
            for ampliar, limiar in self.TENTATIVAS_TRACO:
                texto = ocr.ler_texto(recorte, ampliar=ampliar, limiar=limiar)
                # palavras de 2+ letras: assim o "I" (que é o 1 na fonte do jogo) não gruda no nome
                nome = re.search(r"[A-Za-zÀ-ÿ']{2,}(?:\s+[A-Za-zÀ-ÿ']{2,})*", texto)
                traco = self.tradutor.traco_do_texto(nome.group()) if nome else None
                if traco:
                    textos.append(texto)
                    numero = _numero_da_caixinha(_recorte(imagem, caixa_do_numero)) if ativo else None
                    quantidade = self._quantidade_do_traco(texto, nome, traco, ativo, numero)
                    break
            if traco:
                tracos[traco.id] = quantidade
                linhas_vazias = 0
            else:
                linhas_vazias += 1
                if linhas_vazias == 1 and tracos:
                    escondidos = _tracos_escondidos(_recorte(imagem, hexagono))
                if linhas_vazias == 2 or escondidos:  # acabou a lista de traços
                    break
        return textos, tracos, escondidos

    @staticmethod
    def _quantidade_do_traco(texto, nome, traco, ativo, numero_da_caixinha=None):
        """O número fica numa caixinha antes do nome. Depois do nome vêm os breakpoints
        ('2 > 3 > 4') ou, se o traço está inativo, 'quantidade/próximo' ('1/2')."""
        def com_uns(trecho):  # a fonte do jogo desenha o 1 parecido com um I
            return re.sub(r"[Il|!]", "1", trecho)

        primeiro_nivel = traco.niveis[0] if traco.niveis else 1
        antes = re.search(r"(\d+)\s*$", com_uns(texto[:nome.start()]))
        numero_antes = int(antes.group(1)) if antes else None
        if ativo:
            if numero_da_caixinha and numero_da_caixinha >= primeiro_nivel:
                return numero_da_caixinha
            if numero_antes and numero_antes >= primeiro_nivel:
                return numero_antes
            return primeiro_nivel  # sem o número: pelo menos o primeiro breakpoint
        depois = re.search(r"\d", com_uns(texto[nome.end():]))
        for candidato in (numero_antes, int(depois.group()) if depois else None):
            if candidato and candidato < primeiro_nivel:
                return candidato
        return 1

    def ler_itens(self, imagem):
        itens, detalhes = Counter(), []
        for caixa in regioes.caixas_dos_itens():
            pedaco = np.asarray(_recorte(imagem, caixa))[:, :, ::-1]  # PIL (RGB) -> OpenCV (BGR)
            if pedaco.mean() < BRILHO_DE_VAZIO:
                detalhes.append("vazio")
                continue
            pedaco = cv2.resize(pedaco, (TAMANHO_COMPARACAO, TAMANHO_COMPARACAO), interpolation=cv2.INTER_AREA)
            melhor_id, melhor_nota = None, -1.0
            for id_item, modelo in self.modelos.items():
                nota = float(cv2.matchTemplate(pedaco, modelo, cv2.TM_CCOEFF_NORMED)[0][0])
                if nota > melhor_nota:
                    melhor_id, melhor_nota = id_item, nota
            if melhor_nota >= SEMELHANCA_MINIMA:
                itens[melhor_id] += 1
                detalhes.append(f"{self.catalogo.itens[melhor_id].nome} ({melhor_nota:.2f})")
            else:
                detalhes.append(f"? ({melhor_nota:.2f})")
        return detalhes, itens

    # ------------------------------------------------------------ tudo de uma vez

    MINIMO_DE_OPCOES_NA_BIGORNA = 2  # um nome só pode ser engano do OCR em outra tela

    def ler_bigorna(self, imagem):
        """Opções de uma bigorna aberta, da esquerda para a direita: [(item, caixa da carta)].
        A caixa (em pixels de 2560x1440) é a carta inteira, centrada no nome lido."""
        faixa = regioes.BIGORNA_NOMES
        para_referencia = regioes.REFERENCIA[0] / imagem.width  # pixels da tela -> pixels de 2560x1440
        textos, opcoes = [], []
        for linha in ocr.ler_linhas(_recorte(imagem, faixa)):
            textos.append(linha.texto)
            item = self.tradutor.item_do_texto(linha.texto)
            if item:
                centro = faixa[0] + (linha.x + linha.largura / 2) * para_referencia
                meia = regioes.BIGORNA_CARTA_LARGURA / 2
                opcoes.append((item, (round(centro - meia), regioes.BIGORNA_CARTA_Y0,
                                      round(centro + meia), regioes.BIGORNA_CARTA_Y1)))
        opcoes.sort(key=lambda opcao: opcao[1][0])
        return textos, opcoes if len(opcoes) >= self.MINIMO_DE_OPCOES_NA_BIGORNA else []

    MINIMO_DE_AUGMENTS = 2  # um nome só pode ser engano do OCR (ou um balão de dica)

    def ler_augments(self, imagem):
        """Opções da escolha de augment, da esquerda para a direita: [(augment, x do centro do nome)],
        em pixels de 2560x1440. Primeiro sem ampliar (rápido); se achar só um, tenta ampliado."""
        faixa = regioes.AUGMENT_NOMES
        para_referencia = regioes.REFERENCIA[0] / imagem.width
        recorte = _recorte(imagem, faixa)
        textos, opcoes = [], []
        for ampliar in (1, 2):
            linhas = ocr.ler_linhas(recorte, ampliar=ampliar)
            textos = [linha.texto for linha in linhas]
            opcoes = []
            for linha in linhas:
                augment = self.tradutor.augment_do_texto(linha.texto)
                if augment and all(augment.id != a.id for a, _ in opcoes):
                    opcoes.append((augment, round(faixa[0] + (linha.x + linha.largura / 2) * para_referencia)))
            if len(opcoes) != 1:
                break
        opcoes.sort(key=lambda opcao: opcao[1])
        return textos, opcoes if len(opcoes) >= self.MINIMO_DE_AUGMENTS else []

    def ler(self, imagem):
        leitura = LeituraDaTela()
        texto_nivel, leitura.nivel, leitura.xp = self.ler_nivel(imagem)
        texto_estagio, leitura.estagio = self.ler_estagio(imagem)
        texto_ouro, leitura.ouro = self.ler_ouro(imagem)
        textos_loja, leitura.loja = self.ler_loja(imagem)
        textos_tracos, leitura.tracos, leitura.tracos_escondidos = self.ler_tracos(imagem)
        detalhes_itens, leitura.itens = self.ler_itens(imagem)
        textos_bigorna, leitura.bigorna = self.ler_bigorna(imagem)
        textos_augments, leitura.augments = self.ler_augments(imagem)
        leitura.textos_crus = {
            "nivel": texto_nivel, "estagio": texto_estagio, "ouro": texto_ouro, "loja": textos_loja,
            "tracos": textos_tracos, "itens": detalhes_itens, "bigorna": textos_bigorna,
            "augments": textos_augments,
        }
        return leitura
