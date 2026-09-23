import hashlib
import random

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db, now
from config import EMBED_COLOR

EIGHT_BALL_ANSWERS = [
    "Sì, sicuramente.", "È certo.", "Senza dubbio.", "Sì.", "Probabilmente sì.",
    "Le prospettive sono buone.", "Segnali indicano di sì.", "Risposta poco chiara, riprova.",
    "Chiedi di nuovo più tardi.", "Meglio non dirtelo ora.", "Non posso prevederlo ora.",
    "Concentrati e richiedi.", "Non contarci.", "La mia risposta è no.", "Le mie fonti dicono no.",
    "Prospettive non molto buone.", "Molto dubbioso.",
]


def stable_percent(*parts: str) -> int:
    """Genera una percentuale stabile (0-100) basata sugli ID, così il risultato resta coerente."""
    key = "-".join(sorted(parts))
    h = hashlib.sha256(key.encode()).hexdigest()
    return int(h, 16) % 101


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="ship", description="Calcola la compatibilità tra due utenti")
    @app_commands.describe(user1="Primo utente", user2="Secondo utente")
    async def ship(self, ctx: commands.Context, user1: discord.Member, user2: discord.Member = None):
        user2 = user2 or ctx.author
        percent = stable_percent(str(user1.id), str(user2.id))
        bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
        e = discord.Embed(title="💞 Ship", description=f"{user1.mention} + {user2.mention} = **{percent}%**\n`{bar}`", color=EMBED_COLOR)
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="kiss", description="Bacia un utente")
    @app_commands.describe(member="Utente da baciare")
    async def kiss(self, ctx: commands.Context, member: discord.Member):
        await ctx.reply(f"💋 {ctx.author.mention} bacia {member.mention}!")

    @commands.hybrid_command(name="hug", description="Abbraccia un utente")
    @app_commands.describe(member="Utente da abbracciare")
    async def hug(self, ctx: commands.Context, member: discord.Member):
        await ctx.reply(f"🤗 {ctx.author.mention} abbraccia {member.mention}!")

    @commands.hybrid_command(name="kill", description="'Uccide' scherzosamente un utente")
    @app_commands.describe(member="Vittima designata")
    async def kill(self, ctx: commands.Context, member: discord.Member):
        await ctx.reply(f"🔪 {ctx.author.mention} ha eliminato {member.mention}... (scherzo, ovviamente 😄)")

    @commands.hybrid_command(name="slap", description="Schiaffeggia un utente")
    @app_commands.describe(member="Utente da schiaffeggiare")
    async def slap(self, ctx: commands.Context, member: discord.Member):
        await ctx.reply(f"👋 {ctx.author.mention} ha schiaffeggiato {member.mention}!")

    @commands.hybrid_command(name="fakekick", description="Finge di espellere un utente (scherzo)")
    @app_commands.describe(member="Vittima dello scherzo")
    async def fakekick(self, ctx: commands.Context, member: discord.Member):
        e = discord.Embed(description=f"👢 **{member}** è stato espulso dal server.", color=0xE74C3C)
        msg = await ctx.reply(embed=e)
        await __import__("asyncio").sleep(3)
        await msg.edit(content="*(scherzo 😄)*", embed=None)

    @commands.hybrid_command(name="fakeban", description="Finge di bannare un utente (scherzo)")
    @app_commands.describe(member="Vittima dello scherzo")
    async def fakeban(self, ctx: commands.Context, member: discord.Member):
        e = discord.Embed(description=f"🔨 **{member}** è stato bannato dal server.", color=0xE74C3C)
        msg = await ctx.reply(embed=e)
        await __import__("asyncio").sleep(3)
        await msg.edit(content="*(scherzo 😄)*", embed=None)

    @commands.hybrid_command(name="marry", description="Chiedi in sposo/a un utente")
    @app_commands.describe(member="Utente da sposare")
    async def marry(self, ctx: commands.Context, member: discord.Member):
        db = await get_db()
        cur = await db.execute("SELECT partner_id FROM marriages WHERE user_id=?", (ctx.author.id,))
        if await cur.fetchone():
            return await ctx.reply("❌ Sei già sposato/a! Usa `/divorce` prima.")
        cur = await db.execute("SELECT partner_id FROM marriages WHERE user_id=?", (member.id,))
        if await cur.fetchone():
            return await ctx.reply(f"❌ {member.mention} è già sposato/a con qualcun altro.")

        view = discord.ui.View(timeout=30)
        accept = discord.ui.Button(label="💍 Accetto", style=discord.ButtonStyle.success)
        decline = discord.ui.Button(label="💔 Rifiuto", style=discord.ButtonStyle.danger)

        async def accept_cb(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                return await interaction.response.send_message("Questa proposta non è per te!", ephemeral=True)
            await db.execute("INSERT INTO marriages (user_id, partner_id, timestamp) VALUES (?,?,?)", (ctx.author.id, member.id, now()))
            await db.execute("INSERT INTO marriages (user_id, partner_id, timestamp) VALUES (?,?,?)", (member.id, ctx.author.id, now()))
            await db.commit()
            await interaction.response.edit_message(content=f"💍 {ctx.author.mention} e {member.mention} sono ora sposati! Congratulazioni!", embed=None, view=None)

        async def decline_cb(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                return await interaction.response.send_message("Questa proposta non è per te!", ephemeral=True)
            await interaction.response.edit_message(content=f"💔 {member.mention} ha rifiutato la proposta.", embed=None, view=None)

        accept.callback = accept_cb
        decline.callback = decline_cb
        view.add_item(accept)
        view.add_item(decline)
        await ctx.reply(f"💍 {ctx.author.mention} ha chiesto in sposo/a {member.mention}!", view=view)

    @commands.hybrid_command(name="divorce", description="Divorzia dal tuo partner")
    async def divorce(self, ctx: commands.Context):
        db = await get_db()
        cur = await db.execute("SELECT partner_id FROM marriages WHERE user_id=?", (ctx.author.id,))
        row = await cur.fetchone()
        if not row:
            return await ctx.reply("❌ Non sei sposato/a con nessuno.")
        partner_id = row[0]
        await db.execute("DELETE FROM marriages WHERE user_id=?", (ctx.author.id,))
        await db.execute("DELETE FROM marriages WHERE user_id=?", (partner_id,))
        await db.commit()
        await ctx.reply(f"💔 {ctx.author.mention} ha divorziato da <@{partner_id}>.")

    @commands.hybrid_command(name="say", description="Fai dire qualcosa al bot")
    @app_commands.describe(message="Testo da far dire al bot")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx: commands.Context, *, message: str):
        if ctx.interaction:
            await ctx.interaction.response.send_message("✅ Inviato.", ephemeral=True)
        else:
            await ctx.message.delete()
        await ctx.channel.send(message)

    @commands.hybrid_command(name="8ball", description="Chiedi qualcosa alla palla magica")
    @app_commands.describe(question="La tua domanda")
    async def eight_ball(self, ctx: commands.Context, *, question: str):
        answer = random.choice(EIGHT_BALL_ANSWERS)
        e = discord.Embed(title="🎱 Palla magica", color=EMBED_COLOR)
        e.add_field(name="Domanda", value=question, inline=False)
        e.add_field(name="Risposta", value=answer, inline=False)
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="gay", description="Misura quanto è gay un utente (per scherzo)")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def gay(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        percent = stable_percent(str(member.id), "gay")
        await ctx.reply(f"🏳️‍🌈 {member.mention} è gay al **{percent}%**!")

    @commands.hybrid_command(name="aura", description="Mostra l'aura di un utente (per scherzo)")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def aura(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        percent = stable_percent(str(member.id), "aura")
        aura_points = (percent - 50) * 200  # da -10000 a +10000
        emoji = "✨" if aura_points >= 0 else "💀"
        await ctx.reply(f"{emoji} {member.mention} ha **{aura_points:+d}** punti di aura!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
