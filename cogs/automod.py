import datetime
import time

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db, get_guild_config, update_guild_config
from config import EMBED_COLOR, ANTILINK_TIMEOUT_SECONDS

LINK_RE = __import__("re").compile(r"(https?://|discord\.gg/|www\.)\S+", __import__("re").IGNORECASE)

DANGEROUS_PERMS = ("administrator", "ban_members", "kick_members", "manage_guild", "manage_roles", "manage_channels")

ANTISPAM_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 ore
ANTISPAM_MAX_MESSAGES = 5
ANTISPAM_WINDOW_SECONDS = 3


class AutoMod(commands.Cog):
    """Anti-link, anti-nuke, anti-raid, anti-spam e blacklist globale."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_actions: dict[int, list[float]] = {}  # user_id -> timestamps azioni pericolose
        self._recent_joins: dict[int, list[float]] = {}  # guild_id -> timestamps join
        self._recent_messages: dict[int, list[float]] = {}  # user_id -> timestamps messaggi (antispam)

    # ---------------- CONFIG ----------------
    @commands.hybrid_command(name="antilink", description="Attiva/disattiva il blocco automatico dei link")
    @app_commands.describe(stato="on per attivare, off per disattivare")
    @commands.has_permissions(administrator=True)
    async def antilink(self, ctx: commands.Context, stato: str):
        enabled = stato.lower() in ("on", "attiva", "true", "si", "sì")
        await update_guild_config(ctx.guild.id, antilink=int(enabled))
        await ctx.reply(f"✅ Anti-link {'attivato' if enabled else 'disattivato'}.")

    @commands.hybrid_command(name="antinuke", description="Attiva/disattiva la protezione anti-nuke")
    @app_commands.describe(stato="on per attivare, off per disattivare")
    @commands.has_permissions(administrator=True)
    async def antinuke(self, ctx: commands.Context, stato: str):
        enabled = stato.lower() in ("on", "attiva", "true", "si", "sì")
        await update_guild_config(ctx.guild.id, antinuke=int(enabled))
        await ctx.reply(f"✅ Anti-nuke {'attivato' if enabled else 'disattivato'}.")

    @commands.hybrid_command(name="antiraid", description="Attiva/disattiva la protezione anti-raid")
    @app_commands.describe(stato="on per attivare, off per disattivare")
    @commands.has_permissions(administrator=True)
    async def antiraid(self, ctx: commands.Context, stato: str):
        enabled = stato.lower() in ("on", "attiva", "true", "si", "sì")
        await update_guild_config(ctx.guild.id, antiraid=int(enabled))
        await ctx.reply(f"✅ Anti-raid {'attivato' if enabled else 'disattivato'}.")

    @commands.hybrid_command(name="antispam", description="Attiva/disattiva la protezione anti-spam")
    @app_commands.describe(stato="on per attivare, off per disattivare")
    @commands.has_permissions(administrator=True)
    async def antispam(self, ctx: commands.Context, stato: str):
        enabled = stato.lower() in ("on", "attiva", "true", "si", "sì")
        await update_guild_config(ctx.guild.id, antispam=int(enabled))
        await ctx.reply(f"✅ Anti-spam {'attivato' if enabled else 'disattivato'} (limite: {ANTISPAM_MAX_MESSAGES} messaggi in {ANTISPAM_WINDOW_SECONDS}s).")

    # ---------------- ANTI-LINK ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return
        cfg = await get_guild_config(message.guild.id)
        if not cfg.get("antilink"):
            return
        if LINK_RE.search(message.content or ""):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            try:
                until = discord.utils.utcnow() + datetime.timedelta(seconds=ANTILINK_TIMEOUT_SECONDS)
                await message.author.timeout(until, reason="Anti-link: invio di un link non autorizzato")
                await message.channel.send(
                    f"🚫 {message.author.mention} è stato silenziato per 2 ore per aver inviato un link.",
                    delete_after=10,
                )
            except discord.Forbidden:
                pass

    # ---------------- ANTI-SPAM (troppi messaggi in poco tempo) ----------------
    @commands.Cog.listener(name="on_message")
    async def on_message_antispam(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return
        cfg = await get_guild_config(message.guild.id)
        if not cfg.get("antispam"):
            return
        now_t = time.time()
        timestamps = self._recent_messages.setdefault(message.author.id, [])
        timestamps.append(now_t)
        timestamps = [t for t in timestamps if now_t - t < ANTISPAM_WINDOW_SECONDS]
        self._recent_messages[message.author.id] = timestamps
        if len(timestamps) > ANTISPAM_MAX_MESSAGES:
            self._recent_messages[message.author.id] = []  # reset per evitare timeout ripetuti
            try:
                until = discord.utils.utcnow() + datetime.timedelta(seconds=ANTISPAM_TIMEOUT_SECONDS)
                await message.author.timeout(until, reason="Anti-spam: troppi messaggi in poco tempo")
                await message.channel.send(
                    f"🚫 {message.author.mention} è stato silenziato per 2 ore per spam.",
                    delete_after=10,
                )
            except discord.Forbidden:
                pass

    # ---------------- ANTI-RAID (troppi join in poco tempo) ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = await get_guild_config(member.guild.id)
        if not cfg.get("antiraid"):
            return
        now_t = time.time()
        joins = self._recent_joins.setdefault(member.guild.id, [])
        joins.append(now_t)
        self._recent_joins[member.guild.id] = [t for t in joins if now_t - t < 10]
        if len(self._recent_joins[member.guild.id]) >= 8:  # 8 join in 10 secondi = raid sospetto
            try:
                await member.guild.edit(verification_level=discord.VerificationLevel.high)
            except discord.Forbidden:
                pass
            ch = member.guild.system_channel
            if ch:
                await ch.send("🚨 Rilevata attività sospetta di raid: livello di verifica alzato automaticamente.")

    # ---------------- ANTI-NUKE (troppe azioni pericolose da un utente) ----------------
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._track_dangerous_action(channel.guild, "manage_channels")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._track_dangerous_action(role.guild, "manage_roles")

    async def _track_dangerous_action(self, guild: discord.Guild, perm: str):
        cfg = await get_guild_config(guild.id)
        if not cfg.get("antinuke"):
            return
        try:
            async for entry in guild.audit_logs(limit=1):
                user = entry.user
                now_t = time.time()
                actions = self._recent_actions.setdefault(user.id, [])
                actions.append(now_t)
                self._recent_actions[user.id] = [t for t in actions if now_t - t < 30]
                if len(self._recent_actions[user.id]) >= 5:  # 5 azioni pericolose in 30s
                    member = guild.get_member(user.id)
                    if member and member.id != guild.owner_id:
                        try:
                            await member.ban(reason="Anti-nuke: troppe azioni distruttive rilevate")
                        except discord.Forbidden:
                            pass
        except discord.Forbidden:
            pass

    # ---------------- BLACKLIST ----------------
    @commands.hybrid_command(name="blacklistadd", description="Aggiunge un utente alla blacklist globale tramite ID")
    @app_commands.describe(user_id="ID dell'utente", reason="Motivo")
    @commands.has_permissions(administrator=True)
    async def blacklist_add(self, ctx: commands.Context, user_id: str, *, reason: str = "Nessun motivo specificato"):
        db = await get_db()
        await db.execute(
            "INSERT INTO blacklist (user_id, reason) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET reason=?",
            (int(user_id), reason, reason),
        )
        await db.commit()
        member = ctx.guild.get_member(int(user_id))
        if member:
            try:
                await member.kick(reason=f"Blacklist globale: {reason}")
            except discord.Forbidden:
                pass
        await ctx.reply(f"✅ Utente `{user_id}` aggiunto alla blacklist.\n**Motivo:** {reason}")

    @commands.hybrid_command(name="blacklistremove", description="Rimuove un utente dalla blacklist globale")
    @app_commands.describe(user_id="ID dell'utente")
    @commands.has_permissions(administrator=True)
    async def blacklist_remove(self, ctx: commands.Context, user_id: str):
        db = await get_db()
        await db.execute("DELETE FROM blacklist WHERE user_id=?", (int(user_id),))
        await db.commit()
        await ctx.reply(f"✅ Utente `{user_id}` rimosso dalla blacklist.")

    @commands.hybrid_command(name="blacklist", description="Mostra tutti gli utenti in blacklist")
    async def blacklist_list(self, ctx: commands.Context):
        db = await get_db()
        cur = await db.execute("SELECT user_id, reason FROM blacklist")
        rows = await cur.fetchall()
        if not rows:
            return await ctx.reply("Nessun utente in blacklist.")
        desc = "\n".join(f"`{uid}` — {reason}" for uid, reason in rows)
        await ctx.reply(embed=discord.Embed(title="🚫 Blacklist globale", description=desc[:4000], color=EMBED_COLOR))

    @commands.Cog.listener(name="on_member_join")
    async def on_member_join_blacklist_check(self, member: discord.Member):
        db = await get_db()
        cur = await db.execute("SELECT reason FROM blacklist WHERE user_id=?", (member.id,))
        row = await cur.fetchone()
        if row:
            try:
                await member.kick(reason=f"Utente in blacklist globale: {row[0]}")
            except discord.Forbidden:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
