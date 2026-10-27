"""Overlay por cima do jogo: mostra a comp alvo e marca na loja o que comprar.

É uma janela comum do Windows, transparente, sempre por cima e que deixa o clique
passar para o jogo. Não mexe no jogo (seguro com o Vanguard), mas por isso só
aparece com o TFT em "Tela cheia sem bordas": em tela cheia exclusiva o jogo cobre tudo.

O conteúdo vem do app (dados/overlay.json). Abre pelo botão "Overlay no jogo" do app,
ou à mão:  pythonw overlay.py
"""

import ctypes
import ctypes.wintypes
import json
import sys
import tkinter as tk

import numpy as np
from PIL import ImageTk

from interface import desenho_overlay
from visao import estado_compartilhado, regioes
from visao.captura import capturar_regiao, monitor_do_jogo

ATUALIZAR_A_CADA_MS = 1000
OLHAR_O_MOUSE_A_CADA_MS = 80
OLHAR_A_BIGORNA_A_CADA_MS = 300
# com a bigorna aberta, a faixa logo abaixo das cartas é um fundo azul-esverdeado escuro: vermelho
# médio 7 a 9 e verde 36 a 40. Com a loja ou outra tela, o vermelho fica entre 18 e 60.
FUNDO_DA_BIGORNA_VERMELHO_MAXIMO = 12
FUNDO_DA_BIGORNA_VERDE_ACIMA_DO_VERMELHO = 20
FOLGA_DA_MOLDURA_DA_BIGORNA, ESPESSURA_DA_MOLDURA_DA_BIGORNA = 1, 4
COR_INVISIVEL = "#010203"      # o que for desta cor fica transparente
OPACIDADE = 0.95
FOLGA_DA_MOLDURA = 4  # pixels (de 2560x1440) entre a carta da loja e a moldura do overlay
PAINEL_X, PAINEL_Y, PAINEL_LARGURA = 60, 70, 640  # canto de cima à esquerda, acima dos traços (pixels de 2560x1440)
PAINEL_Y_MAXIMO = 330  # daqui para baixo fica o painel de traços, que a leitura da tela precisa enxergar
# se o painel não couber, vai tirando partes nesta ordem: (mostra traços, mostra itens, quantas dicas)
VERSOES_DO_PAINEL = [(True, True, 2), (True, True, 1), (False, True, 1), (False, True, 0), (False, False, 1)]
FRASES_DE_ITEM_NO_OVERLAY = 3


# ---------------------------------------------------------------- Windows

def deixar_clique_passar(janela):
    """Marca a janela como 'transparente para o mouse' e fora da barra de tarefas/Alt+Tab."""
    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
    usuario = ctypes.windll.user32
    hwnd = usuario.GetParent(janela.winfo_id())
    estilo = usuario.GetWindowLongW(hwnd, GWL_EXSTYLE)
    usuario.SetWindowLongW(hwnd, GWL_EXSTYLE,
                           estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


def posicao_do_mouse():
    """Onde está o mouse na tela. Só lê a posição: a janela continua deixando o clique passar."""
    ponto = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(ponto))
    return ponto.x, ponto.y


def processo_vivo(pid):
    """O overlay fecha sozinho quando o app (o processo que o abriu) fecha."""
    PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
    kernel = ctypes.windll.kernel32
    processo = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not processo:
        return False
    codigo = ctypes.c_ulong()
    kernel.GetExitCodeProcess(processo, ctypes.byref(codigo))
    kernel.CloseHandle(processo)
    return codigo.value == STILL_ACTIVE


# ---------------------------------------------------------------- desenho

class Overlay:
    """Coloca na tela as imagens feitas em interface/desenho_overlay.py."""

    def __init__(self, raiz, monitor, pid_do_app=None):
        self.raiz = raiz
        self.pid_do_app = pid_do_app
        self.canto_do_monitor = (monitor.get("left", 0), monitor.get("top", 0))
        self.pincel = desenho_overlay.Pincel(monitor["width"] / regioes.REFERENCIA[0])
        self.canvas = tk.Canvas(raiz, bg=COR_INVISIVEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.imagens = []         # o Tk só mostra a imagem enquanto alguém guarda uma referência a ela
        self.ultimos_dados = None  # só redesenha quando o app muda alguma coisa
        self.retratos = []         # (x0, y0, x1, y1, campeão) na tela, para mostrar o nome com o mouse em cima
        self.campeao_do_mouse = None
        self.foto_da_etiqueta = None
        self.bigorna = None              # a opção que o app mandou marcar (some se a bigorna não está na tela)
        self.bigorna_desenhada = False

    def px(self, valor):
        return self.pincel.px(valor)

    def atualizar(self):
        if self.pid_do_app and not processo_vivo(self.pid_do_app):
            self.raiz.destroy()
            return
        dados = estado_compartilhado.ler()
        chave = json.dumps(dados, sort_keys=True, ensure_ascii=False)
        if chave != self.ultimos_dados:
            self.ultimos_dados = chave
            self.canvas.delete("all")
            self.imagens, self.retratos, self.campeao_do_mouse = [], [], None
            self.bigorna, self.bigorna_desenhada = None, False
            if dados and not dados.get("fora_do_jogo"):
                self.desenhar_loja(dados.get("loja", []))
                if dados.get("comp"):
                    self.desenhar_painel(dados["comp"], dados.get("dicas", []), dados.get("itens_agora", []))
                self.bigorna = dados.get("bigorna")
                self.mostrar_ou_esconder_bigorna()
                if dados.get("augment"):
                    self.desenhar_augments(dados["augment"])
        self.raiz.attributes("-topmost", True)  # o jogo às vezes "rouba" o topo ao ganhar foco
        self.raiz.after(ATUALIZAR_A_CADA_MS, self.atualizar)

    def olhar_o_mouse(self):
        """Com o mouse em cima de um retrato do painel, mostra o nome do campeão logo abaixo dele."""
        x, y = posicao_do_mouse()
        x, y = x - self.canto_do_monitor[0], y - self.canto_do_monitor[1]
        embaixo = next((r for r in self.retratos if r[0] <= x <= r[2] and r[1] <= y <= r[3]), None)
        if embaixo is not self.campeao_do_mouse:
            self.campeao_do_mouse = embaixo
            self.canvas.delete("etiqueta")
            if embaixo:
                x0, _, x1, y1, campeao = embaixo
                imagem = desenho_overlay.etiqueta_do_campeao(campeao, self.pincel)
                self.foto_da_etiqueta = ImageTk.PhotoImage(imagem)
                self.canvas.create_image(round((x0 + x1 - imagem.width) / 2), y1 + self.px(6),
                                         image=self.foto_da_etiqueta, anchor="nw", tags="etiqueta")
        self.raiz.after(OLHAR_O_MOUSE_A_CADA_MS, self.olhar_o_mouse)

    def olhar_a_bigorna(self):
        """A cada 0,3 s: a moldura da bigorna só fica enquanto a bigorna está aberta na tela. Fechou
        (você escolheu, o tempo acabou ou você fechou a janela) = some na hora, sem esperar o app."""
        self.mostrar_ou_esconder_bigorna()
        self.raiz.after(OLHAR_A_BIGORNA_A_CADA_MS, self.olhar_a_bigorna)

    def mostrar_ou_esconder_bigorna(self):
        aberta = bool(self.bigorna) and self._bigorna_aberta_na_tela()
        if aberta and not self.bigorna_desenhada:
            self.desenhar_bigorna(self.bigorna)
        elif not aberta and self.bigorna_desenhada:
            self.canvas.delete("bigorna")
        self.bigorna_desenhada = aberta

    def _bigorna_aberta_na_tela(self):
        """A faixa logo abaixo das cartas tem o fundo azul-esverdeado da bigorna?"""
        x0, y0, x1, y1 = regioes.BIGORNA_FAIXA_DE_BAIXO
        esquerda, topo = self.canto_do_monitor
        imagem = capturar_regiao(esquerda + self.px(x0), topo + self.px(y0), self.px(x1 - x0), self.px(y1 - y0))
        vermelho, verde, _ = np.asarray(imagem, dtype=float).mean(axis=(0, 1))
        return (vermelho <= FUNDO_DA_BIGORNA_VERMELHO_MAXIMO
                and verde - vermelho >= FUNDO_DA_BIGORNA_VERDE_ACIMA_DO_VERMELHO)

    def _colocar(self, imagem, x, y, marca=""):
        foto = ImageTk.PhotoImage(imagem)
        self.imagens.append(foto)
        self.canvas.create_image(x, y, image=foto, anchor="nw", tags=marca)

    def desenhar_loja(self, selos):
        """Moldura por fora da carta (mesma folga nos 4 lados), para não tapar o nome que a leitura da tela usa."""
        for selo, (x0, y0, x1, y1) in zip(selos, regioes.CARTAS_DA_LOJA):
            if selo:
                imagem, dx, dy = desenho_overlay.marcacao_da_loja(selo, x1 - x0, y1 - y0, FOLGA_DA_MOLDURA, self.pincel)
                self._colocar(imagem, self.px(x0) + dx, self.px(y0) + dy)

    def desenhar_bigorna(self, bigorna):
        """Moldura na opção da bigorna que vale pegar e, acima do ícone, 'PEGUE · motivo'."""
        x0, y0, x1, y1 = bigorna["caixa"]
        imagem, dx, dy = desenho_overlay.marcacao_da_loja(
            "PEGUE", x1 - x0, y1 - y0, FOLGA_DA_MOLDURA_DA_BIGORNA, self.pincel, com_etiqueta=False,
            espessura=ESPESSURA_DA_MOLDURA_DA_BIGORNA)
        self._colocar(imagem, self.px(x0) + dx, self.px(y0) + dy, marca="bigorna")
        aviso = desenho_overlay.aviso(f"PEGUE · {bigorna['motivo']}", self.pincel)
        self._colocar(aviso, round(self.px((x0 + x1) / 2) - aviso.width / 2),
                      self.px(regioes.BIGORNA_ICONE_Y0) - aviso.height - self.px(6), marca="bigorna")

    def desenhar_augments(self, opcoes):
        """Acima do nome de cada augment: 'PEGUE · motivo' (verde) no melhor e 'nota · motivo' nos outros."""
        for opcao in opcoes:
            if opcao["melhor"]:
                aviso = desenho_overlay.aviso(f"PEGUE · {opcao['motivo']}", self.pincel)
            else:
                aviso = desenho_overlay.aviso(f"{opcao['nota']} · {opcao['motivo']}", self.pincel,
                                              cor_da_borda=desenho_overlay.COR_AVISO_FRACO)
            self._colocar(aviso, round(self.px(opcao["x"]) - aviso.width / 2),
                          self.px(regioes.AUGMENT_AVISO_Y) - aviso.height)

    def desenhar_painel(self, comp, dicas=(), itens_agora=()):
        """Coloca a versão mais completa do painel que caiba acima do painel de traços do jogo."""
        itens_agora = list(itens_agora)[:FRASES_DE_ITEM_NO_OVERLAY]
        for com_tracos, com_itens, quantas_dicas in VERSOES_DO_PAINEL:
            desenhado = desenho_overlay.painel(comp, list(dicas)[:quantas_dicas], itens_agora, self.pincel,
                                               PAINEL_LARGURA, com_tracos, com_itens)
            if self.px(PAINEL_Y) + desenhado.imagem.height <= self.px(PAINEL_Y_MAXIMO):
                break
        x, y = self.px(PAINEL_X), self.px(PAINEL_Y)
        self._colocar(desenhado.imagem, x, y)
        self.retratos = [(x + x0, y + y0, x + x1, y + y1, campeao) for x0, y0, x1, y1, campeao in desenhado.retratos]


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # pixels reais, sem a escala do Windows
    except (AttributeError, OSError):
        pass
    pid_do_app = int(sys.argv[1]) if len(sys.argv) > 1 else None
    monitor = monitor_do_jogo()

    raiz = tk.Tk()
    raiz.overrideredirect(True)  # sem borda nem barra de título
    raiz.geometry(f"{monitor['width']}x{monitor['height']}+{monitor['left']}+{monitor['top']}")
    raiz.configure(bg=COR_INVISIVEL)
    raiz.attributes("-transparentcolor", COR_INVISIVEL)
    raiz.attributes("-alpha", OPACIDADE)
    raiz.attributes("-topmost", True)
    raiz.update_idletasks()
    deixar_clique_passar(raiz)

    overlay = Overlay(raiz, monitor, pid_do_app)
    overlay.atualizar()
    overlay.olhar_o_mouse()
    overlay.olhar_a_bigorna()
    raiz.mainloop()


if __name__ == "__main__":
    main()
