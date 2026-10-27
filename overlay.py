"""Overlay por cima do jogo: mostra a comp alvo e marca na loja o que comprar.

É uma janela comum do Windows, transparente, sempre por cima e que deixa o clique
passar para o jogo. Não mexe no jogo (seguro com o Vanguard), mas por isso só
aparece com o TFT em "Tela cheia sem bordas": em tela cheia exclusiva o jogo cobre tudo.

O conteúdo vem do app (dados/overlay.json). Abre pelo botão "Overlay no jogo" do app,
ou à mão:  pythonw overlay.py
"""

import ctypes
import sys
import tkinter as tk
from tkinter import font as tkfont

from interface.estilo import CORES_CUSTO
from visao import estado_compartilhado, regioes
from visao.captura import monitor_do_jogo

ATUALIZAR_A_CADA_MS = 1000
COR_INVISIVEL = "#010203"      # o que for desta cor fica transparente
OPACIDADE = 0.93
FOLGA_DA_MOLDURA = 4  # pixels (de 2560x1440) entre a carta da loja e a moldura do overlay
PAINEL_X, PAINEL_Y, PAINEL_LARGURA = 60, 70, 600  # canto de cima à esquerda, acima dos traços (pixels de 2560x1440)
PAINEL_Y_MAXIMO = 330  # daqui para baixo fica o painel de traços, que a leitura da tela precisa enxergar
# se o painel não couber, vai tirando partes nesta ordem: (mostra traços, mostra itens, quantas dicas)
VERSOES_DO_PAINEL = [(True, True, 2), (False, True, 2), (False, False, 2), (False, False, 1)]
FONTE = "Segoe UI"

COR_FUNDO, COR_BORDA, COR_TEXTO, COR_APAGADO = "#14171f", "#e8b941", "#f2f2f2", "#8a93a3"
COR_DICA = "#7fe3a0"
COR_FRASE_ITEM = {"montar": "#7fe3a0", "quase": "#e8c95a", "util": "#8fbaf5"}
FRASES_DE_ITEM_NO_OVERLAY = 3
COR_SELO = {estado_compartilhado.SELO_COMPRE: "#2fb35a", estado_compartilhado.SELO_SOBE: "#e8b941"}
COR_TRACO = {1: ("#8c5a3c", "#fff"), 2: ("#aebdca", "#17202a"), 3: ("#e8b941", "#2a1d00"), 4: ("#d9b8ff", "#1b1b2a")}
COR_ITEM = {"Pode montar": ("#2fb35a", "#fff"), "Falta 1 componente": ("#c9a227", "#2a1d00")}


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
    def __init__(self, raiz, monitor, pid_do_app=None):
        self.raiz = raiz
        self.pid_do_app = pid_do_app
        self.escala = monitor["width"] / regioes.REFERENCIA[0]
        self.canvas = tk.Canvas(raiz, bg=COR_INVISIVEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.fonte_titulo = tkfont.Font(family=FONTE, size=-self.px(20), weight="bold")
        self.fonte = tkfont.Font(family=FONTE, size=-self.px(15), weight="bold")
        self.fonte_pequena = tkfont.Font(family=FONTE, size=-self.px(13))

    def px(self, valor):
        """Converte pixels de 2560x1440 para a resolução do monitor."""
        return round(valor * self.escala)

    def atualizar(self):
        if self.pid_do_app and not processo_vivo(self.pid_do_app):
            self.raiz.destroy()
            return
        self.canvas.delete("all")
        dados = estado_compartilhado.ler()
        if dados:
            self.desenhar_loja(dados.get("loja", []))
            if dados.get("comp"):
                self.desenhar_painel(dados["comp"], dados.get("dicas", []), dados.get("itens_agora", []))
        self.raiz.attributes("-topmost", True)  # o jogo às vezes "rouba" o topo ao ganhar foco
        self.raiz.after(ATUALIZAR_A_CADA_MS, self.atualizar)

    def desenhar_loja(self, selos):
        for selo, (x0, y0, x1, y1) in zip(selos, regioes.CARTAS_DA_LOJA):
            if not selo:
                continue
            cor = COR_SELO[selo]
            # moldura por fora da carta (mesma folga nos 4 lados), para não tapar o nome que a leitura da tela usa
            f = FOLGA_DA_MOLDURA
            self.canvas.create_rectangle(self.px(x0 - f), self.px(y0 - f), self.px(x1 + f), self.px(y1 + f),
                                         outline=cor, width=self.px(5))
            self._chip(self.px(x0 + 8), self.px(y0 + 8), selo, cor, "#fff" if cor == "#2fb35a" else "#2a1d00",
                       marca="loja")

    def desenhar_painel(self, comp, dicas=(), itens_agora=()):
        """Desenha a versão mais completa do painel que caiba acima do painel de traços do jogo."""
        for com_tracos, com_itens, quantas_dicas in VERSOES_DO_PAINEL:
            self.canvas.delete("painel")
            baixo = self._painel(comp, list(dicas)[:quantas_dicas], com_tracos, com_itens,
                                 list(itens_agora)[:FRASES_DE_ITEM_NO_OVERLAY])
            if baixo <= self.px(PAINEL_Y_MAXIMO):
                return

    def _painel(self, comp, dicas, com_tracos, com_itens, itens_agora=()):
        """Desenha o painel e devolve onde ele termina (y de baixo)."""
        x0, y0 = self.px(PAINEL_X), self.px(PAINEL_Y)
        x1 = x0 + self.px(PAINEL_LARGURA)
        margem = self.px(12)
        fundo = self.canvas.create_rectangle(x0, y0, x1, y0, fill=COR_FUNDO, outline=COR_BORDA, width=self.px(2),
                                             tags="painel")
        x, y = x0 + margem, y0 + margem

        titulo = self.canvas.create_text(x, y, text=comp["nome"], anchor="nw", fill=COR_TEXTO,
                                         font=self.fonte_titulo, width=x1 - x - margem, tags="painel")
        y = self.canvas.bbox(titulo)[3] + self.px(2)  # o nome pode quebrar em duas linhas
        self.canvas.create_text(x, y, anchor="nw", fill=COR_APAGADO, font=self.fonte_pequena, tags="painel",
                                text=f"{comp['origem']} · você tem {comp['tem']}/{comp['total']}")
        y += self.px(24)

        chips = []
        for campeao in comp["campeoes"]:
            cor = CORES_CUSTO.get(campeao["custo"], "#888")
            if campeao["estrelas"]:
                chips.append((f"{campeao['nome']} {'★' * campeao['estrelas']}", cor, "#fff", None))
            else:
                chips.append((campeao["nome"], "#262b36", COR_APAGADO, cor))
        y = self._linha_de_chips(chips, x, x1 - margem, y)

        tracos = [(t["texto"], *COR_TRACO.get(t["estilo"], ("#666", "#fff")), None) for t in comp["tracos"]]
        if tracos and com_tracos:
            y = self._linha_de_chips(tracos, x, x1 - margem, y + self.px(4), fonte=self.fonte_pequena)

        if itens_agora and com_itens:  # com componentes: o que montar e em quem
            for frase in itens_agora:
                texto = self.canvas.create_text(x, y + self.px(4), anchor="nw", font=self.fonte_pequena,
                                                fill=COR_FRASE_ITEM.get(frase["tipo"], COR_TEXTO),
                                                text=frase["texto"], width=x1 - x - margem, tags="painel")
                y = self.canvas.bbox(texto)[3] + self.px(2)
        elif comp["itens"] and com_itens:  # sem componentes: a build do carry
            self.canvas.create_text(x, y + self.px(4), anchor="nw", fill=COR_APAGADO, font=self.fonte_pequena,
                                    text=f"Itens para {comp['carry']}:", tags="painel")
            itens = [(i["nome"], *COR_ITEM.get(i["status"], ("#262b36", COR_APAGADO)), None) for i in comp["itens"]]
            y = self._linha_de_chips(itens, x, x1 - margem, y + self.px(26), fonte=self.fonte_pequena)

        for dica in dicas:  # dicas do momento: subir de nível, rolar, juros
            texto = self.canvas.create_text(x, y + self.px(4), anchor="nw", fill=COR_DICA, font=self.fonte_pequena,
                                            text=f"• {dica}", width=x1 - x - margem, tags="painel")
            y = self.canvas.bbox(texto)[3] + self.px(2)

        baixo = y + margem - self.px(6)
        self.canvas.coords(fundo, x0, y0, x1, baixo)
        return baixo

    def _chip(self, x, y, texto, fundo, cor_texto, borda=None, fonte=None, marca="painel"):
        """Etiqueta com fundo. Devolve (largura, altura). `marca` agrupa o desenho para apagar junto."""
        fonte = fonte or self.fonte
        folga_x, folga_y = self.px(8), self.px(3)
        largura = fonte.measure(texto) + 2 * folga_x
        altura = fonte.metrics("linespace") + 2 * folga_y
        self.canvas.create_rectangle(x, y, x + largura, y + altura, fill=fundo, outline=borda or fundo,
                                     width=self.px(2), tags=marca)
        self.canvas.create_text(x + folga_x, y + folga_y, text=texto, anchor="nw", fill=cor_texto, font=fonte,
                                tags=marca)
        return largura, altura

    def _linha_de_chips(self, chips, x_inicio, x_fim, y, fonte=None):
        """Coloca as etiquetas lado a lado, quebrando a linha quando não cabem. Devolve o y de baixo."""
        espaco = self.px(6)
        x, altura = x_inicio, 0
        for texto, fundo, cor_texto, borda in chips:
            largura = (fonte or self.fonte).measure(texto) + 2 * self.px(8)
            if x > x_inicio and x + largura > x_fim:
                x, y = x_inicio, y + altura + espaco
            largura, altura = self._chip(x, y, texto, fundo, cor_texto, borda, fonte)
            x += largura + espaco
        return y + altura + espaco


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
