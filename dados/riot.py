"""Coleta partidas ranqueadas de alto elo (Challenger e Grão-Mestre) pela API oficial da Riot.

Precisa de uma chave da Riot (veja o README). A chave fica no arquivo .env na raiz
do projeto, numa linha assim:  RIOT_API_KEY=RGAPI-xxxxxxxx

Limite da chave gratuita: 100 pedidos a cada 2 minutos. Por isso a coleta espera
um pouco entre os pedidos, e as partidas já salvas no banco não são baixadas de novo.
"""

import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

from dados import banco

ARQUIVO_ENV = Path(__file__).parent.parent / ".env"
PLATAFORMA = "br1"         # servidor do Brasil (ranking, jogadores)
REGIAO = "americas"        # rota regional usada pelas partidas do BR
FILA_RANQUEADA = 1100      # queue_id das partidas ranqueadas de TFT
INTERVALO = 1.25           # segundos entre pedidos (fica abaixo de 100 a cada 2 min)
TIMEOUT = 30


class ErroRiot(Exception):
    pass


def ler_chave():
    """Procura a chave no ambiente (RIOT_API_KEY) e depois no arquivo .env."""
    chave = os.environ.get("RIOT_API_KEY", "").strip()
    if not chave and ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("RIOT_API_KEY="):
                chave = linha.split("=", 1)[1].strip().strip('"')
    return chave or None


def salvar_chave(chave):
    ARQUIVO_ENV.write_text(f"RIOT_API_KEY={chave.strip()}\n", encoding="utf-8")


class ClienteRiot:
    def __init__(self, chave):
        self.sessao = requests.Session()
        self.sessao.headers["X-Riot-Token"] = chave
        self.ultimo_pedido = 0.0

    def _get(self, url, parametros=None):
        for _tentativa in range(5):
            espera = INTERVALO - (time.time() - self.ultimo_pedido)
            if espera > 0:
                time.sleep(espera)
            self.ultimo_pedido = time.time()
            resposta = self.sessao.get(url, params=parametros, timeout=TIMEOUT)

            if resposta.status_code == 429:  # passou do limite: a Riot diz quanto esperar
                time.sleep(int(resposta.headers.get("Retry-After", 10)))
                continue
            if resposta.status_code in (401, 403):
                raise ErroRiot("Chave da Riot inválida ou expirada. Gere outra em developer.riotgames.com.")
            if resposta.status_code == 404:
                return None
            resposta.raise_for_status()
            return resposta.json()
        raise ErroRiot("A Riot recusou os pedidos várias vezes seguidas (limite de uso). Tente mais tarde.")

    def jogadores_alto_elo(self):
        """puuids dos jogadores Challenger e Grão-Mestre do BR, do maior PL para o menor."""
        entradas = []
        for liga in ("challenger", "grandmaster"):
            resposta = self._get(
                f"https://{PLATAFORMA}.api.riotgames.com/tft/league/v1/{liga}",
                {"queue": "RANKED_TFT"},
            )
            entradas += (resposta or {}).get("entries", [])
        entradas.sort(key=lambda entrada: entrada.get("leaguePoints", 0), reverse=True)

        puuids = []
        for entrada in entradas:
            puuid = entrada.get("puuid")
            if not puuid and entrada.get("summonerId"):  # respostas antigas não traziam o puuid
                invocador = self._get(
                    f"https://{PLATAFORMA}.api.riotgames.com/tft/summoner/v1/summoners/{entrada['summonerId']}"
                )
                puuid = (invocador or {}).get("puuid")
            if puuid:
                puuids.append(puuid)
        return puuids

    def puuid_do_riot_id(self, riot_id):
        """'nome#tag' -> puuid (a conta da Riot fica na rota regional, não no servidor do BR)."""
        nome, _, tag = riot_id.strip().partition("#")
        if not nome or not tag:
            raise ErroRiot("Riot ID no formato nome#tag (ex.: jogador#br1).")
        conta = self._get(f"https://{REGIAO}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
                          f"{quote(nome)}/{quote(tag)}")
        if not conta:
            raise ErroRiot(f"A Riot não achou o Riot ID {riot_id}.")
        return conta["puuid"]

    def ids_partidas(self, puuid, quantidade):
        return self._get(
            f"https://{REGIAO}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids",
            {"count": quantidade},
        ) or []

    def partida(self, match_id):
        return self._get(f"https://{REGIAO}.api.riotgames.com/tft/match/v1/matches/{match_id}")


def _salvar_partida(conexao, partida, origem=banco.ORIGEM_ALTO_ELO):
    info = partida["info"]
    match_id = partida["metadata"]["match_id"]
    conexao.execute(
        "INSERT OR REPLACE INTO partidas (match_id, data, versao, set_numero, fila, duracao, origem) "
        "VALUES (?,?,?,?,?,?,?)",
        (match_id, info.get("game_datetime"), info.get("game_version"),
         info.get("tft_set_number"), info.get("queue_id"), info.get("game_length"), origem),
    )
    for jogador in info.get("participants", []):
        unidades = [
            {"id": u.get("character_id"), "estrelas": u.get("tier"), "itens": u.get("itemNames", [])}
            for u in jogador.get("units", [])
        ]
        tracos = [
            {"id": t.get("name"), "unidades": t.get("num_units"), "estilo": t.get("style"), "tier": t.get("tier_current")}
            for t in jogador.get("traits", [])
        ]
        conexao.execute(
            "INSERT OR REPLACE INTO participacoes VALUES (?,?,?,?,?,?,?,?,?,?)",
            (match_id, jogador.get("puuid"), jogador.get("placement"), jogador.get("level"),
             jogador.get("gold_left"), jogador.get("last_round"), jogador.get("time_eliminated"),
             json.dumps(unidades), json.dumps(tracos), json.dumps(jogador.get("augments", []))),
        )
    conexao.commit()


def coletar_partidas(conexao, chave, jogadores=60, partidas_por_jogador=20, progresso=print):
    """Baixa as partidas ranqueadas mais recentes dos melhores jogadores do BR.

    Com os valores padrão são uns 700 a 900 pedidos: 15 a 20 minutos com a chave gratuita.

    `progresso` recebe mensagens de texto (print no terminal, ou a barra do app).
    Devolve quantas partidas novas foram salvas.
    """
    cliente = ClienteRiot(chave)
    progresso("Buscando o ranking Challenger/Grão-Mestre do BR...")
    puuids = cliente.jogadores_alto_elo()[:jogadores]
    if not puuids:
        raise ErroRiot("A Riot não devolveu nenhum jogador de alto elo.")

    ja_salvas = {linha[0] for linha in conexao.execute("SELECT match_id FROM partidas")}
    novas = []
    for numero, puuid in enumerate(puuids, start=1):
        progresso(f"Lendo o histórico do jogador {numero}/{len(puuids)}...")
        for match_id in cliente.ids_partidas(puuid, partidas_por_jogador):
            if match_id not in ja_salvas and match_id not in novas:
                novas.append(match_id)

    for numero, match_id in enumerate(novas, start=1):
        progresso(f"Baixando partida {numero}/{len(novas)}...")
        partida = cliente.partida(match_id)
        if partida:  # salva todas (para não baixar de novo); a análise usa só as ranqueadas
            _salvar_partida(conexao, partida)
    return len(novas)


def coletar_minhas_partidas(conexao, chave, riot_id, quantidade=30, progresso=print):
    """Baixa as suas partidas mais recentes (as que já estão no banco não são baixadas de novo).

    Guarda o Riot ID e o puuid no banco (metadados), para o app saber quais tabuleiros são seus.
    Devolve quantas partidas novas foram salvas.
    """
    cliente = ClienteRiot(chave)
    progresso(f"Procurando {riot_id}...")
    puuid = cliente.puuid_do_riot_id(riot_id)
    banco.salvar_metadado(conexao, "riot_id", riot_id.strip())
    banco.salvar_metadado(conexao, "meu_puuid", puuid)
    conexao.commit()

    ja_salvas = {linha[0] for linha in conexao.execute("SELECT match_id FROM partidas")}
    novas = [m for m in cliente.ids_partidas(puuid, quantidade) if m not in ja_salvas]
    for numero, match_id in enumerate(novas, start=1):
        progresso(f"Baixando sua partida {numero}/{len(novas)}...")
        partida = cliente.partida(match_id)
        if partida:
            _salvar_partida(conexao, partida, origem=banco.ORIGEM_MINHAS)
    return len(novas)
