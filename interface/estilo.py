"""CSS da página: cores de custo, selos de traço, cartões das comps e botões com retrato."""

from interface.imagens import icone

CORES_CUSTO = {1: "#9aa0a6", 2: "#1fa34a", 3: "#2f7ae5", 4: "#b14be0", 5: "#f0b429"}
# selos dos traços: (fundo, texto) para bronze, prata, ouro e prismático
CORES_ESTILO = {1: ("#8c5a3c", "#fff"), 2: ("#aebdca", "#17202a"), 3: ("#e8b941", "#2a1d00"),
                4: ("linear-gradient(90deg,#f6a9d8,#a8c8ff,#b6f0c8)", "#1b1b2a")}

CSS_GERAL = """
<style>
[data-testid="stMainBlockContainer"], .block-container { padding-top: 3.5rem !important; max-width: 100%; }

/* ---------- cartão de comp ---------- */
.cartao { border: 1px solid rgba(128,128,128,.28); border-radius: 12px; padding: 12px 14px;
          margin-bottom: 12px; background: rgba(128,128,128,.06); }
.cartao-topo { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.cartao-nome { font-weight: 700; font-size: 1.05rem; flex: 1; min-width: 160px; }
.origem { font-size: .72rem; font-weight: 700; padding: 2px 8px; border-radius: 99px; text-transform: uppercase; letter-spacing: .03em; }
.origem-algoritmo { background: rgba(47,122,229,.18); color: #5b9cf0; }
.origem-meta { background: rgba(240,180,41,.18); color: #e0a520; }
.origem-minhas { background: rgba(31,163,74,.18); color: #2fb35a; }
.origem-suas { background: rgba(164,92,230,.18); color: #b47cf0; }
.tem { font-size: .85rem; font-weight: 700; padding: 2px 10px; border-radius: 99px; background: rgba(128,128,128,.16); }
.numeros { display: flex; gap: 14px; flex-wrap: wrap; font-size: .82rem; opacity: .85; margin: -4px 0 10px; }
.numeros b { font-size: .95rem; }
.numeros.previsao { color: #8fbaf5; margin-top: -6px; }

.retratos { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.retrato { width: 60px; text-align: center; font-size: .68rem; line-height: 1.15; }
.retrato .foto { position: relative; width: 56px; height: 56px; margin: 0 auto 3px; border-radius: 8px;
                 border: 3px solid var(--cor); background-size: cover; background-position: center; }
.retrato.falta .foto { filter: grayscale(.9); opacity: .55; }
.retrato .estrelas { position: absolute; left: 0; right: 0; bottom: -2px; color: #ffd75e; font-size: .8rem;
                     text-shadow: 0 0 3px #000, 0 0 3px #000; }
.retrato .chance { position: absolute; left: 0; right: 0; bottom: 0; font-weight: 700; color: #fff;
                   background: rgba(0,0,0,.65); border-radius: 0 0 5px 5px; font-size: .68rem; }
.retrato .nome { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.tracos { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.traco { font-size: .78rem; font-weight: 700; padding: 2px 9px; border-radius: 6px; }
.traco.quase { border: 1px dashed #8889; background: transparent; opacity: .8; font-weight: 500; }

.itens-linha { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: .8rem; margin-top: 4px; }
.item { position: relative; width: 30px; height: 30px; border-radius: 5px; background-size: cover; }
.item .bola { position: absolute; right: -3px; top: -3px; width: 10px; height: 10px; border-radius: 99px; border: 1px solid #0008; }
.bola.pode { background: #2fb35a; } .bola.falta1 { background: #f0b429; } .bola.falta2 { background: #8888; }
.legenda { font-size: .72rem; opacity: .65; }

/* ---------- botões de retrato (seu jogo) ---------- */
[class*="st-key-campeao_"] button, [class*="st-key-componente_"] button {
    position: relative; width: 62px; height: 62px; min-height: 0; padding: 0; border-radius: 8px; overflow: hidden;
    background-size: cover; background-position: center;
    display: flex; align-items: flex-end; justify-content: center;
}
[class*="st-key-campeao_"] button > div, [class*="st-key-campeao_"] button [data-testid="stMarkdownContainer"] {
    width: 100% !important; min-width: 0 !important;
}
/* nome do campeão numa faixa escura embaixo do retrato */
[class*="st-key-campeao_"] button p {
    width: 100% !important; margin: 0 !important; padding: 1px 2px !important;
    font-size: .58rem !important; font-weight: 700; color: #fff; line-height: 1.25 !important;
    background: rgba(0,0,0,.72); white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis;
    word-break: normal !important; overflow-wrap: normal !important;
}
/* estrelas no topo do retrato (o número vem no fim da chave do botão: _e1, _e2, _e3) */
[class*="st-key-campeao_"] button::before {
    position: absolute; top: 1px; left: 0; right: 0; text-align: center; color: #ffd75e; font-size: .8rem;
    text-shadow: 0 0 3px #000, 0 0 3px #000, 0 0 3px #000;
}
[class*="st-key-campeao_"][class*="_e1"] button::before { content: "★"; }
[class*="st-key-campeao_"][class*="_e2"] button::before { content: "★★"; }
[class*="st-key-campeao_"][class*="_e3"] button::before { content: "★★★"; }
[class*="st-key-componente_"] button p {
    color: #fff; font-weight: 800; font-size: .95rem; text-shadow: 0 0 3px #000, 0 0 3px #000, 0 0 3px #000;
}
[class*="st-key-campeao_"][class*="_nao"] button, [class*="st-key-componente_"][class*="_nao"] button {
    filter: grayscale(.9); opacity: .45;
}
[class*="st-key-campeao_"] button:hover, [class*="st-key-componente_"] button:hover { filter: none; opacity: 1; }
[class*="st-key-componente_"] button { width: 44px; height: 44px; border: 2px solid #8886; }
.custo-titulo { font-size: .78rem; font-weight: 700; margin: 6px 0 -6px; }

/* ---------- plano de jogo e dicas ---------- */
.plano { font-size: .82rem; margin: -2px 0 10px; padding: 6px 10px; border-radius: 8px;
         background: rgba(47,122,229,.10); border-left: 3px solid #5b9cf0; }
.plano .essenciais { opacity: .75; margin-top: 2px; }
.dicas { border: 1px solid rgba(47,179,90,.45); border-radius: 12px; padding: 10px 14px; margin-bottom: 12px;
         background: rgba(47,179,90,.07); }
.dica { font-size: .88rem; margin-top: 5px; }
.dica.urgente { font-weight: 700; }
.dicas.itens-agora { border-color: rgba(232,185,65,.45); background: rgba(232,185,65,.07); }

/* ---------- loja agora (leitura da tela) ---------- */
.loja-agora { border: 1px solid rgba(232,185,65,.45); border-radius: 12px; padding: 10px 14px;
              margin-bottom: 12px; background: rgba(232,185,65,.07); }
.loja-agora .cartas { display: flex; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.carta-loja { width: 84px; text-align: center; font-size: .75rem; font-weight: 600; opacity: .45; }
.carta-loja.destaque { opacity: 1; }
.carta-loja.vazia { height: 84px; border: 1px dashed #8885; border-radius: 8px; }
.carta-loja .foto { position: relative; width: 78px; height: 78px; margin: 0 auto 6px; border-radius: 8px;
                    border: 3px solid var(--cor); background-size: cover; }
.selo-loja { position: absolute; left: 50%; bottom: -8px; transform: translateX(-50%); white-space: nowrap;
             font-size: .66rem; font-weight: 800; padding: 1px 7px; border-radius: 99px; }
.selo-loja.compre { background: #2fb35a; color: #fff; }
.selo-loja.sobe { background: #e8b941; color: #2a1d00; }
</style>
"""


def css_dos_botoes(catalogo):
    """Uma regra por campeão/componente: a imagem de fundo e a cor da borda pelo custo."""
    regras = []
    for campeao in catalogo.campeoes.values():
        seletor = f'[class*="st-key-campeao_{campeao.id}_"] button'
        regras.append(
            f"{seletor} {{ background-image: url({icone('campeao', campeao.chave)}); "
            f"border: 3px solid {CORES_CUSTO.get(campeao.custo, '#888')}; }}"
        )
    for componente in catalogo.componentes():
        seletor = f'[class*="st-key-componente_{componente.id}_"] button'
        regras.append(f"{seletor} {{ background-image: url({icone('item', componente.chave)}); }}")
    return "<style>" + "\n".join(regras) + "</style>"
