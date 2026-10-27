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
# mudança média (0 a 255) da faixa de baixo das cartas que quer dizer "a bigorna fechou":
# entre prints da bigorna aberta fica até ~5 (mesmo com balão de dica); com a loja de volta, 18 a 26
MUDANCA_DE_BIGORNA_FECHADA = 12
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
        self.bigorna_na_tela = None    # a bigorna marcada agora (dados do app) e como estava a tela quando marcou
        self.faixa_da_bigorna = None
        self.bigorna_fechada = None    # a que já fechou: não volta mesmo que o app ainda não tenha percebido

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
            self.bigorna_na_tela = None
            if dados:
                self.desenhar_loja(dados.get("loja", []))
                if dados.get("comp"):
                    self.desenhar_painel(dados["comp"], dados.get("dicas", []), dados.get("itens_agora", []))
                if dados.get("bigorna") and dados["bigorna"] != self.bigorna_fechada:
                    self.desenhar_bigorna(dados["bigorna"])
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
        """Com uma bigorna marcada, confere a tela a cada 0,3 s: se ela fechou (você escolheu ou o
        tempo acabou), apaga a moldura na hora, sem esperar o app ler a tela de novo (até ~3 s)."""
        if self.bigorna_na_tela:
            mudanca = np.abs(self._faixa_de_baixo_da_bigorna() - self.faixa_da_bigorna).mean()
            if mudanca > MUDANCA_DE_BIGORNA_FECHADA:
                self.canvas.delete("bigorna")
                self.bigorna_fechada, self.bigorna_na_tela = self.bigorna_na_tela, None
        self.raiz.after(OLHAR_A_BIGORNA_A_CADA_MS, self.olhar_a_bigorna)

    def _faixa_de_baixo_da_bigorna(self):
        x0, y0, x1, y1 = regioes.BIGORNA_FAIXA_DE_BAIXO
        esquerda, topo = self.canto_do_monitor
        imagem = capturar_regiao(esquerda + self.px(x0), topo + self.px(y0), self.px(x1 - x0), self.px(y1 - y0))
        return np.asarray(imagem.convert("L"), dtype=float)

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
        self.bigorna_na_tela, self.faixa_da_bigorna = bigorna, self._faixa_de_baixo_da_bigorna()

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
