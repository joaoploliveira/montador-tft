"""Monta o HTML do cartão de uma comp (só apresentação; as contas vêm da pasta logica/)."""

from html import escape

from interface.estilo import CORES_CUSTO, CORES_ESTILO
from interface.imagens import icone
from logica import itens as modulo_itens
from logica import montador
from visao import estado_compartilhado

CLASSE_ORIGEM = {"Algoritmo": "origem-algoritmo", "Meta": "origem-meta", "Minhas comps": "origem-minhas"}
ROTULO_ORIGEM = {"Algoritmo": "Para você", "Meta": "🏆 Meta", "Minhas comps": "📌 Minha"}
CLASSE_STATUS = {"Pode montar": "pode", "Falta 1 componente": "falta1"}


def _retrato(campeao, situacao, chance=None):
    estrelas = situacao.unidades.get(campeao.id)
    cor = CORES_CUSTO.get(campeao.custo, "#888")
    if estrelas:
        selo = f'<div class="estrelas">{"★" * estrelas}</div>'
    elif chance is not None:
        texto = f"{chance.chance_por_loja:.0%}" if chance.chance_por_loja else "—"
        selo = f'<div class="chance" title="chance de aparecer por loja">{texto}</div>'
    else:
        selo = ""
    return (
        f'<div class="retrato {"tem" if estrelas else "falta"}">'
        f'<div class="foto" style="--cor:{cor}; background-image:url({icone("campeao", campeao.chave)})">{selo}</div>'
        f'<div class="nome">{escape(campeao.nome)}</div></div>'
    )


def _tracos(comp):
    selos = []
    for traco in comp.tracos:
        if traco.ativo:
            fundo, texto = CORES_ESTILO.get(traco.estilo, ("#666", "#fff"))
            selos.append(f'<span class="traco" style="background:{fundo}; color:{texto}">{escape(traco.texto())}</span>')
        elif traco.faltam == 1:
            selos.append(f'<span class="traco quase" title="falta 1 para ativar">{escape(traco.texto())}</span>')
    return f'<div class="tracos">{"".join(selos)}</div>'


def _itens(comp, catalogo, componentes):
    linhas = []
    for carry in modulo_itens.carregadores(comp):
        sugestoes = modulo_itens.itens_para_campeao(carry, componentes, catalogo)
        if not sugestoes:
            continue
        icones = "".join(
            f'<div class="item" title="{escape(s.item.nome)} — {escape(s.status)}" '
            f'style="background-image:url({icone("item", s.item.chave)})">'
            f'<div class="bola {CLASSE_STATUS.get(s.status, "falta2")}"></div></div>'
            for s in sugestoes
        )
        linhas.append(f'<div class="itens-linha"><b>{escape(carry.nome)}</b> {icones}</div>')
    if not linhas:
        return ""
    legenda = '<div class="legenda">🟢 dá para montar · 🟡 falta 1 componente · ⚪ faltam 2</div>'
    return "".join(linhas) + legenda


def _numeros(comp):
    e = comp.estatisticas
    if not e.get("jogos"):
        return f'<div class="numeros">{escape(e["notas"])}</div>' if e.get("notas") else ""
    itens = ", ".join(e.get("itens_do_carry", []))
    return (
        '<div class="numeros">'
        f'<span>Colocação média <b>{e["colocacao_media"]}</b></span>'
        f'<span>Top 4 <b>{e["top4"]:.0%}</b></span>'
        f'<span>Vitória <b>{e["vitoria"]:.0%}</b></span>'
        f'<span><b>{e["jogos"]}</b> jogos</span>'
        + (f'<span>Itens no {escape(e["carry"])}: {escape(itens)}</span>' if itens else "")
        + "</div>"
    )


def _plano(comp):
    """Como jogar a comp (só comps meta: vem dos tabuleiros de alto elo)."""
    plano = comp.estatisticas.get("plano")
    if not plano:
        return ""
    essenciais = comp.estatisticas.get("essenciais") or []
    centrais = f'<div class="essenciais">Peças centrais: {escape(", ".join(essenciais))}</div>' if essenciais else ""
    return f'<div class="plano">🧭 <b>{escape(plano.estilo)}</b> · {escape(plano.texto)}{centrais}</div>'


def html_da_comp(comp, situacao, catalogo, componentes):
    chances = montador.chance_dos_que_faltam(comp, situacao, catalogo)
    retratos = "".join(_retrato(c, situacao, chances.get(c.id)) for c in comp.campeoes)
    return (
        '<div class="cartao">'
        '<div class="cartao-topo">'
        f'<span class="origem {CLASSE_ORIGEM.get(comp.origem, "")}">{ROTULO_ORIGEM.get(comp.origem, comp.origem)}</span>'
        f'<span class="cartao-nome">{escape(comp.nome)}</span>'
        f'<span class="tem">Você tem {len(comp.tem)}/{len(comp.campeoes)}</span>'
        "</div>"
        f"{_numeros(comp)}"
        f"{_plano(comp)}"
        f'<div class="retratos">{retratos}</div>'
        f"{_tracos(comp)}"
        f"{_itens(comp, catalogo, componentes)}"
        "</div>"
    )


def html_da_loja(loja, selos):
    """Faixa '🛒 Loja agora': as 5 cartas com o selo de cada uma (COMPRE, SOBE ★ ou nada)."""
    classes = {estado_compartilhado.SELO_COMPRE: "compre", estado_compartilhado.SELO_SOBE: "sobe"}
    cartas = []
    for campeao, selo in zip(loja, selos):
        if campeao is None:
            cartas.append('<div class="carta-loja vazia"></div>')
            continue
        etiqueta = f'<span class="selo-loja {classes[selo]}">{selo}</span>' if selo else ""
        cor = CORES_CUSTO.get(campeao.custo, "#888")
        cartas.append(
            f'<div class="carta-loja{" destaque" if selo else ""}" style="--cor:{cor}">'
            f'<div class="foto" style="background-image:url({icone("campeao", campeao.chave)})">{etiqueta}</div>'
            f"<div>{escape(campeao.nome)}</div></div>"
        )
    return f'<div class="loja-agora"><b>🛒 Loja agora</b><div class="cartas">{"".join(cartas)}</div></div>'


def html_das_dicas(dicas):
    """Caixa '💡 Agora': dicas de nível, rolagem e juros para o momento da partida."""
    if not dicas:
        return ""
    linhas = "".join(
        f'<div class="dica{" urgente" if d.urgente else ""}">{d.icone} {escape(d.texto)}</div>' for d in dicas
    )
    return f'<div class="dicas"><b>💡 Agora</b>{linhas}</div>'


def html_da_bigorna(escolha):
    """Caixa '🔨 Bigorna': qual opção pegar e por quê."""
    return (f'<div class="dicas itens-agora"><b>🔨 Bigorna</b>'
            f'<div class="dica urgente">Pegue {escape(escolha.item.nome)}</div>'
            f'<div class="dica">{escape(escolha.motivo)}</div></div>')


ICONE_DA_FRASE = {"montar": "🛠️", "quase": "🟡", "util": "🎯"}


def html_dos_itens_agora(frases, para_comp):
    """Caixa '🛠️ Itens agora': o que montar com seus componentes e em quem, na comp alvo."""
    linhas = "".join(
        f'<div class="dica{" urgente" if f.tipo == "montar" else ""}">{ICONE_DA_FRASE[f.tipo]} {escape(f.texto)}</div>'
        for f in frases
    )
    return f'<div class="dicas itens-agora"><b>🛠️ Itens agora</b> · {escape(para_comp)}{linhas}</div>'
