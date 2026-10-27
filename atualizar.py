"""Atualiza o banco de dados (dados/tft.db).

    python atualizar.py            dados do set (Community Dragon) e ícones
    python atualizar.py --meta     também baixa partidas de alto elo da Riot (precisa da chave)
    python atualizar.py --treinar  também treina o modelo do alto elo (aba Aprendizado)
"""

import sys
from pathlib import Path

from dados import banco, cdragon, riot
from logica import aprendizado, taticas
from logica import catalogo as modulo_catalogo

BANCO_ANTIGO = Path(__file__).parent / "dados" / "datatft.db"  # versão anterior do app


def atualizar_dados_de_jogo(progresso=print):
    conexao = banco.conectar()
    cdragon.importar(conexao, progresso=progresso)
    trazidas = banco.importar_partidas_antigas(conexao, BANCO_ANTIGO)
    if trazidas:
        progresso(f"{trazidas} registros de partidas trazidos do banco antigo.")
    conexao.close()
    progresso("Pronto: dados do set atualizados.")


def atualizar_meta(progresso=print):
    chave = riot.ler_chave()
    if not chave:
        raise riot.ErroRiot("Sem chave da Riot. Coloque RIOT_API_KEY=... no arquivo .env (veja o README).")
    conexao = banco.conectar()
    novas = riot.coletar_partidas(conexao, chave, progresso=progresso)
    total = conexao.execute("SELECT COUNT(*) FROM partidas").fetchone()[0]
    conexao.close()
    progresso(f"Pronto: {novas} partidas novas ({total} no banco).")


def treinar_modelo(progresso=print):
    catalogo = modulo_catalogo.carregar()
    modelo = aprendizado.treinar(taticas.ler_tabuleiros(catalogo), catalogo, progresso=progresso)
    aprendizado.salvar(modelo)
    a = modelo.avaliacao
    progresso(f"Pronto: erro médio {a.erro_do_modelo:.2f} posição (sem modelo {a.erro_sem_modelo:.2f}); "
              f"top 4 certo em {a.acerto_top4_modelo:.0%}.")


if __name__ == "__main__":
    atualizar_dados_de_jogo()
    if "--meta" in sys.argv:
        atualizar_meta()
    if "--treinar" in sys.argv:
        treinar_modelo()
