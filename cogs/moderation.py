import datetime

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db, now
from config import EMBED_COLOR


def mod_embed(title: str, description: str, color: int = EMBED_COLOR) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    e.timestamp = discord.utils.utcnow()
    return e


class Moderation(commands.Cog):
    """Comandi di moderazione: ban, kick, warn, mute, purge, lock..."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context):
        return True

    # ---------------- BAN ----------------
    @commands.hybrid_command(name="ban", description="Banna un utente dal server")
    @app_commands.describe(member="Utente da bannare", reason="Motivo del ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Nessun motivo specificato"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.reply("❌ Non puoi bannare questo utente (ruolo pari o superiore al tuo).")
        try:
            await member.send(embed=mod_embed("Sei stato bannato", f"Server: **{ctx.guild.name}**\nMotivo: {reason}"))
        except discord.Forbidden:
            pass
        await ctx.guild.ban(member, reason=f"{reason} | Moderatore: {ctx.author}")
        await ctx.reply(embed=mod_embed("🔨 Utente bannato", f"{member.mention} è stato bannato.\n**Motivo:** {reason}"))

    # ---------------- UNBAN ----------------
    @commands.hybrid_command(name="unban", description="Rimuove il ban di un utente tramite ID")
    @app_commands.describe(user_id="ID dell'utente da sbannare", reason="Motivo")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: str, *, reason: str = "Nessun motivo specificato"):
        try:
            user = discord.Object(id=int(user_id))
            await ctx.guild.unban(user, reason=reason)
            await ctx.reply(embed=mod_embed("✅ Utente sbannato", f"ID `{user_id}` sbannato.\n**Motivo:** {reason}"))
        except (discord.NotFound, ValueError):
            await ctx.reply("❌ Utente non trovato nella lista ban o ID non valido.")

    # ---------------- KICK ----------------
    @commands.hybrid_command(name="kick", description="Espelle un utente dal server")
    @app_commands.describe(member="Utente da espellere", reason="Motivo")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Nessun motivo specificato"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.reply("❌ Non puoi espellere questo utente.")
        try:
            await member.send(embed=mod_embed("Sei stato espulso", f"Server: **{ctx.guild.name}**\nMotivo: {reason}"))
        except discord.Forbidden:
            pass
        await member.kick(reason=f"{reason} | Moderatore: {ctx.author}")
        await ctx.reply(embed=mod_embed("👢 Utente espulso", f"{member.mention} è stato espulso.\n**Motivo:** {reason}"))

    # ---------------- WARN ----------------
    @commands.hybrid_command(name="warn", description="Assegna un warn a un utente")
    @app_commands.describe(member="Utente da warnare", reason="Motivo del warn")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Nessun motivo specificato"):
        db = await get_db()
        await db.execute(
            "INSERT INTO warns (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?,?,?,?,?)",
            (ctx.guild.id, member.id, ctx.author.id, reason, now()),
        )
        await db.commit()
        try:
            await member.send(embed=mod_embed("Hai ricevuto un warn", f"Server: **{ctx.guild.name}**\nMotivo: {reason}"))
        except discord.Forbidden:
            pass
        await ctx.reply(embed=mod_embed("⚠️ Warn assegnato", f"{member.mention} è stato warnato.\n**Motivo:** {reason}"))

    # ---------------- WARNS (lista) ----------------
    @commands.hybrid_command(name="warns", description="Mostra i warn di un utente")
    @app_commands.describe(member="Utente di cui vedere i warn")
    async def warns(self, ctx: commands.Context, member: discord.Member):
        db = await get_db()
        cur = await db.execute(
            "SELECT moderator_id, reason, timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id DESC",
            (ctx.guild.id, member.id),
        )
        rows = await cur.fetchall()
        if not rows:
            return await ctx.reply(f"{member.mention} non ha nessun warn.")
        desc = ""
        for i, (mod_id, reason, ts) in enumerate(rows, start=1):
            desc += f"**#{i}** — <t:{ts}:R> — Moderatore: <@{mod_id}>\nMotivo: {reason}\n\n"
        await ctx.reply(embed=mod_embed(f"Warn di {member}", desc[:4000]))

    # ---------------- NICKSET ----------------
    @commands.hybrid_command(name="nickset", description="Cambia il nickname di un utente")
    @app_commands.describe(member="Utente", nickname="Nuovo nickname (vuoto per resettarlo)")
    @commands.has_permissions(manage_nicknames=True)
    async def nickset(self, ctx: commands.Context, member: discord.Member, *, nickname: str = None):
        await member.edit(nick=nickname)
        await ctx.reply(embed=mod_embed("✏️ Nickname modificato", f"{member.mention} → `{nickname or member.name}`"))

    # ---------------- PURGE (solo slash) ----------------
    @app_commands.command(name="purge", description="Elimina un numero di messaggi dal canale")
    @app_commands.describe(amount="Numero di messaggi da eliminare (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Eliminati **{len(deleted)}** messaggi.", ephemeral=True)

    # ---------------- SLOWMODE ----------------
    @commands.hybrid_command(name="slowmode", description="Imposta la modalità lenta del canale (in secondi)")
    @app_commands.describe(seconds="Secondi di slowmode (0 per disattivare)")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: int):
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.reply(embed=mod_embed("🐌 Slowmode impostato", f"Slowmode del canale: **{seconds}s**"))

    # ---------------- LOCK / UNLOCK ----------------
    @commands.hybrid_command(name="lock", description="Blocca il canale corrente per @everyone")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.reply(embed=mod_embed("🔒 Canale bloccato", "Nessuno può più scrivere qui (tranne lo staff)."))

    @commands.hybrid_command(name="unlock", description="Sblocca il canale corrente")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.reply(embed=mod_embed("🔓 Canale sbloccato", "Il canale è di nuovo scrivibile."))

    # ---------------- PEX / DEPEX (assegna/rimuove un ruolo "permesso") ----------------
    @commands.hybrid_command(name="pex", description="Assegna un ruolo di permesso a un utente")
    @app_commands.describe(member="Utente", role="Ruolo da assegnare")
    @commands.has_permissions(manage_roles=True)
    async def pex(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.reply("❌ Non puoi assegnare un ruolo pari o superiore al tuo.")
        await member.add_roles(role, reason=f"Pex da {ctx.author}")
        await ctx.reply(embed=mod_embed("✅ Pex assegnato", f"{member.mention} ha ricevuto il ruolo {role.mention}."))

    @commands.hybrid_command(name="depex", description="Rimuove un ruolo di permesso a un utente")
    @app_commands.describe(member="Utente", role="Ruolo da rimuovere")
    @commands.has_permissions(manage_roles=True)
    async def depex(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.reply("❌ Non puoi rimuovere un ruolo pari o superiore al tuo.")
        await member.remove_roles(role, reason=f"Depex da {ctx.author}")
        await ctx.reply(embed=mod_embed("✅ Pex rimosso", f"A {member.mention} è stato tolto il ruolo {role.mention}."))

    # ---------------- MUTE / UNMUTE (timeout nativo Discord) ----------------
    @commands.hybrid_command(name="mute", description="Silenzia un utente per un tempo determinato (minuti)")
    @app_commands.describe(member="Utente", minutes="Durata in minuti", reason="Motivo")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str = "Nessun motivo specificato"):
        duration = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await ctx.reply(embed=mod_embed("🔇 Utente silenziato", f"{member.mention} silenziato per **{minutes} minuti**.\nMotivo: {reason}"))

    @commands.hybrid_command(name="unmute", description="Rimuove il timeout da un utente")
    @app_commands.describe(member="Utente")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        await member.timeout(None)
        await ctx.reply(embed=mod_embed("🔊 Utente riattivato", f"{member.mention} non è più silenziato."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
