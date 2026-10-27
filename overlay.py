"""Overlay por cima do jogo: mostra a comp alvo e marca na loja o que comprar.

É uma janela comum do Windows, transparente, sempre por cima e que deixa o clique
passar para o jogo. Não mexe no jogo (seguro com o Vanguard), mas por isso só
aparece com o TFT em "Tela cheia sem bordas": em tela cheia exclusiva o jogo cobre tudo.

O conteúdo vem do app (dados/overlay.json). Abre pelo botão "Overlay no jogo" do app,
ou à mão:  pythonw overlay.py
"""

import ctypes
import json
import sys
import tkinter as tk

from PIL import ImageTk

from interface import desenho_overlay
from visao import estado_compartilhado, regioes
from visao.captura import monitor_do_jogo

ATUALIZAR_A_CADA_MS = 1000
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
        self.pincel = desenho_overlay.Pincel(monitor["width"] / regioes.REFERENCIA[0])
        self.canvas = tk.Canvas(raiz, bg=COR_INVISIVEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.imagens = []         # o Tk só mostra a imagem enquanto alguém guarda uma referência a ela
        self.ultimos_dados = None  # só redesenha quando o app muda alguma coisa

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
            self.imagens = []
            if dados:
                self.desenhar_loja(dados.get("loja", []))
                if dados.get("comp"):
                    self.desenhar_painel(dados["comp"], dados.get("dicas", []), dados.get("itens_agora", []))
        self.raiz.attributes("-topmost", True)  # o jogo às vezes "rouba" o topo ao ganhar foco
        self.raiz.after(ATUALIZAR_A_CADA_MS, self.atualizar)

    def _colocar(self, imagem, x, y):
        foto = ImageTk.PhotoImage(imagem)
        self.imagens.append(foto)
        self.canvas.create_image(x, y, image=foto, anchor="nw")

    def desenhar_loja(self, selos):
        """Moldura por fora da carta (mesma folga nos 4 lados), para não tapar o nome que a leitura da tela usa."""
        for selo, (x0, y0, x1, y1) in zip(selos, regioes.CARTAS_DA_LOJA):
            if selo:
                imagem, dx, dy = desenho_overlay.marcacao_da_loja(selo, x1 - x0, y1 - y0, FOLGA_DA_MOLDURA, self.pincel)
                self._colocar(imagem, self.px(x0) + dx, self.px(y0) + dy)

    def desenhar_painel(self, comp, dicas=(), itens_agora=()):
        """Coloca a versão mais completa do painel que caiba acima do painel de traços do jogo."""
        itens_agora = list(itens_agora)[:FRASES_DE_ITEM_NO_OVERLAY]
        for com_tracos, com_itens, quantas_dicas in VERSOES_DO_PAINEL:
            imagem = desenho_overlay.painel(comp, list(dicas)[:quantas_dicas], itens_agora, self.pincel,
                                            PAINEL_LARGURA, com_tracos, com_itens)
            if self.px(PAINEL_Y) + imagem.height <= self.px(PAINEL_Y_MAXIMO):
                break
        self._colocar(imagem, self.px(PAINEL_X), self.px(PAINEL_Y))


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

    Overlay(raiz, monitor, pid_do_app).atualizar()
    raiz.mainloop()


if __name__ == "__main__":
    main()
