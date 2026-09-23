"""
Gestione del database SQLite (asincrono tramite aiosqlite).
Tutte le tabelle usate dal bot vengono create qui al primo avvio.
"""

import aiosqlite
import json
import time
from config import DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await _db.execute("PRAGMA journal_mode=WAL;")
        await _db.commit()
    return _db


async def init_db():
    db = await get_db()
    await db.executescript(
        """
        -- ECONOMIA: globale, per utente (stesso saldo su qualsiasi server)
        CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER PRIMARY KEY,
            cash INTEGER NOT NULL DEFAULT 0,
            bank INTEGER NOT NULL DEFAULT 0,
            last_work INTEGER DEFAULT 0,
            last_fish INTEGER DEFAULT 0,
            last_hunt INTEGER DEFAULT 0
        );

        -- MODERAZIONE: warn
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT,
            timestamp INTEGER NOT NULL
        );

        -- LEVELING (per server)
        CREATE TABLE IF NOT EXISTS levels (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            messages INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        -- INVITI (per server)
        CREATE TABLE IF NOT EXISTS invites (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        -- PUNTI PEX STAFF (per server)
        CREATE TABLE IF NOT EXISTS staff_points (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        -- RUOLI STAFF ABILITATI ALLE QUEST (max 15 per server, gestito in codice)
        CREATE TABLE IF NOT EXISTS staff_roles (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, role_id)
        );

        -- QUEST GIORNALIERE ASSEGNATE
        CREATE TABLE IF NOT EXISTS staff_quests (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            quests_json TEXT NOT NULL,
            progress_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, date)
        );

        -- BLACKLIST GLOBALE
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT
        );

        -- CONFIGURAZIONE PER SERVER
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER,
            welcome_channel INTEGER,
            welcome_message TEXT,
            goodbye_channel INTEGER,
            goodbye_message TEXT,
            antinuke INTEGER NOT NULL DEFAULT 0,
            antiraid INTEGER NOT NULL DEFAULT 0,
            antilink INTEGER NOT NULL DEFAULT 0,
            mute_role INTEGER,
            member_role INTEGER,
            desk_text TEXT,
            trial_questions TEXT
        );

        -- GIVEAWAY
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            end_time INTEGER NOT NULL,
            winners_count INTEGER NOT NULL,
            reroll_interval INTEGER,
            requirements TEXT,
            participants TEXT NOT NULL DEFAULT '[]',
            ended INTEGER NOT NULL DEFAULT 0
        );

        -- TICKET CREATI DAI GIVEAWAY (per tracciare il pulsante "Consegnato")
        CREATE TABLE IF NOT EXISTS giveaway_tickets (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            winner_id INTEGER NOT NULL,
            prize TEXT NOT NULL
        );

        -- MESSAGGI STICKY (uno per canale)
        CREATE TABLE IF NOT EXISTS sticky (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            last_message_id INTEGER
        );

        -- PARTNERSHIP SALVATE
        CREATE TABLE IF NOT EXISTS partnerships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            message TEXT NOT NULL
        );

        -- MATRIMONI
        CREATE TABLE IF NOT EXISTS marriages (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL
        );
        """
    )
    await db.commit()


# ---------- Helper generici ----------

async def get_guild_config(guild_id: int) -> dict:
    db = await get_db()
    cur = await db.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,))
    row = await cur.fetchone()
    cols = [d[0] for d in cur.description]
    if row is None:
        await db.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        return await get_guild_config(guild_id)
    return dict(zip(cols, row))


async def update_guild_config(guild_id: int, **kwargs):
    await get_guild_config(guild_id)  # assicura che la riga esista
    db = await get_db()
    keys = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [guild_id]
    await db.execute(f"UPDATE guild_config SET {keys} WHERE guild_id=?", values)
    await db.commit()


def now() -> int:
    return int(time.time())


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text: str, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
