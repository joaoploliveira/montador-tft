"""Grava a partida rodada a rodada, para entender depois o que aconteceu (logica/linha_do_tempo.py).

A API da Riot só mostra o fim da partida; o que explica uma derrota costuma estar no meio.
Um arquivo por partida em dados/partidas_gravadas/ (fora do git), uma linha JSON por rodada, gravada
na primeira leitura da rodada (no planejamento): estágio, nível, ouro, traços e o painel de dano
(quem lutou na rodada anterior, com as estrelas).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "dados" / "partidas_gravadas"
ESPERA_MAXIMA = 20  # segundos: sem nível ou ouro na leitura, espera uma leitura melhor da mesma rodada


@dataclass
class Gravacao:
    arquivo: Path | None = None
    ultima_rodada: tuple | None = None
    esperando: tuple | None = None       # rodada nova que ainda não foi gravada (o OCR não leu nível ou ouro)
    esperando_desde: float = 0.0

    def registrar(self, leitura, painel, agora=None):
        """Grava a rodada se ela é nova. `painel`: acompanhamento.PainelDeDano. `agora`: segundos (time.time())."""
        estagio = leitura.estagio
        if not estagio or estagio == self.ultima_rodada:
            return
        partida_nova = self.arquivo is None or (estagio[0] == 1 and self.ultima_rodada[0] > 1)
        if not partida_nova and estagio < self.ultima_rodada:  # leitura errada do estágio (voltou no tempo)
            return
        agora = agora or time.time()
        if leitura.nivel is None or leitura.ouro is None:  # o OCR falhou nesta leitura: espera a próxima
            if self.esperando != estagio:
                self.esperando, self.esperando_desde = estagio, agora
            if agora - self.esperando_desde < ESPERA_MAXIMA:
                return
        if partida_nova:
            self.arquivo = PASTA / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(agora))}.jsonl"
        self.ultima_rodada = estagio
        linha = {"hora": round(agora), "estagio": list(estagio), "nivel": leitura.nivel, "ouro": leitura.ouro,
                 "tracos": leitura.tracos, "painel": [[c.id, estrelas] for c, estrelas in painel.campeoes]}
        PASTA.mkdir(parents=True, exist_ok=True)
        with open(self.arquivo, "a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")


def ler_gravacoes():
    """{nome do arquivo: [linhas]} de todas as partidas gravadas, da mais antiga para a mais recente."""
    gravacoes = {}
    for caminho in sorted(PASTA.glob("*.jsonl")):
        linhas = [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip()]
        if linhas:
            gravacoes[caminho.stem] = linhas
    return gravacoes
