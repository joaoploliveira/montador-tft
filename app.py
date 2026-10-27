"""Montador de comps de TFT. Para abrir:  streamlit run app.py  (ou clique em iniciar.bat)

Este arquivo só monta a página. O visual (HTML/CSS) fica em interface/ e as contas em logica/.
"""

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

import atualizar
from dados import banco, riot
from interface import estilo
from interface.cartoes import (ROTULO_ORIGEM, html_da_bigorna, html_da_comp, html_da_loja, html_das_dicas,
                               html_dos_itens_agora)
from logica import catalogo as modulo_catalogo
from logica import itens as modulo_itens
from logica import dicas as modulo_dicas
from logica import aprendizado, manuais, meta, meu_desempenho, montador, taticas
from logica.loja import chance_na_loja
from visao import acompanhamento, estado_compartilhado
from visao.captura import capturar_tela
from visao.leitor import Leitor

st.set_page_config(page_title="Montador TFT", page_icon="🧩", layout="wide", initial_sidebar_state="collapsed")

ADICIONAR, REMOVER = "➕ Adicionar", "➖ Remover"
FONTES = ["Todas", "Para você", "Meta", "Minhas"]
BRANCO = "⠀"  # rótulo "vazio" para os botões de retrato
SEGUNDOS_ENTRE_LEITURAS = 2
PASTA_DO_APP = Path(__file__).resolve().parent


# ---------------------------------------------------------------- dados (com cache)

@st.cache_resource
def carregar_catalogo():
    return modulo_catalogo.carregar()


@st.cache_resource
def carregar_leitor():
    return Leitor(carregar_catalogo())


def banco_vazio():
    conexao = banco.conectar()
    vazio = conexao.execute("SELECT COUNT(*) FROM campeoes").fetchone()[0] == 0
    conexao.close()
    return vazio


def total_de_partidas():
    conexao = banco.conectar()
    total = conexao.execute("SELECT COUNT(*) FROM partidas").fetchone()[0]
    conexao.close()
    return total


def _situacao_de(chave):
    nivel, unidades, emblemas, fixos = chave
    return montador.Situacao(nivel=nivel, unidades=dict(unidades), emblemas=list(emblemas), fixos=list(fixos))


@st.cache_resource(show_spinner=False, max_entries=50)  # sem cópia: não quebra se o código mudar com o app aberto
def comps_do_algoritmo(_catalogo, chave_situacao, tamanho):
    return montador.sugerir_comps(_situacao_de(chave_situacao), _catalogo, quantidade=5, tamanho=tamanho)


@st.cache_resource(show_spinner=False, max_entries=50)
def comps_da_meta(_catalogo, chave_situacao, partidas):  # `partidas` só serve para renovar o cache
    return meta.comps_meta(_situacao_de(chave_situacao), _catalogo)


@st.cache_resource(show_spinner=False, max_entries=2)
def tabelas_de_taticas(_catalogo, partidas):
    """Tabelas da aba Táticas (calculadas uma vez por quantidade de partidas no banco)."""
    tabuleiros = taticas.ler_tabuleiros(_catalogo)
    if not tabuleiros:
        return None
    por_nivel = pd.DataFrame([
        {"Nível final": nivel, "Jogadores": f"{d.jogos / len(tabuleiros):.0%}",
         "Colocação média": round(d.media, 2), "Top 4": f"{d.top4:.0%}"}
        for nivel, d in taticas.desempenho_por_nivel(_catalogo, tabuleiros).items()
    ])
    forca = taticas.forca_dos_campeoes(_catalogo, tabuleiros)
    campeoes = pd.DataFrame([
        {"Campeão": c.nome, "Custo": c.custo, "Jogos": forca[c.id].jogos,
         "Colocação (ajustada)": round(forca[c.id].ajustada, 2), "Top 4": f"{forca[c.id].top4:.0%}",
         "Segura 3 itens": f"{c.taxa_de_itens:.0%}"}
        for c in _catalogo.campeoes.values() if c.id in forca
    ]).sort_values("Colocação (ajustada)")
    tracos = pd.DataFrame([
        {"Traço": _catalogo.tracos[id_traco].nome, "Nível": nivel, "Jogos": d.jogos,
         "Colocação (ajustada)": round(d.ajustada, 2), "Top 4": f"{d.top4:.0%}"}
        for (id_traco, nivel), d in taticas.forca_dos_tracos(_catalogo, tabuleiros).items()
        if not _catalogo.tracos[id_traco].unico
    ]).sort_values("Colocação (ajustada)")
    return {"partidas": len(tabuleiros) // 8, "por_nivel": por_nivel, "campeoes": campeoes, "tracos": tracos}


@st.cache_resource(show_spinner=False, max_entries=2)
def modelo_treinado(_catalogo, data_do_arquivo):  # `data_do_arquivo` só serve para renovar o cache ao treinar
    return aprendizado.carregar(_catalogo)


def modelo_atual(catalogo):
    """O modelo do alto elo (aba Aprendizado), ou None se ainda não foi treinado."""
    arquivo = aprendizado.ARQUIVO_DO_MODELO
    return modelo_treinado(catalogo, arquivo.stat().st_mtime if arquivo.exists() else 0)


# ---------------------------------------------------------------- estado do seu jogo

def iniciar_estado():
    st.session_state.setdefault("unidades", {})          # campeao_id -> estrelas
    st.session_state.setdefault("componentes", Counter())  # componente_id -> quantidade
    st.session_state.setdefault("nivel", 7)
    st.session_state.setdefault("overlay", overlay_aberto())
    st.session_state.setdefault("copias", {})            # campeao_id -> cópias compradas (leitura da tela)
    st.session_state.setdefault("acompanhamento", acompanhamento.Acompanhamento())
    st.session_state.setdefault("leitura", None)         # última leitura da tela
    st.session_state.setdefault("emblemas_lidos", [])    # ids de traço dos emblemas no banco
    st.session_state.setdefault("compras_recentes", [])
    # o nível lido da tela só pode entrar antes de o campo "Nível" ser desenhado
    nivel_lido = st.session_state.pop("nivel_lido", None)
    if nivel_lido:
        st.session_state.nivel = nivel_lido


# ---------------------------------------------------------------- overlay (janela por cima do jogo)

@st.cache_resource
def processo_do_overlay():
    """Guarda o processo do overlay entre as atualizações da página."""
    return {"processo": None}


def overlay_aberto():
    processo = processo_do_overlay()["processo"]
    return processo is not None and processo.poll() is None


def ligar_ou_desligar_overlay():
    guardado = processo_do_overlay()
    if overlay_aberto():
        guardado["processo"].terminate()
    guardado["processo"] = None
    if st.session_state.overlay:
        sem_console = Path(sys.executable).with_name("pythonw.exe")
        python = str(sem_console) if sem_console.exists() else sys.executable
        guardado["processo"] = subprocess.Popen([python, "overlay.py", str(os.getpid())], cwd=PASTA_DO_APP)


def removendo():
    return st.session_state.get("modo") == REMOVER


def clicar_campeao(id_campeao):
    unidades = st.session_state.unidades
    estrelas = unidades.get(id_campeao, 0) + (-1 if removendo() else 1)
    if estrelas <= 0:
        unidades.pop(id_campeao, None)
    else:
        unidades[id_campeao] = min(estrelas, 3)
    # a correção à mão vale também para as cópias contadas pela leitura da tela
    st.session_state.copias[id_campeao] = acompanhamento.COPIAS_POR_ESTRELA.get(unidades.get(id_campeao, 0), 0)


def clicar_componente(id_componente):
    componentes = st.session_state.componentes
    componentes[id_componente] = max(componentes[id_componente] + (-1 if removendo() else 1), 0)


def limpar_tudo():
    st.session_state.unidades = {}
    st.session_state.componentes = Counter()
    st.session_state.copias = {}
    st.session_state.acompanhamento = acompanhamento.Acompanhamento()
    st.session_state.compras_recentes = []


# ---------------------------------------------------------------- leitura da tela do jogo

@st.fragment(run_every=SEGUNDOS_ENTRE_LEITURAS)
def leitura_da_tela(catalogo):
    """Roda sozinha a cada poucos segundos. Se algo mudou no jogo, atualiza a página toda."""
    if not st.session_state.get("lendo"):
        return
    try:
        leitura = carregar_leitor().ler(capturar_tela())
    except Exception as erro:  # ex.: tela bloqueada
        st.caption(f"⚠️ Não consegui capturar a tela: {erro}")
        return
    if not (leitura.nivel or leitura.ouro is not None or any(leitura.loja) or leitura.tracos):
        st.caption("⏸️ Não achei o TFT na tela (o jogo precisa estar em tela cheia ou sem bordas).")
        return

    compras = st.session_state.acompanhamento.detectar_compras(leitura)
    acompanhamento.aplicar_compras(st.session_state.unidades, st.session_state.copias, compras)
    if compras:
        nomes = [compra.campeao.nome for compra in compras]
        st.session_state.compras_recentes = (nomes + st.session_state.compras_recentes)[:6]

    anterior = st.session_state.leitura
    mudou = bool(compras) or anterior is None or (
        (leitura.nivel, leitura.xp, leitura.estagio, leitura.ouro, leitura.loja, leitura.itens, leitura.tracos,
         leitura.tracos_escondidos, leitura.bigorna)
        != (anterior.nivel, anterior.xp, anterior.estagio, anterior.ouro, anterior.loja, anterior.itens,
            anterior.tracos, anterior.tracos_escondidos, anterior.bigorna)
    )
    st.session_state.leitura = leitura
    estado_compartilhado.renovar()
    if mudou:
        componentes, emblemas = acompanhamento.componentes_e_emblemas(leitura.itens, catalogo)
        st.session_state.componentes = Counter(componentes)
        st.session_state.emblemas_lidos = emblemas
        if leitura.nivel and leitura.nivel != st.session_state.nivel:
            st.session_state.nivel_lido = leitura.nivel
        st.rerun(scope="app")
    st.caption(f"🟢 Lendo a tela a cada {SEGUNDOS_ENTRE_LEITURAS} s")


def resumo_da_leitura(catalogo):
    leitura = st.session_state.leitura
    if not (st.session_state.get("lendo") and leitura):
        return
    partes = []
    if leitura.estagio:
        partes.append(f"Estágio **{leitura.estagio[0]}-{leitura.estagio[1]}**")
    if leitura.nivel:
        partes.append(f"Nível **{leitura.nivel}**")
    if leitura.ouro is not None:
        partes.append(f"**{leitura.ouro}** de ouro")
    if partes:
        st.markdown(" · ".join(partes))
    if st.session_state.compras_recentes:
        st.caption("🛍️ Compras detectadas: " + ", ".join(st.session_state.compras_recentes))
    if leitura.tracos:
        no_jogo = ", ".join(f"{catalogo.tracos[t].nome} {q}" for t, q in leitura.tracos.items())
        st.caption(f"Traços no seu tabuleiro (lidos do jogo): {no_jogo}")


# ---------------------------------------------------------------- coluna da esquerda: seu jogo

def coluna_seu_jogo(catalogo):
    st.subheader("🎮 Seu jogo")
    st.toggle(
        "📷 Ler a tela do jogo", key="lendo",
        help="Lê nível, ouro, loja, componentes e emblemas sozinho. Os campeões entram quando você compra "
             "na loja; venda e carrossel você corrige clicando nos retratos.",
    )
    st.toggle(
        "🖥️ Overlay no jogo", key="overlay", on_change=ligar_ou_desligar_overlay,
        help="Mostra a primeira comp da lista e marca na loja o que comprar, por cima do jogo. "
             "O TFT precisa estar em 'Tela cheia sem bordas'. Não mexe no jogo: é uma janela por cima.",
    )
    leitura_da_tela(catalogo)
    resumo_da_leitura(catalogo)

    a, b, c = st.columns([1, 2, 1], vertical_alignment="bottom")
    nivel = a.number_input("Nível", 1, 10, key="nivel")
    b.segmented_control("Clique nos retratos para", [ADICIONAR, REMOVER], default=ADICIONAR, key="modo")
    c.button("Limpar", on_click=limpar_tudo, use_container_width=True)

    st.caption("Cada clique soma uma estrela (até 3★). Use ➖ Remover para tirar.")
    unidades = st.session_state.unidades
    for custo in range(1, 6):
        do_custo = sorted((x for x in catalogo.campeoes.values() if x.custo == custo), key=lambda x: x.nome)
        st.markdown(f'<div class="custo-titulo">{"🪙" * custo}  custo {custo}</div>', unsafe_allow_html=True)
        with st.container(horizontal=True, gap="small"):
            for campeao in do_custo:
                estrelas = unidades.get(campeao.id, 0)
                st.button(
                    campeao.nome,
                    key=f"campeao_{campeao.id}_{'tem' if estrelas else 'nao'}_e{estrelas}",
                    help=campeao.nome,
                    on_click=clicar_campeao, args=(campeao.id,),
                )

    st.markdown("**Componentes**")
    componentes = st.session_state.componentes
    with st.container(horizontal=True, gap="small"):
        for componente in catalogo.componentes():
            quantidade = componentes[componente.id]
            st.button(
                str(quantidade) if quantidade else BRANCO,
                key=f"componente_{componente.id}_{'tem' if quantidade else 'nao'}",
                help=componente.nome,
                on_click=clicar_componente, args=(componente.id,),
            )

    todos = sorted(catalogo.campeoes.values(), key=lambda x: (x.custo, x.nome))
    emblemas_disponiveis = sorted(
        (i for i in catalogo.itens.values() if i.tipo == "Emblema" and i.traco_id), key=lambda i: i.nome
    )
    emblemas = st.multiselect(
        "Emblemas que você tem", emblemas_disponiveis, format_func=lambda i: i.nome, placeholder="Nenhum"
    )
    fixos = st.multiselect(
        "Quero jogar com (obrigatórios)", todos, format_func=lambda x: f"{x.nome} ({x.custo})", placeholder="Nenhum"
    )

    situacao = montador.Situacao(
        nivel=nivel,
        unidades=dict(unidades),
        emblemas=[e.traco_id for e in emblemas] + st.session_state.emblemas_lidos,
        fixos=[x.id for x in fixos],
    )
    painel_de_dados()
    return situacao, Counter({k: v for k, v in componentes.items() if v})


def painel_de_dados():
    with st.expander("⚙️ Dados e chave da Riot"):
        if st.button("🔄 Atualizar dados do jogo (Community Dragon)"):
            with st.status("Baixando...", expanded=True) as status:
                atualizar.atualizar_dados_de_jogo(progresso=status.write)
            st.cache_resource.clear()
            st.rerun()

        st.markdown(
            "**Chave da Riot** (para as comps meta): entre em **developer.riotgames.com**, faça login e copie a "
            "*Development API Key* (começa com `RGAPI-`). Ela vence a cada 24h."
        )
        nova = st.text_input("Chave da Riot", type="password", placeholder="RGAPI-...")
        if st.button("Salvar chave") and nova.strip():
            riot.salvar_chave(nova)
            st.success("Chave salva no arquivo .env.")
        if riot.ler_chave() and st.button("Baixar partidas do alto elo do BR (15 a 20 minutos)"):
            with st.status("Baixando partidas...", expanded=True) as status:
                try:
                    atualizar.atualizar_meta(progresso=status.write)
                    status.update(label="Partidas atualizadas!", state="complete")
                except riot.ErroRiot as erro:
                    status.update(label=str(erro), state="error")
        st.caption(f"{total_de_partidas()} partidas no banco.")


# ---------------------------------------------------------------- coluna da direita: comps

def coluna_comps(situacao, catalogo, componentes):
    chave = (situacao.nivel, tuple(sorted(situacao.unidades.items())), tuple(situacao.emblemas), tuple(situacao.fixos))
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    fonte = a.pills("Mostrar", FONTES, default="Todas", key="fonte") or "Todas"
    tamanho = b.number_input("Tamanho do time", 1, 12, max(situacao.nivel, len(situacao.fixos), 1))

    comps = []
    da_meta, resumo = comps_da_meta(catalogo, chave, total_de_partidas())
    # as mais perto do que você tem primeiro; empate decide pela colocação média ajustada
    da_meta = sorted(da_meta, key=lambda c: (-c.porcentagem_que_tem, c.estatisticas["media_ajustada"]))
    if fonte in ("Todas", "Para você"):
        with st.spinner("Montando comps..."):
            comps += comps_do_algoritmo(catalogo, chave, tamanho)
    if fonte in ("Todas", "Meta"):
        comps += da_meta[:5 if fonte == "Todas" else 15]
        if fonte == "Meta":
            st.caption(f"{resumo['partidas']} partidas de Challenger/Grão-Mestre do BR · "
                       "ordem: mais perto do que você tem, depois melhor colocação média")
    minhas, desconhecidos = manuais.avaliar_todas(situacao, catalogo)
    if fonte in ("Todas", "Minhas"):
        comps += minhas
        if desconhecidos:
            st.warning("Campeões não encontrados no set atual: " + ", ".join(desconhecidos))

    # dá para escolher qualquer comp da lista, qualquer comp meta e qualquer comp sua
    candidatas = {}
    for comp in comps + da_meta + minhas:
        candidatas.setdefault(chave_da_comp(comp), comp)
    escolhida = st.session_state.get("alvo_escolhido")
    if escolhida not in candidatas:
        if escolhida:
            st.warning("A comp que você escolheu sumiu da lista (o algoritmo remonta as comps quando seu jogo muda). "
                       "Voltei para a automática.")
        st.session_state.alvo_escolhido = escolhida = None
    st.selectbox(
        "🎯 Comp alvo (é a que o overlay mostra e a que a loja marca)", [None, *candidatas], key="alvo_escolhido",
        format_func=lambda chave: "Automática (a que mais combina com seu tabuleiro)" if chave is None
        else rotulo_da_comp(candidatas[chave]),
    )

    leitura = st.session_state.leitura if st.session_state.get("lendo") else None
    tracos_lidos = leitura.tracos if leitura else {}
    if escolhida:
        alvo = candidatas[escolhida]
    else:  # automática: a que usa os traços do seu tabuleiro; sem leitura, a 1ª da lista
        alvo = montador.mais_parecida_com_tabuleiro(candidatas.values(), tracos_lidos) or (comps[0] if comps else None)
    if alvo:  # o alvo vai para o topo da lista
        comps = [alvo] + [c for c in comps if chave_da_comp(c) != chave_da_comp(alvo)]

    # quem da comp alvo provavelmente já está no seu tabuleiro (pelos traços lidos): aparece colorido no overlay
    provaveis_da_comp = montador.provaveis_no_tabuleiro(alvo.campeoes, tracos_lidos, catalogo) if alvo else []
    # e quem mais está em campo, fora da comp (pelos traços que sobram); só com a leitura ligada
    fora = montador.ForaDaComp()
    if leitura and alvo:
        fora = montador.fora_da_comp(provaveis_da_comp, tracos_lidos, catalogo, leitura.nivel or situacao.nivel,
                                     leitura.tracos_escondidos)
    # um campeão da comp com traço escondido no "2+" só aparece aqui: conta como provável
    da_comp = {c.id for c in alvo.campeoes} if alvo else set()
    provaveis = {c.id for c in provaveis_da_comp} | {c.id for c in fora.certos if c.id in da_comp}
    fora.certos = [c for c in fora.certos if c.id not in da_comp]
    # com o modelo treinado: cada um de fora da comp FICA (vale no time final) ou é rotação
    modelo = modelo_atual(catalogo) if fora.certos else None
    trocas = aprendizado.avaliar_trocas(alvo, fora.certos, provaveis | set(situacao.unidades), modelo) \
        if modelo else []

    dicas_agora = []
    if leitura and alvo:
        plano = plano_do_alvo(alvo, da_meta)
        feitos = bool(plano and plano.tres_estrelas) and all(
            situacao.unidades.get(c.id) == 3 for c in plano.tres_estrelas
        )
        dicas_agora = modulo_dicas.dicas(leitura, plano, catalogo, faltando=alvo.faltam, tres_estrelas_feitos=feitos)
        if dicas_agora:
            st.html(html_das_dicas(dicas_agora))
    frases_dos_itens = []
    if alvo and componentes:
        frases_dos_itens = modulo_itens.frases_do_plano(modulo_itens.plano_de_itens(alvo, componentes, catalogo))
        if frases_dos_itens:
            st.html(html_dos_itens_agora(frases_dos_itens, alvo.nome))
    bigorna = None  # com uma bigorna aberta: qual opção pegar e onde ela está na tela
    if leitura and leitura.bigorna and alvo:
        escolha = modulo_itens.melhor_opcao([item for item, _ in leitura.bigorna], alvo, componentes, catalogo)
        if escolha:
            caixa = next(caixa for item, caixa in leitura.bigorna if item is escolha.item)
            bigorna = {"item": escolha.item.nome, "motivo": escolha.motivo, "caixa": caixa}
            st.html(html_da_bigorna(escolha))
    selos = []
    if leitura and any(leitura.loja):
        # a loja marca só os campeões da comp alvo (misturar várias comps mandava comprar campeão de outro time)
        selos = estado_compartilhado.selos_da_loja(leitura.loja, [alvo] if alvo else [], situacao, provaveis)
        st.html(html_da_loja(leitura.loja, selos))
    estado_compartilhado.salvar(
        estado_compartilhado.montar(alvo, situacao, selos, catalogo, componentes, dicas_agora, frases_dos_itens,
                                    provaveis, bigorna, fora, trocas)
    )

    if not comps:
        st.info("Nada para mostrar aqui ainda.")
    modelo = modelo_atual(catalogo)
    for posicao, comp in enumerate(comps):
        previsao = modelo.prever_comp(comp) if modelo else None
        st.html(html_da_comp(comp, situacao, catalogo, componentes, previsao))
        _, em_comum = montador.combina_com_tabuleiro(comp, tracos_lidos)
        if em_comum:
            st.caption("🧩 Usa traços do seu tabuleiro: " + ", ".join(em_comum))
        chave_comp = chave_da_comp(comp)
        if comp is alvo:
            st.caption("🎯 Esta é a sua comp alvo" + ("." if escolhida else " (escolhida automaticamente)."))
        if chave_comp != escolhida:
            st.button("🎯 Jogar esta", key=f"jogar_{posicao}", on_click=escolher_alvo, args=(chave_comp,))


def chave_da_comp(comp):
    """Identifica a comp entre uma atualização e outra da página (os objetos são recriados a cada vez)."""
    return f"{comp.origem}|{comp.nome}|{','.join(sorted(c.id for c in comp.campeoes))}"


def rotulo_da_comp(comp):
    return f"{ROTULO_ORIGEM.get(comp.origem, comp.origem)} · {comp.nome} (você tem {len(comp.tem)}/{len(comp.campeoes)})"


def escolher_alvo(chave):
    st.session_state.alvo_escolhido = chave


MINIMO_EM_COMUM = 4  # campeões em comum para uma comp do algoritmo usar o plano de uma comp meta


def plano_do_alvo(alvo, comps_meta):
    """Plano de jogo da comp alvo: o dela (comp meta) ou o da comp meta mais parecida."""
    if alvo.estatisticas.get("plano"):
        return alvo.estatisticas["plano"]
    ids = {c.id for c in alvo.campeoes}
    parecidas = [(len(ids & {c.id for c in m.campeoes}), m) for m in comps_meta]
    em_comum, mais_parecida = max(parecidas, key=lambda x: x[0], default=(0, None))
    return mais_parecida.estatisticas["plano"] if em_comum >= MINIMO_EM_COMUM else None


# ---------------------------------------------------------------- abas de ferramentas

def aba_itens(catalogo, componentes):
    possiveis = modulo_itens.itens_que_pode_montar(componentes, catalogo)
    if possiveis:
        st.markdown("**Com seus componentes, dá para montar:**")
        for item in possiveis:
            receita = " + ".join(catalogo.itens[c].nome for c in item.componentes)
            st.markdown(f"- **{item.nome}** ({receita})")
    else:
        st.info("Clique nos componentes que você tem, na coluna da esquerda.")

    st.markdown("**Todas as receitas**")
    nome_de = lambda id_item: catalogo.itens[id_item].nome if id_item in catalogo.itens else ""
    st.dataframe(
        pd.DataFrame(
            [{"Item": i.nome, "Tipo": i.tipo, "Componente 1": nome_de(i.componentes[0]), "Componente 2": nome_de(i.componentes[1])}
             for i in sorted(catalogo.receitas(), key=lambda i: (i.tipo, i.nome))]
        ),
        hide_index=True, width="stretch",
    )


def aba_loja(situacao, catalogo):
    st.markdown(f"**Chance de ver cada campeão numa loja no nível {situacao.nivel}**")
    linhas = []
    for campeao in sorted(catalogo.campeoes.values(), key=lambda c: (c.custo, c.nome)):
        copias = montador.copias_que_voce_tem(campeao, situacao)
        chance = chance_na_loja(campeao, situacao.nivel, catalogo, copias_suas=copias)
        linhas.append({
            "Campeão": campeao.nome, "Custo": campeao.custo, "Você tem (cópias)": copias,
            "Chance por loja (%)": round(chance.chance_por_loja * 100, 1),
            "Rolls esperados": None if chance.chance_por_loja == 0 else round(chance.rolls_esperados, 1),
        })
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")

    st.markdown("**Chance de cada custo por nível (%)**")
    tabela = pd.DataFrame(catalogo.chances_loja).T.sort_index().fillna(0) * 100
    tabela.columns = [f"Custo {c}" for c in tabela.columns]
    tabela.index.name = "Nível"
    st.dataframe(tabela.round(0), width="stretch")


def aba_cadastro(catalogo):
    nome = st.text_input("Nome da comp")
    todos = sorted(catalogo.campeoes.values(), key=lambda c: (c.custo, c.nome))
    escolhidos = st.multiselect(
        "Campeões", todos, format_func=lambda c: f"{c.nome} ({c.custo})", key="nova_comp", placeholder="Escolha os campeões"
    )
    notas = st.text_area("Notas (opcional)")
    if st.button("Salvar comp") and nome and escolhidos:
        cadastro = manuais.ler()
        cadastro.append({"nome": nome, "campeoes": [c.nome for c in escolhidos], "notas": notas})
        manuais.salvar(cadastro)
        st.success("Comp salva em minhas_comps.json.")

    cadastradas = manuais.ler()
    if cadastradas:
        st.markdown("**Cadastradas**")
        for posicao, cadastro in enumerate(cadastradas):
            a, b = st.columns([5, 1])
            a.markdown(f"**{cadastro.get('nome')}** — {', '.join(cadastro.get('campeoes', []))}")
            if b.button("Apagar", key=f"apagar_{posicao}"):
                manuais.salvar([c for i, c in enumerate(cadastradas) if i != posicao])
                st.rerun()


def aba_taticas(catalogo):
    tabelas = tabelas_de_taticas(catalogo, total_de_partidas())
    if not tabelas:
        st.info("Baixe partidas do alto elo (⚙️ Dados e chave da Riot) para ver as táticas.")
        return
    st.caption(f"Tabuleiro final de {tabelas['partidas']} partidas ranqueadas de Challenger/Grão-Mestre do BR. "
               "Colocação ajustada: com poucos jogos, a média é puxada para 4,5.")
    a, b = st.columns([2, 3])
    with a:
        st.markdown("**Nível final x colocação**")
        st.dataframe(tabelas["por_nivel"], hide_index=True, width="stretch")
    with b:
        st.markdown("**Campeões que mais ajudam a colocar bem**")
        st.dataframe(tabelas["campeoes"], hide_index=True, width="stretch", height=260)
    st.markdown("**Traços mais fortes (por nível ativado)**")
    st.dataframe(tabelas["tracos"], hide_index=True, width="stretch", height=260)

    st.markdown("**Melhores builds de 3 itens**")
    carries = sorted(catalogo.campeoes.values(), key=lambda c: -c.taxa_de_itens)
    campeao = st.selectbox(
        "Campeão", carries, format_func=lambda c: f"{c.nome} (segura 3 itens em {c.taxa_de_itens:.0%} dos jogos)"
    )
    builds = taticas.builds_do_campeao(catalogo, campeao.id)
    if builds:
        st.dataframe(pd.DataFrame([
            {"Itens": " + ".join(catalogo.itens[i].nome for i in b.itens), "Jogos": b.desempenho.jogos,
             "Colocação média": round(b.desempenho.media, 2), "Top 4": f"{b.desempenho.top4:.0%}"}
            for b in builds
        ]), hide_index=True, width="stretch")
    else:
        st.caption("Poucos jogos com esse campeão segurando 3 itens.")


def aba_aprendizado(catalogo):
    """Etapa 1: suas partidas x alto elo. Etapa 2: o modelo que aprende com o alto elo."""
    alto_elo = taticas.ler_tabuleiros(catalogo)
    st.markdown("**1. Suas partidas**")
    conexao = banco.conectar()
    a, b = st.columns([3, 2], vertical_alignment="bottom")
    riot_id = a.text_input("Seu Riot ID", value=banco.metadado(conexao, "riot_id", ""), placeholder="nome#tag")
    if b.button("⬇️ Baixar minhas partidas (últimas 30)") and riot_id.strip():
        with st.status("Baixando suas partidas...", expanded=True) as status:
            try:
                novas = riot.coletar_minhas_partidas(conexao, riot.ler_chave() or "", riot_id, progresso=status.write)
                status.update(label=f"Pronto: {novas} partidas novas.", state="complete")
            except riot.ErroRiot as erro:
                status.update(label=str(erro), state="error")
    conexao.close()

    meus = taticas.meus_tabuleiros(catalogo)
    if meus:
        geral = meu_desempenho.resumo(meus, alto_elo)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Colocação média", f"{geral.colocacao_media:.2f}", help=f"{geral.jogos} partidas ranqueadas")
        c2.metric("Top 4", f"{geral.top4:.0%}")
        c3.metric("Vitórias", f"{geral.vitorias:.0%}")
        c4.metric("Nível final", f"{geral.nivel_medio:.1f}", delta_color="off",
                  delta=f"{geral.nivel_medio - geral.nivel_medio_alto_elo:+.1f} que o alto elo")
        st.dataframe(pd.DataFrame([
            {"Comp": l.nome, "Jogos": l.jogos, "Sua colocação": round(l.sua_colocacao, 2),
             "Seu top 4": f"{l.seu_top4:.0%}", "Alto elo": None if l.alto_elo_colocacao is None
             else round(l.alto_elo_colocacao, 2), "Jogos do alto elo": l.alto_elo_jogos,
             "Seu nível": round(l.seu_nivel, 1),
             "Nível do alto elo": None if l.alto_elo_nivel is None else round(l.alto_elo_nivel, 1)}
            for l in meu_desempenho.por_comp(meus, alto_elo, catalogo)
        ]), hide_index=True, width="stretch")
        st.caption("Comp = carry (quem tem mais itens) + 2 traços principais, como nas comps meta. "
                   "Alto elo: colocação média ajustada de quem terminou com a mesma comp.")
    else:
        st.caption("Coloque seu Riot ID e baixe suas partidas para comparar com o alto elo.")

    st.markdown("**2. Modelo do alto elo**")
    st.caption("O modelo olha o tabuleiro final (campeões, estrelas, traços, nível e itens) e prevê a colocação. "
               "É o tabuleiro FINAL: quem cai cedo tem tabuleiro fraco porque caiu. Então ele diz quanto vale "
               "uma comp montada por completo, não a sua chance no meio da partida.")
    if st.button("🤖 Treinar modelo (uns 15 segundos)"):
        with st.spinner("Treinando..."):
            try:
                aprendizado.salvar(aprendizado.treinar(alto_elo, catalogo, progresso=lambda _texto: None))
            except ValueError as erro:
                st.error(str(erro))
    modelo = modelo_atual(catalogo)
    if not modelo:
        st.info("Ainda não há modelo treinado para este set.")
        return
    a = modelo.avaliacao
    st.markdown(f"Teste em **{a.partidas_de_teste} partidas** que o modelo não viu no treino "
                f"(treinado com {a.partidas_de_treino}):")
    st.dataframe(pd.DataFrame([
        {"Medida": "Erro médio da colocação", "Modelo": f"{a.erro_do_modelo:.2f} posição",
         "Sem modelo": f"{a.erro_sem_modelo:.2f} (chutando 4,5)"},
        {"Medida": "Acerta se ficou no top 4", "Modelo": f"{a.acerto_top4_modelo:.0%}", "Sem modelo": "50% (chute)"},
        {"Medida": "Ordem dos 8 jogadores da partida (0 a 1)", "Modelo": f"{a.ordem_do_modelo:.2f}",
         "Sem modelo": f"{a.ordem_da_regra:.2f} (nota feita à mão do app)"},
    ]), hide_index=True, width="stretch")
    if meus:
        previstas, _ = modelo.prever([aprendizado.vetor_do_tabuleiro(t, modelo.colunas) for t in meus])
        real = sum(t.colocacao for t in meus) / len(meus)
        st.markdown(f"**Seus tabuleiros finais, pelo modelo:** valiam em média **{previstas.mean():.2f}**; "
                    f"você terminou em **{real:.2f}** (o modelo aprendeu com lobbies de alto elo; nos seus, "
                    "os adversários costumam ser mais fracos, então parte da diferença vem daí). "
                    + ("Você coloca melhor do que o tabuleiro sugere (bom posicionamento/economia)."
                       if real < previstas.mean() - 0.3 else
                       "Você coloca pior do que o tabuleiro sugere: vale olhar posicionamento e o momento de "
                       "montar o time." if real > previstas.mean() + 0.3 else
                       "Você coloca mais ou menos o que o tabuleiro vale."))


TABELAS_DO_BANCO = ["campeoes", "tracos", "traco_niveis", "campeao_traco", "itens", "augments",
                    "partidas", "participacoes", "metadados"]


def aba_banco():
    a, b = st.columns(2)
    tabela = a.selectbox("Tabela", TABELAS_DO_BANCO)
    busca = b.text_input("Filtrar (qualquer coluna)")
    conexao = banco.conectar()
    limite = " LIMIT 2000" if tabela == "participacoes" else ""
    dados = pd.read_sql(f"SELECT * FROM {tabela}{limite}", conexao)
    conexao.close()
    if busca:
        dados = dados[dados.astype(str).apply(lambda col: col.str.contains(busca, case=False)).any(axis=1)]
    st.caption(f"{len(dados)} linhas" + (" (as primeiras 2000)" if limite else ""))
    st.dataframe(dados, hide_index=True, width="stretch")


# ---------------------------------------------------------------- página

st.html(estilo.CSS_GERAL)

if banco_vazio():
    st.warning("O banco ainda está vazio.")
    if st.button("Baixar dados do jogo"):
        with st.status("Baixando...", expanded=True) as status:
            atualizar.atualizar_dados_de_jogo(progresso=status.write)
        st.cache_resource.clear()
        st.rerun()
    st.stop()

catalogo = carregar_catalogo()
st.html(estilo.css_dos_botoes(catalogo))
iniciar_estado()

esquerda, direita = st.columns([2, 3], gap="large")
with esquerda:
    situacao, componentes = coluna_seu_jogo(catalogo)
with direita:
    st.subheader("🧩 Comps")
    coluna_comps(situacao, catalogo, componentes)
    st.divider()
    abas = st.tabs(["🧠 Táticas", "🤖 Aprendizado", "🗡️ Itens", "🎲 Loja", "📌 Cadastrar minhas comps",
                    "📚 Banco de dados"])
    with abas[0]:
        aba_taticas(catalogo)
    with abas[1]:
        aba_aprendizado(catalogo)
    with abas[2]:
        aba_itens(catalogo, componentes)
    with abas[3]:
        aba_loja(situacao, catalogo)
    with abas[4]:
        aba_cadastro(catalogo)
    with abas[5]:
        aba_banco()
