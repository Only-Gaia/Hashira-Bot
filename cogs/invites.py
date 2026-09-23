import discord
from discord import app_commands
from discord.ext import commands

from database import get_db
from config import EMBED_COLOR


class Invites(commands.Cog):
    """Traccia quanti inviti validi ha fatto ogni utente."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}  # guild_id -> {invite_code: uses}

    async def cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except discord.Forbidden:
            self.invite_cache[guild.id] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        before = self.invite_cache.get(guild.id, {})
        try:
            after_invites = await guild.invites()
        except discord.Forbidden:
            return
        after = {inv.code: inv.uses for inv in after_invites}

        used_invite = None
        for inv in after_invites:
            if before.get(inv.code, 0) < inv.uses:
                used_invite = inv
                break

        self.invite_cache[guild.id] = after

        if used_invite and used_invite.inviter:
            db = await get_db()
            await db.execute(
                """INSERT INTO invites (guild_id, user_id, count) VALUES (?,?,1)
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1""",
                (guild.id, used_invite.inviter.id),
            )
            await db.commit()

    # ---------------- COMANDI ----------------
    @commands.hybrid_command(name="invites", description="Mostra quanti inviti ha fatto un utente")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def invites_cmd(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        db = await get_db()
        cur = await db.execute("SELECT count FROM invites WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        row = await cur.fetchone()
        count = row[0] if row else 0
        e = discord.Embed(title="📨 Inviti", description=f"{member.mention} ha invitato **{count}** persone.", color=EMBED_COLOR)
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="invitesleaderboard", description="Mostra la classifica degli inviti")
    async def invites_leaderboard(self, ctx: commands.Context):
        db = await get_db()
        cur = await db.execute(
            "SELECT user_id, count FROM invites WHERE guild_id=? ORDER BY count DESC LIMIT 10", (ctx.guild.id,)
        )
        rows = await cur.fetchall()
        if not rows:
            return await ctx.reply("Nessun invito registrato.")
        desc = "\n".join(f"**#{i}** <@{uid}> — {c} inviti" for i, (uid, c) in enumerate(rows, start=1))
        await ctx.reply(embed=discord.Embed(title="🏆 Classifica inviti", description=desc, color=EMBED_COLOR))

    @commands.hybrid_command(name="resetinvites", description="Azzera gli inviti di un utente")
    @app_commands.describe(member="Utente da resettare")
    @commands.has_permissions(manage_guild=True)
    async def reset_invites(self, ctx: commands.Context, member: discord.Member):
        db = await get_db()
        await db.execute("UPDATE invites SET count=0 WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        await db.commit()
        await ctx.reply(f"✅ Inviti di {member.mention} azzerati.")

    @commands.hybrid_command(name="resetallinvites", description="Azzera gli inviti di tutti gli utenti")
    @commands.has_permissions(administrator=True)
    async def reset_all_invites(self, ctx: commands.Context):
        db = await get_db()
        await db.execute("UPDATE invites SET count=0 WHERE guild_id=?", (ctx.guild.id,))
        await db.commit()
        await ctx.reply("✅ Tutti gli inviti del server sono stati azzerati.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
