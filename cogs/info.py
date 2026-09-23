import discord
from discord import app_commands
from discord.ext import commands

from config import EMBED_COLOR


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="userinfo", description="Mostra informazioni su un utente")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        e = discord.Embed(title=f"👤 Informazioni su {member}", color=EMBED_COLOR)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="ID", value=member.id, inline=True)
        e.add_field(name="Bot", value="Sì" if member.bot else "No", inline=True)
        e.add_field(name="Account creato", value=f"<t:{int(member.created_at.timestamp())}:D>", inline=False)
        e.add_field(name="Entrato nel server", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "N/D", inline=False)
        roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
        e.add_field(name=f"Ruoli ({len(roles)})", value=" ".join(roles)[:1000] if roles else "Nessuno", inline=False)
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="serverinfo", description="Mostra informazioni sul server")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        e = discord.Embed(title=f"🏠 Informazioni su {guild.name}", color=EMBED_COLOR)
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        e.add_field(name="ID", value=guild.id, inline=True)
        e.add_field(name="Proprietario", value=f"<@{guild.owner_id}>", inline=True)
        e.add_field(name="Membri", value=guild.member_count, inline=True)
        e.add_field(name="Canali testuali", value=len(guild.text_channels), inline=True)
        e.add_field(name="Canali vocali", value=len(guild.voice_channels), inline=True)
        e.add_field(name="Ruoli", value=len(guild.roles), inline=True)
        e.add_field(name="Creato il", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=False)
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="invitebot", description="Mostra il link per invitare il bot")
    async def invitebot(self, ctx: commands.Context):
        url = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(administrator=True))
        e = discord.Embed(title="🔗 Invita il bot", description=f"[Clicca qui per invitarmi]({url})", color=EMBED_COLOR)
        await ctx.reply(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
