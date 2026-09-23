import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_config, update_guild_config
from config import EMBED_COLOR


async def get_log_channel(guild: discord.Guild):
    cfg = await get_guild_config(guild.id)
    ch_id = cfg.get("log_channel")
    if not ch_id:
        return None
    return guild.get_channel(ch_id)


def base_embed(title: str, color: int = EMBED_COLOR) -> discord.Embed:
    e = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
    return e


class Logs(commands.Cog):
    """Sistema di log: voc, messaggi, canali, ruoli, membri."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- CONFIG (hybrid: .logs set / .logs disable + slash) ----------------
    @commands.hybrid_group(name="logs", description="Gestisci il sistema di log", fallback="info")
    async def logs_cmd(self, ctx: commands.Context):
        cfg = await get_guild_config(ctx.guild.id)
        ch = f"<#{cfg['log_channel']}>" if cfg.get("log_channel") else "Nessuno"
        await ctx.reply(embed=base_embed("📋 Configurazione log").add_field(name="Canale log", value=ch))

    @logs_cmd.command(name="set", description="Imposta il canale dove inviare i log")
    @app_commands.describe(channel="Canale di testo per i log")
    @commands.has_permissions(manage_guild=True)
    async def logs_set(self, ctx: commands.Context, channel: discord.TextChannel):
        await update_guild_config(ctx.guild.id, log_channel=channel.id)
        await ctx.reply(embed=base_embed("✅ Log attivati", 0x2ECC71).add_field(name="Canale", value=channel.mention))

    @logs_cmd.command(name="disable", description="Disattiva il sistema di log")
    @commands.has_permissions(manage_guild=True)
    async def logs_disable(self, ctx: commands.Context):
        await update_guild_config(ctx.guild.id, log_channel=None)
        await ctx.reply(embed=base_embed("🚫 Log disattivati", 0xE74C3C))

    # ---------------- VOICE ----------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        ch = await get_log_channel(member.guild)
        if not ch:
            return
        if before.channel is None and after.channel is not None:
            e = base_embed("🔊 Entrato in un canale vocale", 0x2ECC71)
            e.description = f"{member.mention} è entrato in **{after.channel.name}**"
            await ch.send(embed=e)
        elif before.channel is not None and after.channel is None:
            e = base_embed("🔈 Uscito da un canale vocale", 0xE74C3C)
            e.description = f"{member.mention} è uscito da **{before.channel.name}**"
            await ch.send(embed=e)
        elif before.channel != after.channel and after.channel is not None:
            e = base_embed("🔁 Cambio canale vocale")
            e.description = f"{member.mention}: **{before.channel.name}** → **{after.channel.name}**"
            await ch.send(embed=e)

    # ---------------- MESSAGGI ----------------
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or before.content == after.content:
            return
        ch = await get_log_channel(before.guild)
        if not ch:
            return
        e = base_embed("✏️ Messaggio modificato")
        e.add_field(name="Autore", value=before.author.mention, inline=False)
        e.add_field(name="Canale", value=before.channel.mention, inline=False)
        e.add_field(name="Prima", value=(before.content or "*vuoto*")[:1024], inline=False)
        e.add_field(name="Dopo", value=(after.content or "*vuoto*")[:1024], inline=False)
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        ch = await get_log_channel(message.guild)
        if not ch:
            return
        e = base_embed("🗑️ Messaggio eliminato", 0xE74C3C)
        e.add_field(name="Autore", value=message.author.mention, inline=False)
        e.add_field(name="Canale", value=message.channel.mention, inline=False)
        e.add_field(name="Contenuto", value=(message.content or "*vuoto*")[:1024], inline=False)
        await ch.send(embed=e)

    # ---------------- CANALI / CATEGORIE ----------------
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        ch = await get_log_channel(channel.guild)
        if not ch:
            return
        kind = "Categoria" if isinstance(channel, discord.CategoryChannel) else "Canale"
        e = base_embed(f"➕ {kind} creato/a", 0x2ECC71)
        e.description = f"**{channel.name}**"
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        ch = await get_log_channel(channel.guild)
        if not ch:
            return
        kind = "Categoria" if isinstance(channel, discord.CategoryChannel) else "Canale"
        e = base_embed(f"➖ {kind} eliminato/a", 0xE74C3C)
        e.description = f"**{channel.name}**"
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        ch = await get_log_channel(before.guild)
        if not ch or before.name == after.name:
            return
        e = base_embed("✏️ Canale/Categoria modificato")
        e.description = f"**{before.name}** → **{after.name}**"
        await ch.send(embed=e)

    # ---------------- RUOLI (assegnati/rimossi a un membro) ----------------
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        ch = await get_log_channel(before.guild)
        if not ch:
            return
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added = after_roles - before_roles
        removed = before_roles - after_roles
        for role in added:
            e = base_embed("➕ Ruolo aggiunto", 0x2ECC71)
            e.description = f"{after.mention} ha ricevuto {role.mention}"
            await ch.send(embed=e)
        for role in removed:
            e = base_embed("➖ Ruolo rimosso", 0xE74C3C)
            e.description = f"{after.mention} ha perso {role.mention}"
            await ch.send(embed=e)

    # ---------------- MEMBRI (join/leave) ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ch = await get_log_channel(member.guild)
        if not ch:
            return
        e = base_embed("📥 Utente entrato nel server", 0x2ECC71)
        e.description = f"{member.mention} ({member})"
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        ch = await get_log_channel(member.guild)
        if not ch:
            return
        e = base_embed("📤 Utente uscito dal server", 0xE74C3C)
        e.description = f"{member.mention} ({member})"
        await ch.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
