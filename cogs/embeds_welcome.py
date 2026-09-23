import discord
from discord import app_commands
from discord.ext import commands

from database import get_db, get_guild_config, update_guild_config
from config import EMBED_COLOR


def render_placeholders(text: str, member: discord.Member) -> str:
    return (
        text.replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{membercount}", str(member.guild.member_count))
    )


class EmbedsWelcome(commands.Cog):
    """Welcome, goodbye, embed personalizzati, sticky message e member role."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- MEMBER ROLE (autoruolo all'ingresso) ----------------
    @commands.hybrid_group(name="memberrole", description="Gestisci il ruolo automatico assegnato ai nuovi membri", fallback="info")
    async def member_role_cmd(self, ctx: commands.Context):
        cfg = await get_guild_config(ctx.guild.id)
        role_id = cfg.get("member_role")
        text = f"<@&{role_id}>" if role_id else "Nessun ruolo configurato."
        await ctx.reply(embed=discord.Embed(title="👤 Ruolo membro automatico", description=text, color=EMBED_COLOR))

    @member_role_cmd.command(name="set", description="Imposta il ruolo da assegnare automaticamente ai nuovi membri")
    @app_commands.describe(role="Ruolo da assegnare automaticamente")
    @commands.has_permissions(manage_roles=True)
    async def member_role_set(self, ctx: commands.Context, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            return await ctx.reply("❌ Il mio ruolo deve essere più alto di quello che vuoi assegnare automaticamente.")
        await update_guild_config(ctx.guild.id, member_role=role.id)
        await ctx.reply(embed=discord.Embed(
            title="✅ Ruolo membro impostato",
            description=f"Ogni nuovo utente riceverà automaticamente {role.mention}.",
            color=0x2ECC71,
        ))

    @member_role_cmd.command(name="remove", description="Rimuove il ruolo membro automatico configurato")
    @commands.has_permissions(manage_roles=True)
    async def member_role_remove(self, ctx: commands.Context):
        await update_guild_config(ctx.guild.id, member_role=None)
        await ctx.reply(embed=discord.Embed(title="🚫 Ruolo membro disattivato", description="Non verrà più assegnato nessun ruolo automatico.", color=0xE74C3C))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Assegna il ruolo membro configurato
        cfg = await get_guild_config(member.guild.id)
        role_id = cfg.get("member_role")
        if role_id:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Ruolo membro automatico")
                except discord.Forbidden:
                    pass

        # Messaggio di benvenuto
        if cfg.get("welcome_channel"):
            channel = member.guild.get_channel(cfg["welcome_channel"])
            if channel:
                text = cfg.get("welcome_message") or "Benvenuto/a {user} su **{server}**! Ora siamo in {membercount}."
                e = discord.Embed(description=render_placeholders(text, member), color=0x2ECC71)
                e.set_thumbnail(url=member.display_avatar.url)
                await channel.send(embed=e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cfg = await get_guild_config(member.guild.id)
        if cfg.get("goodbye_channel"):
            channel = member.guild.get_channel(cfg["goodbye_channel"])
            if channel:
                text = cfg.get("goodbye_message") or "{username} ha lasciato **{server}**. Ora siamo in {membercount}."
                e = discord.Embed(description=render_placeholders(text, member), color=0xE74C3C)
                e.set_thumbnail(url=member.display_avatar.url)
                await channel.send(embed=e)

    # ---------------- WELCOME / GOODBYE CONFIG ----------------
    @commands.hybrid_command(name="welcome", description="Configura il messaggio di benvenuto")
    @app_commands.describe(channel="Canale di benvenuto", message="Messaggio (usa {user} {username} {server} {membercount})")
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str = None):
        await update_guild_config(ctx.guild.id, welcome_channel=channel.id, welcome_message=message)
        await ctx.reply(f"✅ Messaggio di benvenuto configurato su {channel.mention}.")

    @commands.hybrid_command(name="goodbye", description="Configura il messaggio di addio")
    @app_commands.describe(channel="Canale di addio", message="Messaggio (usa {user} {username} {server} {membercount})")
    @commands.has_permissions(manage_guild=True)
    async def goodbye(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str = None):
        await update_guild_config(ctx.guild.id, goodbye_channel=channel.id, goodbye_message=message)
        await ctx.reply(f"✅ Messaggio di addio configurato su {channel.mention}.")

    # ---------------- EMBED BUILDER ----------------
    @commands.hybrid_command(name="embedded", description="Invia un embed personalizzato nel canale corrente")
    @app_commands.describe(title="Titolo dell'embed", description="Testo dell'embed", color="Colore esadecimale, es: FF0000")
    @commands.has_permissions(manage_messages=True)
    async def embedded(self, ctx: commands.Context, title: str, description: str, color: str = None):
        try:
            col = int(color, 16) if color else EMBED_COLOR
        except ValueError:
            col = EMBED_COLOR
        e = discord.Embed(title=title, description=description, color=col)
        await ctx.channel.send(embed=e)
        if ctx.interaction:
            await ctx.reply("✅ Embed inviato.", ephemeral=True)

    # ---------------- STICKY MESSAGE ----------------
    @commands.hybrid_command(name="stick", description="Fissa un messaggio in fondo al canale")
    @app_commands.describe(message="Testo del messaggio da fissare")
    @commands.has_permissions(manage_messages=True)
    async def stick(self, ctx: commands.Context, *, message: str):
        db = await get_db()
        sent = await ctx.channel.send(embed=discord.Embed(description=message, color=EMBED_COLOR))
        await db.execute(
            """INSERT INTO sticky (channel_id, guild_id, content, last_message_id) VALUES (?,?,?,?)
               ON CONFLICT(channel_id) DO UPDATE SET content=?, last_message_id=?""",
            (ctx.channel.id, ctx.guild.id, message, sent.id, message, sent.id),
        )
        await db.commit()
        if ctx.interaction:
            await ctx.reply("📌 Messaggio fissato.", ephemeral=True)

    @commands.hybrid_command(name="unstick", description="Rimuove il messaggio fissato dal canale")
    @commands.has_permissions(manage_messages=True)
    async def unstick(self, ctx: commands.Context):
        db = await get_db()
        cur = await db.execute("SELECT last_message_id FROM sticky WHERE channel_id=?", (ctx.channel.id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                msg = await ctx.channel.fetch_message(row[0])
                await msg.delete()
            except discord.NotFound:
                pass
        await db.execute("DELETE FROM sticky WHERE channel_id=?", (ctx.channel.id,))
        await db.commit()
        await ctx.reply("✅ Sticky rimosso.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        db = await get_db()
        cur = await db.execute("SELECT content, last_message_id FROM sticky WHERE channel_id=?", (message.channel.id,))
        row = await cur.fetchone()
        if not row:
            return
        content, last_message_id = row
        if last_message_id:
            try:
                old = await message.channel.fetch_message(last_message_id)
                await old.delete()
            except discord.NotFound:
                pass
        new_msg = await message.channel.send(embed=discord.Embed(description=content, color=EMBED_COLOR))
        await db.execute("UPDATE sticky SET last_message_id=? WHERE channel_id=?", (new_msg.id, message.channel.id))
        await db.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedsWelcome(bot))
