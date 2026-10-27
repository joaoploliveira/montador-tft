"""Banco SQLite (dados/tft.db) com os dados do set atual e as partidas de alto elo.

- Dados de jogo (campeões, traços, itens, augments): Community Dragon, que extrai
  os arquivos do próprio cliente do TFT da Riot (veja dados/cdragon.py).
- Partidas: API oficial da Riot (veja dados/riot.py).

Os ids de tudo são os nomes internos da Riot (ex.: 'DA_18_LeBlanc', 'DA_18_Solar',
'DA_InfinityEdge'), os mesmos que aparecem nas partidas da API. Exemplos de consulta no README.
"""

import sqlite3
from pathlib import Path

CAMINHO_DB = Path(__file__).parent / "tft.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS metadados (chave TEXT PRIMARY KEY, valor TEXT);

CREATE TABLE IF NOT EXISTS campeoes (
    chave TEXT PRIMARY KEY, nome TEXT, custo INTEGER,
    vida REAL, ataque REAL, armadura REAL, resist_magica REAL, vel_ataque REAL,
    alcance REAL, critico REAL, mana_max REAL, mana_inicial REAL,
    habilidade TEXT, habilidade_desc TEXT, icone TEXT
);
CREATE TABLE IF NOT EXISTS tracos (chave TEXT PRIMARY KEY, nome TEXT, descricao TEXT, icone TEXT);
CREATE TABLE IF NOT EXISTS traco_niveis (
    traco TEXT, minimo INTEGER, maximo INTEGER, estilo INTEGER, efeito TEXT
);
CREATE TABLE IF NOT EXISTS campeao_traco (campeao TEXT, traco TEXT);
CREATE TABLE IF NOT EXISTS itens (
    chave TEXT PRIMARY KEY, nome TEXT, tipo TEXT, componente_1 TEXT, componente_2 TEXT,
    traco TEXT, descricao TEXT, icone TEXT
);
CREATE TABLE IF NOT EXISTS augments (chave TEXT PRIMARY KEY, nome TEXT, descricao TEXT, icone TEXT);

-- Partidas ranqueadas de alto elo, vindas da API oficial da Riot
CREATE TABLE IF NOT EXISTS partidas (
    match_id TEXT PRIMARY KEY, data INTEGER, versao TEXT, set_numero INTEGER, fila INTEGER,
    duracao REAL
);
CREATE TABLE IF NOT EXISTS participacoes (
    match_id TEXT, puuid TEXT, colocacao INTEGER, nivel INTEGER,
    ouro_restante INTEGER, ultima_rodada INTEGER, eliminado_em REAL,
    unidades TEXT, tracos TEXT, augments TEXT,
    PRIMARY KEY (match_id, puuid)
);
"""

TABELAS_DE_JOGO = ["campeoes", "tracos", "traco_niveis", "campeao_traco", "itens", "augments"]

# de onde veio a partida: dos jogadores de alto elo (base das estatísticas) ou do seu histórico.
# Separar importa: os outros 7 jogadores dos seus lobbies não são alto elo.
ORIGEM_ALTO_ELO, ORIGEM_MINHAS = "alto_elo", "minhas"


def conectar(caminho=None):
    conexao = sqlite3.connect(caminho or CAMINHO_DB)
    conexao.row_factory = sqlite3.Row
    conexao.executescript(ESQUEMA)
    _atualizar_esquema(conexao)
    return conexao


def _atualizar_esquema(conexao):
    """Bancos de versões anteriores não têm a coluna `origem`: tudo que já existe é alto elo."""
    colunas = {linha[1] for linha in conexao.execute("PRAGMA table_info(partidas)")}
    if "origem" not in colunas:
        conexao.execute(f"ALTER TABLE partidas ADD COLUMN origem TEXT DEFAULT '{ORIGEM_ALTO_ELO}'")
        conexao.commit()


def metadado(conexao, chave, padrao=None):
    linha = conexao.execute("SELECT valor FROM metadados WHERE chave=?", (chave,)).fetchone()
    return linha[0] if linha else padrao


def salvar_metadado(conexao, chave, valor):
    conexao.execute("INSERT OR REPLACE INTO metadados VALUES (?, ?)", (chave, str(valor)))


def importar_partidas_antigas(conexao, caminho_antigo):
    """Traz as partidas de um banco da versão anterior (datatft.db), para não baixar de novo."""
    if not Path(caminho_antigo).exists():
        return 0
    conexao.execute("ATTACH DATABASE ? AS antigo", (str(caminho_antigo),))
    try:
        antes = conexao.total_changes
        conexao.execute(
            "INSERT OR IGNORE INTO partidas (match_id, data, versao, set_numero, fila) "
            "SELECT match_id, data, versao, set_numero, fila FROM antigo.partidas"
        )
        conexao.execute(
            "INSERT OR IGNORE INTO participacoes (match_id, puuid, colocacao, nivel, unidades, tracos, augments) "
            "SELECT match_id, puuid, colocacao, nivel, unidades, tracos, augments FROM antigo.participacoes"
        )
        conexao.commit()
        return conexao.total_changes - antes
    finally:
        conexao.execute("DETACH DATABASE antigo")
