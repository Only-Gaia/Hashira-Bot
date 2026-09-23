import random

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db
from config import EMBED_COLOR, xp_per_level


class Leveling(commands.Cog):
    """Sistema di livelli basato sui messaggi inviati."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns: dict[tuple, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        db = await get_db()
        cur = await db.execute(
            "SELECT xp, level, messages FROM levels WHERE guild_id=? AND user_id=?",
            (message.guild.id, message.author.id),
        )
        row = await cur.fetchone()
        xp, level, messages = row if row else (0, 0, 0)

        xp += random.randint(15, 25)
        messages += 1
        needed = xp_per_level(level)
        leveled_up = False
        while xp >= needed:
            xp -= needed
            level += 1
            leveled_up = True
            needed = xp_per_level(level)

        await db.execute(
            """INSERT INTO levels (guild_id, user_id, xp, level, messages) VALUES (?,?,?,?,?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=?, level=?, messages=?""",
            (message.guild.id, message.author.id, xp, level, messages, xp, level, messages),
        )
        await db.commit()

        if leveled_up:
            try:
                await message.channel.send(
                    f"🎉 {message.author.mention} è salito al livello **{level}**!"
                )
            except discord.Forbidden:
                pass

    @commands.hybrid_command(name="level", description="Mostra il livello di un utente")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def level(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        db = await get_db()
        cur = await db.execute(
            "SELECT xp, level, messages FROM levels WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)
        )
        row = await cur.fetchone()
        xp, level, messages = row if row else (0, 0, 0)
        needed = xp_per_level(level)
        e = discord.Embed(title=f"📊 Livello di {member}", color=EMBED_COLOR)
        e.add_field(name="Livello", value=str(level))
        e.add_field(name="XP", value=f"{xp}/{needed}")
        e.add_field(name="Messaggi totali", value=str(messages))
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="leaderboard", description="Top 10 utenti per livello")
    async def leaderboard(self, ctx: commands.Context):
        db = await get_db()
        cur = await db.execute(
            "SELECT user_id, level, xp FROM levels WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT 10",
            (ctx.guild.id,),
        )
        rows = await cur.fetchall()
        if not rows:
            return await ctx.reply("Nessun dato di livello disponibile.")
        desc = "\n".join(f"**#{i}** <@{uid}> — Livello {lvl} ({xp} XP)" for i, (uid, lvl, xp) in enumerate(rows, start=1))
        await ctx.reply(embed=discord.Embed(title="🏆 Classifica livelli", description=desc, color=EMBED_COLOR))

    @commands.hybrid_command(name="rank", description="Mostra quanto manca al prossimo livello")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def rank(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        db = await get_db()
        cur = await db.execute(
            "SELECT xp, level FROM levels WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)
        )
        row = await cur.fetchone()
        xp, level = row if row else (0, 0)
        needed = xp_per_level(level)
        remaining = needed - xp
        e = discord.Embed(
            title=f"📈 Rank di {member}",
            description=f"Livello attuale: **{level}**\nMancano **{remaining} XP** al livello {level + 1}.",
            color=EMBED_COLOR,
        )
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="messages", description="Mostra quanti messaggi ha inviato un utente")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def messages_cmd(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        db = await get_db()
        cur = await db.execute(
            "SELECT messages FROM levels WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)
        )
        row = await cur.fetchone()
        count = row[0] if row else 0
        await ctx.reply(f"💬 {member.mention} ha inviato **{count}** messaggi.")

    @commands.hybrid_command(name="resetallmess", description="Resetta i messaggi/livelli di tutti")
    @commands.has_permissions(administrator=True)
    async def reset_all_messages(self, ctx: commands.Context):
        db = await get_db()
        await db.execute("DELETE FROM levels WHERE guild_id=?", (ctx.guild.id,))
        await db.commit()
        await ctx.reply("✅ Messaggi e livelli di tutti gli utenti azzerati.")

    @commands.hybrid_command(name="resetmess", description="Resetta i messaggi/livello di un utente")
    @app_commands.describe(member="Utente da resettare")
    @commands.has_permissions(manage_guild=True)
    async def reset_messages(self, ctx: commands.Context, member: discord.Member):
        db = await get_db()
        await db.execute("DELETE FROM levels WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        await db.commit()
        await ctx.reply(f"✅ Messaggi e livello di {member.mention} azzerati.")

    @commands.hybrid_command(name="resetrolemess", description="Resetta i messaggi/livello di chi ha un ruolo")
    @app_commands.describe(role="Ruolo target")
    @commands.has_permissions(administrator=True)
    async def reset_role_messages(self, ctx: commands.Context, role: discord.Role):
        db = await get_db()
        count = 0
        for member in role.members:
            await db.execute("DELETE FROM levels WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
            count += 1
        await db.commit()
        await ctx.reply(f"✅ Azzerati i messaggi/livello di **{count}** utenti con il ruolo {role.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
