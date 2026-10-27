"""Teste do painel de dano: um print real do 4-3 (só a coluna dos retratos, em testes/imagens).

Roda com:  python testes/test_painel_de_dano.py
Precisa do banco e dos ícones baixados (python atualizar.py).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

PASTA_DO_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PASTA_DO_APP))

from logica import montador  # noqa: E402
from logica.catalogo import carregar  # noqa: E402
from visao.acompanhamento import PainelDeDano  # noqa: E402
from visao.leitor import Leitor  # noqa: E402

RECORTE = PASTA_DO_APP / "testes" / "imagens" / "painel-de-dano-4-3.png"
ONDE_FICA_O_RECORTE = (2320, 420)  # canto do recorte na tela de 2560x1440
NO_PAINEL = [("Ahri", 1), ("Yorick", 3), ("Fiddlesticks", 2), ("Sejuani", 2), ("Krugue", 1), ("Vi", 1), ("Rakan", 2)]
# o que o painel de traços mostrava nesse print (mais 3 traços escondidos no "3+": Solar, Fera do Rift e Vanguarda)
TRACOS = {"Colosso": 4, "Enfeitiçador": 2, "Flora Fatalis": 1, "Florescer": 2, "Defendente": 1, "Feérico": 1,
          "Invocador": 1, "Lutador": 1, "Primordial": 1}

catalogo = carregar()
leitor = Leitor(catalogo)
por_nome = {c.nome: c for c in catalogo.campeoes.values()}
tracos_lidos = {t.id: TRACOS[t.nome] for t in catalogo.tracos.values() if t.nome in TRACOS}


def tela_com_o_recorte():
    tela = Image.new("RGB", (2560, 1440), "black")
    tela.paste(Image.open(RECORTE).convert("RGB"), ONDE_FICA_O_RECORTE)
    return tela


def test_le_os_campeoes_e_as_estrelas():
    _, lidos = leitor.ler_painel_de_dano(tela_com_o_recorte())
    assert [(c.nome, estrelas) for c, estrelas in lidos] == NO_PAINEL


def test_painel_fechado_nao_inventa_campeao():
    _, lidos = leitor.ler_painel_de_dano(Image.new("RGB", (2560, 1440), (40, 60, 50)))
    assert lidos == []


def test_painel_resolve_o_tabuleiro():
    comp = SimpleNamespace(campeoes=[por_nome[n] for n in ("Sett", "Yorick", "Fiddlesticks", "Ahri", "Zyra",
                                                           "Lillia", "Sejuani")])
    do_painel = [por_nome[nome] for nome, _ in NO_PAINEL]
    provaveis, fora = montador.quem_esta_em_campo(comp, tracos_lidos, catalogo, 7, 3, do_painel)
    assert {c.nome for c in provaveis} == {"Ahri", "Yorick", "Fiddlesticks", "Sejuani"}
    assert {c.nome for c in fora.certos} == {"Krugue", "Vi", "Rakan"}
    assert fora.vagas_em_duvida == 0 and not fora.sem_combinacao


def test_vendido_sai_do_tabuleiro():
    # Rakan vendido depois do combate: o Feérico some do painel de traços e o Colosso cai para 3
    sem_rakan = {t: n for t, n in tracos_lidos.items() if catalogo.tracos[t].nome != "Feérico"}
    sem_rakan[next(t for t in sem_rakan if catalogo.tracos[t].nome == "Colosso")] = 3
    comp = SimpleNamespace(campeoes=[por_nome["Ahri"]])
    do_painel = [por_nome[nome] for nome, _ in NO_PAINEL]
    provaveis, fora = montador.quem_esta_em_campo(comp, sem_rakan, catalogo, 7, 3, do_painel)
    em_campo = {c.nome for c in provaveis} | {c.nome for c in fora.certos}
    assert "Rakan" not in em_campo


def test_leitura_pela_metade_no_combate():
    # partida de 27/10/2026, 3-1 -> 3-2: no combate o painel reordena e a leitura sai pela metade
    yi, kog, vi = por_nome["Master Yi"], por_nome["Kog'Maw"], por_nome["Vi"]
    painel = PainelDeDano()
    painel.atualizar([(yi, 1), (kog, 1), (kog, 1), (vi, 1)], (3, 1))
    painel.atualizar([(yi, 1)], (3, 1))                       # pedaço: ignorado
    assert len(painel.campeoes) == 4
    painel.atualizar([(kog, 2)], (3, 2))                      # pedaço com novidade: Kog'Maw subiu para 2★
    assert sorted((c.nome, e) for c, e in painel.campeoes) == [("Kog'Maw", 2), ("Master Yi", 1), ("Vi", 1)]
    painel.atualizar([], (1, 1))                              # estágio 1 de novo: partida nova
    assert painel.campeoes == []


if __name__ == "__main__":
    for nome, teste in list(globals().items()):
        if nome.startswith("test_"):
            teste()
            print(f"ok  {nome}")
