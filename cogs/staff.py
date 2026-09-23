import random

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db, get_guild_config, update_guild_config, dumps, loads, now
from config import EMBED_COLOR

MAX_STAFF_ROLES = 15

# Se passano più di questi secondi senza un nuovo messaggio nella chat monitorata,
# lo streak di attività si considera interrotto e riparte dal prossimo messaggio.
CHAT_GAP_THRESHOLD = 120  # 2 minuti

# Tutte le quest tracciabili usano mode="diff" (contatore crescente: confronta il valore
# attuale con quello al momento dell'assegnazione, tramite "baseline") oppure mode="streak"
# (valore assoluto, per l'attività chat continua). Nessuna quest viene più validata "sulla
# fiducia": ogni tipo ha una metrica reale collegata a un comando o dato del bot.
QUEST_POOL = [
    {"key": "collab", "desc": "Fai {n} partnership", "n": (2, 4), "trackable": True, "mode": "diff"},
    {"key": "invites", "desc": "Porta {n} nuovi inviti", "n": (3, 5), "trackable": True, "mode": "diff"},
    {"key": "messages", "desc": "Invia {n} messaggi nel server", "n": (20, 40), "trackable": True, "mode": "diff"},
    {"key": "chat_general", "desc": "Mantieni attiva la chat generale per {n} minuti consecutivi", "n": (15, 30), "trackable": True, "mode": "streak"},
    {"key": "chat_staff", "desc": "Mantieni attiva la chat staff per {n} minuti consecutivi", "n": (15, 30), "trackable": True, "mode": "streak"},
]
POINTS_PER_QUEST = 5


def today_str() -> str:
    import datetime
    return datetime.date.today().isoformat()


async def is_staff(member: discord.Member) -> bool:
    db = await get_db()
    cur = await db.execute("SELECT role_id FROM staff_roles WHERE guild_id=?", (member.guild.id,))
    role_ids = {r[0] for r in await cur.fetchall()}
    return any(r.id in role_ids for r in member.roles) or member.guild_permissions.administrator


async def _current_stat(guild_id: int, user_id: int, key: str) -> int:
    """Legge la statistica reale attuale per una quest tracciabile."""
    db = await get_db()
    if key == "messages":
        cur = await db.execute("SELECT messages FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = await cur.fetchone()
        return row[0] if row else 0
    elif key == "invites":
        cur = await db.execute("SELECT count FROM invites WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = await cur.fetchone()
        return row[0] if row else 0
    elif key == "collab":
        # conta quante partnership l'utente ha creato con /partnershipadd in questo server
        cur = await db.execute(
            "SELECT COUNT(*) FROM partnerships WHERE guild_id=? AND author_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    elif key in ("chat_general", "chat_staff"):
        cur = await db.execute(
            "SELECT streak_start, last_message FROM chat_activity WHERE guild_id=? AND channel_type=?",
            (guild_id, key),
        )
        row = await cur.fetchone()
        if not row:
            return 0
        streak_start, last_message = row
        if now() - last_message > CHAT_GAP_THRESHOLD:
            return 0
        return (last_message - streak_start) // 60
    return 0


class Staff(commands.Cog):
    """Sistema staff: desk, quest giornaliere, trial, punti pex, partnership."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- MONITORAGGIO ATTIVITÀ CHAT (per le quest chat_general/chat_staff) ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        cfg = await get_guild_config(message.guild.id)
        channel_type = None
        if cfg.get("general_chat_channel") == message.channel.id:
            channel_type = "chat_general"
        elif cfg.get("staff_chat_channel") == message.channel.id:
            channel_type = "chat_staff"
        if not channel_type:
            return

        db = await get_db()
        cur = await db.execute(
            "SELECT streak_start, last_message FROM chat_activity WHERE guild_id=? AND channel_type=?",
            (message.guild.id, channel_type),
        )
        row = await cur.fetchone()
        ts = now()

        if row and (ts - row[1]) <= CHAT_GAP_THRESHOLD:
            streak_start = row[0]
        else:
            streak_start = ts

        await db.execute(
            """INSERT INTO chat_activity (guild_id, channel_type, streak_start, last_message) VALUES (?,?,?,?)
               ON CONFLICT(guild_id, channel_type) DO UPDATE SET streak_start=excluded.streak_start, last_message=excluded.last_message""",
            (message.guild.id, channel_type, streak_start, ts),
        )
        await db.commit()

    # ---------------- CONFIG CANALI CHAT MONITORATI ----------------
    @commands.hybrid_command(name="chatconfig", description="Imposta il canale della chat generale da monitorare per le quest")
    @app_commands.describe(channel="Canale della chat generale")
    @commands.has_permissions(manage_guild=True)
    async def chatconfig(self, ctx: commands.Context, channel: discord.TextChannel):
        await update_guild_config(ctx.guild.id, general_chat_channel=channel.id)
        await ctx.reply(f"✅ Chat generale impostata su {channel.mention}. Verrà monitorata per le quest \"chat generale\".")

    @commands.hybrid_command(name="chatsconfig", description="Imposta il canale della chat staff da monitorare per le quest")
    @app_commands.describe(channel="Canale della chat staff")
    @commands.has_permissions(manage_guild=True)
    async def chatsconfig(self, ctx: commands.Context, channel: discord.TextChannel):
        await update_guild_config(ctx.guild.id, staff_chat_channel=channel.id)
        await ctx.reply(f"✅ Chat staff impostata su {channel.mention}. Verrà monitorata per le quest \"chat staff\".")

    # ---------------- CONFIG RUOLI STAFF ----------------
    @commands.hybrid_command(name="staff", description="Aggiunge un ruolo alla lista dei ruoli staff abilitati (max 15)")
    @app_commands.describe(role="Ruolo da abilitare come staff")
    @commands.has_permissions(administrator=True)
    async def staff_add_role(self, ctx: commands.Context, role: discord.Role):
        db = await get_db()
        cur = await db.execute("SELECT COUNT(*) FROM staff_roles WHERE guild_id=?", (ctx.guild.id,))
        count = (await cur.fetchone())[0]
        if count >= MAX_STAFF_ROLES:
            return await ctx.reply(f"❌ Hai raggiunto il limite massimo di {MAX_STAFF_ROLES} ruoli staff.")
        await db.execute("INSERT OR IGNORE INTO staff_roles (guild_id, role_id) VALUES (?,?)", (ctx.guild.id, role.id))
        await db.commit()
        await ctx.reply(f"✅ {role.mention} aggiunto ai ruoli staff abilitati alle quest.")

    @commands.hybrid_command(name="staffdelete", description="Resetta tutti i ruoli staff configurati")
    @commands.has_permissions(administrator=True)
    async def staff_delete_roles(self, ctx: commands.Context):
        db = await get_db()
        await db.execute("DELETE FROM staff_roles WHERE guild_id=?", (ctx.guild.id,))
        await db.commit()
        await ctx.reply("✅ Tutti i ruoli staff configurati sono stati rimossi.")

    # ---------------- PUNTI PEX ----------------
    @commands.hybrid_command(name="points", description="Mostra quanti punti Pex hai (solo staff)")
    async def points(self, ctx: commands.Context):
        if not await is_staff(ctx.author):
            return await ctx.reply("❌ Solo i membri dello staff possono usare questo comando.")
        db = await get_db()
        cur = await db.execute("SELECT points FROM staff_points WHERE guild_id=? AND user_id=?", (ctx.guild.id, ctx.author.id))
        row = await cur.fetchone()
        pts = row[0] if row else 0
        await ctx.reply(embed=discord.Embed(title="⭐ Punti Pex", description=f"Hai **{pts}** punti Pex.", color=EMBED_COLOR))

    # ---------------- STAFF QUEST ----------------
    async def _get_or_assign_quests(self, guild_id: int, user_id: int):
        db = await get_db()
        date = today_str()
        cur = await db.execute(
            "SELECT quests_json, progress_json, completed FROM staff_quests WHERE guild_id=? AND user_id=? AND date=?",
            (guild_id, user_id, date),
        )
        row = await cur.fetchone()
        if row:
            return loads(row[0], []), loads(row[1], []), row[2]

        quests = random.sample(QUEST_POOL, k=2)
        assigned = []
        for q in quests:
            n = random.randint(*q["n"])
            quest = {
                "key": q["key"],
                "desc": q["desc"].format(n=n),
                "target": n,
                "trackable": q["trackable"],
                "mode": q.get("mode"),
            }
            if q["trackable"] and q.get("mode") == "diff":
                quest["baseline"] = await _current_stat(guild_id, user_id, q["key"])
            assigned.append(quest)
        progress = [0 for _ in assigned]
        await db.execute(
            "INSERT INTO staff_quests (guild_id, user_id, date, quests_json, progress_json, completed) VALUES (?,?,?,?,?,0)",
            (guild_id, user_id, date, dumps(assigned), dumps(progress)),
        )
        await db.commit()
        return assigned, progress, 0

    @commands.hybrid_command(name="staffquest", description="Mostra le tue missioni staff di oggi")
    async def staffquest(self, ctx: commands.Context):
        if not await is_staff(ctx.author):
            return await ctx.reply("❌ Solo i membri dello staff possono avere delle quest.")
        assigned, progress, completed = await self._get_or_assign_quests(ctx.guild.id, ctx.author.id)
        lines = []
        for i, q in enumerate(assigned):
            check = "✅" if progress[i] >= 1 else "❌"
            lines.append(f"**{i+1}.** {q['desc']} — {check}")
        e = discord.Embed(title="📋 Le tue quest di oggi", description="\n".join(lines), color=EMBED_COLOR)
        e.set_footer(text=f"Ogni quest completata vale +{POINTS_PER_QUEST} punti Pex. Usa /staffquestdone per farle verificare dal bot.")
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="staffquestdone", description="Chiedi al bot di verificare le tue quest di oggi")
    async def staffquest_done(self, ctx: commands.Context):
        if not await is_staff(ctx.author):
            return await ctx.reply("❌ Solo i membri dello staff possono completare le quest.")
        db = await get_db()
        date = today_str()
        assigned, progress, completed_flag = await self._get_or_assign_quests(ctx.guild.id, ctx.author.id)

        newly_completed_points = 0
        for i, q in enumerate(assigned):
            if progress[i] >= 1:
                continue  # già verificata in precedenza
            if q.get("trackable"):
                current = await _current_stat(ctx.guild.id, ctx.author.id, q["key"])
                if q.get("mode") == "streak":
                    done = current >= q["target"]
                else:  # mode == "diff"
                    done = (current - q.get("baseline", 0)) >= q["target"]
            else:
                done = True
            if done:
                progress[i] = 1
                newly_completed_points += POINTS_PER_QUEST

        await db.execute(
            "UPDATE staff_quests SET progress_json=? WHERE guild_id=? AND user_id=? AND date=?",
            (dumps(progress), ctx.guild.id, ctx.author.id, date),
        )
        if newly_completed_points:
            await db.execute(
                """INSERT INTO staff_points (guild_id, user_id, points) VALUES (?,?,?)
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET points = points + ?""",
                (ctx.guild.id, ctx.author.id, newly_completed_points, newly_completed_points),
            )
        await db.commit()

        all_done = all(p >= 1 for p in progress)
        if all_done:
            await db.execute(
                "UPDATE staff_quests SET completed=1 WHERE guild_id=? AND user_id=? AND date=?",
                (ctx.guild.id, ctx.author.id, date),
            )
            await db.commit()
            await ctx.reply(f"✅ Bravo {ctx.author.mention} hai completato tutte le quest! ")
        else:
            await ctx.reply(f"❌ NO {ctx.author.mention} NON HAI COMPLETATO LE QUEST! ")

    # ---------------- DESK ----------------
    @commands.hybrid_command(name="desk", description="Mostra il messaggio desk configurato")
    async def desk(self, ctx: commands.Context):
        cfg = await get_guild_config(ctx.guild.id)
        text = cfg.get("desk_text")
        if not text:
            return await ctx.reply("❌ Nessun desk configurato. Usa `/deskcreate` per crearne uno.")
        await ctx.reply(text)

    @commands.hybrid_command(name="deskcreate", description="Crea/aggiorna il messaggio desk (testo semplice, non embed)")
    @app_commands.describe(message="Contenuto del desk")
    @commands.has_permissions(manage_guild=True)
    async def deskcreate(self, ctx: commands.Context, *, message: str):
        await update_guild_config(ctx.guild.id, desk_text=message)
        await ctx.reply("✅ Desk configurato/aggiornato.")

    @commands.hybrid_command(name="deskremove", description="Rimuove il desk configurato")
    @commands.has_permissions(manage_guild=True)
    async def deskremove(self, ctx: commands.Context):
        await update_guild_config(ctx.guild.id, desk_text=None)
        await ctx.reply("✅ Desk rimosso.")

    # ---------------- TRIAL ----------------
    @commands.hybrid_command(name="trial", description="Mostra le domande del provino configurate (messaggio di testo)")
    async def trial(self, ctx: commands.Context):
        cfg = await get_guild_config(ctx.guild.id)
        questions = loads(cfg.get("trial_questions"), [])
        if not questions:
            return await ctx.reply("❌ Nessuna domanda provino configurata.")
        text = "**📋 Domande provino:**\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        await ctx.reply(text)

    @commands.hybrid_command(name="trialcreate", description="Configura le domande del provino (max 20, separate da ' | ')")
    @app_commands.describe(questions="Domande separate da ' | ' (es: Domanda 1 | Domanda 2 | ...)")
    @commands.has_permissions(manage_guild=True)
    async def trialcreate(self, ctx: commands.Context, *, questions: str):
        q_list = [q.strip() for q in questions.split("|") if q.strip()]
        if len(q_list) > 20:
            return await ctx.reply("❌ Puoi configurare al massimo 20 domande.")
        await update_guild_config(ctx.guild.id, trial_questions=dumps(q_list))
        await ctx.reply(f"✅ Configurate **{len(q_list)}** domande provino.")

    @commands.hybrid_command(name="trialremove", description="Rimuove tutte le domande provino configurate")
    @commands.has_permissions(manage_guild=True)
    async def trialremove(self, ctx: commands.Context):
        await update_guild_config(ctx.guild.id, trial_questions=None)
        await ctx.reply("✅ Domande provino rimosse.")

    # ---------------- PARTNERSHIP ----------------
    @commands.hybrid_command(name="partnershipadd", description="Apre un modulo per creare e pubblicare una nuova partnership")
    @commands.has_permissions(manage_guild=True)
    async def partnership_add(self, ctx: commands.Context):
        if not ctx.interaction:
            return await ctx.reply("❌ Questo comando apre un modulo, quindi funziona solo come slash command: usa `/partnershipadd`.")
        await ctx.interaction.response.send_modal(PartnershipModal())

    @commands.hybrid_command(name="partnership", description="Invia una partnership salvata (messaggio di testo)")
    @app_commands.describe(name="Nome della partnership da inviare")
    async def partnership_send(self, ctx: commands.Context, name: str):
        db = await get_db()
        cur = await db.execute("SELECT message FROM partnerships WHERE guild_id=? AND name=?", (ctx.guild.id, name))
        row = await cur.fetchone()
        if not row:
            return await ctx.reply(f"❌ Nessuna partnership trovata con il nome **{name}**.")
        await ctx.channel.send(row[0], allowed_mentions=discord.AllowedMentions.none())
        if ctx.interaction:
            await ctx.reply("✅ Inviata.", ephemeral=True)

    @commands.hybrid_command(name="partnershipdelete", description="Rimuove una partnership salvata")
    @app_commands.describe(name="Nome della partnership da rimuovere")
    @commands.has_permissions(manage_guild=True)
    async def partnership_delete(self, ctx: commands.Context, name: str):
        db = await get_db()
        await db.execute("DELETE FROM partnerships WHERE guild_id=? AND name=?", (ctx.guild.id, name))
        await db.commit()
        await ctx.reply(f"✅ Partnership **{name}** rimossa (se esisteva).")

    @commands.hybrid_command(name="partnershiplist", description="Elenca le partnership salvate")
    async def partnership_list(self, ctx: commands.Context):
        db = await get_db()
        cur = await db.execute("SELECT name FROM partnerships WHERE guild_id=?", (ctx.guild.id,))
        rows = await cur.fetchall()
        if not rows:
            return await ctx.reply("Nessuna partnership salvata.")
        await ctx.reply("📋 Partnership salvate: " + ", ".join(f"`{r[0]}`" for r in rows))


class PartnershipModal(discord.ui.Modal, title="Nuova partnership"):
    description = discord.ui.TextInput(
        label="Descrizione della partnership",
        style=discord.TextStyle.paragraph,
        placeholder="Incolla qui il testo della partnership. I ping verranno rimossi automaticamente.",
        max_length=2000,
        required=True,
    )
    server_name = discord.ui.TextInput(
        label="Nome del server partner",
        style=discord.TextStyle.short,
        max_length=100,
        required=True,
    )
    server_members = discord.ui.TextInput(
        label="Membri del server partner",
        style=discord.TextStyle.short,
        placeholder="es: 1500",
        max_length=10,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        import re
        clean_desc = re.sub(r"<@[!&]?\d+>|@everyone|@here", "", str(self.description.value)).strip()

        text = (
            f"🤝 **PARTNERSHIP**\n\n"
            f"{clean_desc}\n\n"
            f"**Server:** {self.server_name.value}\n"
            f"**Membri:** {self.server_members.value}"
        )

        db = await get_db()
        await db.execute(
            "INSERT INTO partnerships (guild_id, name, message, author_id) VALUES (?,?,?,?)",
            (interaction.guild.id, str(self.server_name.value), text, interaction.user.id),
        )
        await db.commit()

        await interaction.channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message("✅ Partnership pubblicata.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Si è verificato un errore durante l'invio.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Si è verificato un errore durante l'invio.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Staff(bot))
