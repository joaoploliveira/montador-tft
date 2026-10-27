"""Liga o app ao overlay: o app escreve o que mostrar e o overlay só lê.

Fica em dados/overlay.json, só com dados simples (nomes, custos, textos), para o
overlay não precisar carregar o catálogo nem o banco.
"""

import json
import os
import time
from pathlib import Path

from logica import itens as modulo_itens

ARQUIVO = Path(__file__).resolve().parent.parent / "dados" / "overlay.json"
SELO_COMPRE, SELO_SOBE = "COMPRE", "SOBE ★"
LOJA_VALE_POR = 15  # segundos: sem leitura nova nesse tempo, a marcação da loja some do overlay


def selos_da_loja(loja, comps_alvo, situacao, provaveis=()):
    """Um selo por carta, só para campeões das comps alvo: SOBE ★ se você já tem, COMPRE se não tem.
    Campeão que não está nas comps fica sem selo, mesmo que você tenha (não vale gastar ouro nele).
    `provaveis`: ids que provavelmente estão no tabuleiro (deduzidos dos traços) contam como "já tem"."""
    nas_comps = {c.id for comp in comps_alvo for c in comp.campeoes}
    selos = []
    for campeao in loja:
        if campeao is None or campeao.id not in nas_comps:
            selos.append("")
        elif campeao.id in situacao.unidades or campeao.id in provaveis:
            selos.append(SELO_SOBE)
        else:
            selos.append(SELO_COMPRE)
    return selos


DICAS_NO_OVERLAY = 2


def montar(comp, situacao, selos, catalogo, componentes, dicas=(), frases_dos_itens=(), provaveis=(),
           bigorna=None, fora=None, estrelas_lidas=None, fora_do_jogo=False):
    """O que o overlay mostra: a comp alvo (a escolhida no app, ou a primeira da lista), os selos da loja,
    as dicas e o plano de itens (o que montar e em quem; ver logica/itens.py:frases_do_plano).
    Campeões e itens levam a `chave` do ícone, para o overlay desenhar as imagens.
    `provaveis`: ids que provavelmente estão no tabuleiro (deduzidos dos traços lidos).
    `bigorna`: com uma bigorna aberta, {"item", "motivo", "caixa"} da opção que vale pegar.
    `fora`: quem mais está em campo, fora da comp (montador.ForaDaComp).
    `estrelas_lidas`: {id: estrelas} de quem o painel de dano mostrou em campo (confirmado, não deduzido).
    `fora_do_jogo`: a leitura está ligada mas o TFT não está na tela (ex.: no cliente): o overlay some."""
    dados = {"loja": selos, "comp": None, "dicas": [d.texto for d in list(dicas)[:DICAS_NO_OVERLAY]],
             "itens_agora": [_frase_simples(f) for f in frases_dos_itens], "bigorna": bigorna,
             "fora_do_jogo": fora_do_jogo}
    if comp is None:
        return dados
    estrelas_lidas = estrelas_lidas or {}
    carry = next(iter(modulo_itens.carregadores(comp, 1)), None)
    itens = modulo_itens.itens_para_campeao(carry, componentes, catalogo) if carry else []
    dados["comp"] = {
        "nome": comp.nome,
        "origem": comp.origem,
        "tem": len({c.id for c in comp.tem} | {c.id for c in comp.campeoes if c.id in provaveis}),
        "total": len(comp.campeoes),
        "campeoes": [
            {"nome": c.nome, "custo": c.custo, "chave": c.chave,
             "estrelas": estrelas_lidas.get(c.id) or situacao.unidades.get(c.id, 0),
             "provavel": c.id in provaveis, "confirmado": c.id in estrelas_lidas}
            for c in comp.campeoes
        ],
        # traços de verdade primeiro; os de um campeão só (sempre ativos) vão para o fim
        "tracos": [{"texto": t.texto(), "estilo": t.estilo}
                   for t in sorted(comp.tracos, key=lambda t: t.traco.unico) if t.ativo],
        "carry": carry.nome if carry else "",
        "carry_chave": carry.chave if carry else "",
        "itens": [{"nome": s.item.nome, "status": s.status, "chave": s.item.chave} for s in itens],
        "em_campo": _em_campo(fora, estrelas_lidas),
    }
    return dados


PODE_SER_NO_OVERLAY = 6


def _em_campo(fora, estrelas_lidas):
    """Os de fora da comp que estão em campo, e um "?" por vaga que não deu para saber quem é."""
    if not fora:
        return []
    em_campo = [{"nome": c.nome, "custo": c.custo, "chave": c.chave, "estrelas": estrelas_lidas.get(c.id, 0),
                 "fora_da_comp": True, "confirmado": c.id in estrelas_lidas}
                for c in fora.certos]
    if fora.vagas_em_duvida:
        nomes = [c.nome for c in fora.pode_ser]
        em_campo.append({"nome": "?", "custo": 0, "chave": "", "estrelas": 0, "quantos": fora.vagas_em_duvida,
                         "pode_ser": nomes[:PODE_SER_NO_OVERLAY] + (["…"] if len(nomes) > PODE_SER_NO_OVERLAY else [])})
    return em_campo


def _frase_simples(frase):
    """Uma frase do plano de itens só com textos e chaves de ícone."""
    return {
        "tipo": frase.tipo,
        "texto": frase.texto,
        "item": frase.item.nome,
        "item_chave": frase.item.chave,
        "componentes": list(getattr(frase.item, "componentes", ())) if frase.tipo == "montar" else [],
        "campeao": frase.campeao.nome if frase.campeao else "",
        "campeao_chave": frase.campeao.chave if frase.campeao else "",
        "falta": frase.falta.nome if frase.falta else "",
        "falta_chave": frase.falta.chave if frase.falta else "",
    }


def salvar(dados):
    """Grava só se mudou (o app roda várias vezes por minuto)."""
    novo = json.dumps(dados, ensure_ascii=False)
    try:
        if ARQUIVO.read_text(encoding="utf-8") == novo:
            return
    except OSError:
        pass
    temporario = ARQUIVO.with_suffix(".tmp")
    temporario.write_text(novo, encoding="utf-8")
    os.replace(temporario, ARQUIVO)  # troca de uma vez: o overlay nunca lê o arquivo pela metade


def renovar():
    """Chamado a cada leitura da tela: avisa ao overlay que a marcação da loja ainda vale."""
    if ARQUIVO.exists():
        os.utime(ARQUIVO)


def ler():
    """Devolve os dados, ou None se o app ainda não escreveu. A loja e a bigorna somem se a leitura parou."""
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        idade = time.time() - ARQUIVO.stat().st_mtime
    except (OSError, ValueError):
        return None
    if idade > LOJA_VALE_POR:
        dados["loja"], dados["bigorna"] = [], None
    return dados
