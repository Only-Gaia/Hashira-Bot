"""
Configurazione principale del bot.
Inserisci qui il tuo token e gli ID necessari prima di avviare il bot.
"""

import os

# Token del bot (meglio metterlo in una variabile d'ambiente su Render/Railway/host)
TOKEN = os.getenv("DISCORD_TOKEN", "INSERISCI_QUI_IL_TUO_TOKEN")

# Prefissi accettati dal bot (oltre agli slash command "/")
PREFIXES = ["."]  # puoi aggiungere altri prefissi qui, es: [".", "Kira "]

# ID dell'unico utente autorizzato a usare i comandi economia "add" / "remove"
ECONOMY_ADMIN_ID = 1520803701692829806

# Nome del database SQLite (verrà creato automaticamente al primo avvio)
DB_PATH = "kira_bot.db"

# Colore standard usato per gli embed del bot
EMBED_COLOR = 0x2F3136

# Durata del timeout automatico per chi manda link (anti-link) in secondi
ANTILINK_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 ore

# Formula XP -> livello per il sistema di leveling (messaggi)
def xp_per_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100
