import random

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db, now
from config import EMBED_COLOR, ECONOMY_ADMIN_ID

WORK_COOLDOWN = 60 * 30  # 30 minuti
FISH_COOLDOWN = 60 * 10  # 10 minuti
HUNT_COOLDOWN = 60 * 15  # 15 minuti

WORK_JOBS = [
    ("programmatore", 150, 400),
    ("cameriere", 50, 150),
    ("tassista", 80, 200),
    ("streamer", 30, 500),
    ("idraulico", 100, 250),
]

FISH_ITEMS = [("una vecchia scarpa", 0, 10), ("un pesciolino", 20, 60), ("un pesce raro", 100, 300), ("un tesoro sommerso", 300, 800)]
HUNT_ITEMS = [("un coniglio", 20, 50), ("un cervo", 80, 200), ("un orso", 200, 500), ("niente", 0, 0)]


async def get_balance(user_id: int) -> tuple[int, int]:
    db = await get_db()
    cur = await db.execute("SELECT cash, bank FROM economy WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    if not row:
        await db.execute("INSERT INTO economy (user_id, cash, bank) VALUES (?,0,0)", (user_id,))
        await db.commit()
        return 0, 0
    return row


async def add_cash(user_id: int, amount: int):
    db = await get_db()
    await get_balance(user_id)
    await db.execute("UPDATE economy SET cash = cash + ? WHERE user_id=?", (amount, user_id))
    await db.commit()


class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Economy", player: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.player = player
        self.bet = bet
        self.deck = [v for v in list(range(2, 11)) + [10, 10, 10, 11]] * 4
        random.shuffle(self.deck)
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.finished = False

    @staticmethod
    def hand_value(hand: list[int]) -> int:
        value = sum(hand)
        aces = hand.count(11)
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def render(self, reveal_dealer: bool = False) -> discord.Embed:
        e = discord.Embed(title="🃏 Blackjack", color=EMBED_COLOR)
        e.add_field(name="La tua mano", value=f"{self.player_hand} → **{self.hand_value(self.player_hand)}**", inline=False)
        if reveal_dealer:
            e.add_field(name="Mano del banco", value=f"{self.dealer_hand} → **{self.hand_value(self.dealer_hand)}**", inline=False)
        else:
            e.add_field(name="Mano del banco", value=f"[{self.dealer_hand[0]}, ?]", inline=False)
        e.set_footer(text=f"Puntata: {self.bet} 💰")
        return e

    async def end_game(self, interaction: discord.Interaction):
        self.finished = True
        for child in self.children:
            child.disabled = True
        player_val = self.hand_value(self.player_hand)
        dealer_val = self.hand_value(self.dealer_hand)

        if player_val <= 21:
            while dealer_val < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_val = self.hand_value(self.dealer_hand)

        e = self.render(reveal_dealer=True)
        if player_val > 21:
            result = "💥 Hai sballato! Hai perso la puntata."
            await add_cash(self.player.id, -self.bet)
        elif dealer_val > 21 or player_val > dealer_val:
            result = f"🎉 Hai vinto **{self.bet * 2}**!"
            await add_cash(self.player.id, self.bet)
        elif player_val == dealer_val:
            result = "🤝 Pareggio, puntata restituita."
        else:
            result = "😢 Hai perso la puntata."
            await add_cash(self.player.id, -self.bet)
        e.add_field(name="Risultato", value=result, inline=False)
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="Carta", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            return await interaction.response.send_message("Non è la tua partita!", ephemeral=True)
        self.player_hand.append(self.deck.pop())
        if self.hand_value(self.player_hand) >= 21:
            await self.end_game(interaction)
        else:
            await interaction.response.edit_message(embed=self.render())

    @discord.ui.button(label="Stai", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            return await interaction.response.send_message("Non è la tua partita!", ephemeral=True)
        await self.end_game(interaction)


class Economy(commands.Cog):
    """Economia globale: lo stesso saldo vale su tutti i server dove è presente il bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="cash", description="Mostra il tuo saldo (globale su tutti i server)")
    @app_commands.describe(member="Utente (vuoto = te stesso)")
    async def cash(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        cash_bal, bank_bal = await get_balance(member.id)
        e = discord.Embed(title=f"💰 Portafoglio di {member}", color=EMBED_COLOR)
        e.add_field(name="Contanti", value=str(cash_bal))
        e.add_field(name="Banca", value=str(bank_bal))
        e.set_footer(text="Il saldo è lo stesso su tutti i server con il bot.")
        await ctx.reply(embed=e)

    @commands.hybrid_command(name="work", description="Lavora per guadagnare denaro")
    async def work(self, ctx: commands.Context):
        db = await get_db()
        await get_balance(ctx.author.id)
        cur = await db.execute("SELECT last_work FROM economy WHERE user_id=?", (ctx.author.id,))
        last = (await cur.fetchone())[0] or 0
        if now() - last < WORK_COOLDOWN:
            remaining = WORK_COOLDOWN - (now() - last)
            return await ctx.reply(f"⏳ Potrai lavorare di nuovo tra **{remaining // 60} minuti**.")
        job, lo, hi = random.choice(WORK_JOBS)
        earned = random.randint(lo, hi)
        await db.execute("UPDATE economy SET last_work=? WHERE user_id=?", (now(), ctx.author.id))
        await db.commit()
        await add_cash(ctx.author.id, earned)
        await ctx.reply(f"💼 Hai lavorato come **{job}** e guadagnato **{earned}** 💰")

    @commands.hybrid_command(name="fish", description="Vai a pescare")
    async def fish(self, ctx: commands.Context):
        db = await get_db()
        await get_balance(ctx.author.id)
        cur = await db.execute("SELECT last_fish FROM economy WHERE user_id=?", (ctx.author.id,))
        last = (await cur.fetchone())[0] or 0
        if now() - last < FISH_COOLDOWN:
            remaining = FISH_COOLDOWN - (now() - last)
            return await ctx.reply(f"⏳ Potrai pescare di nuovo tra **{remaining // 60} minuti**.")
        item, lo, hi = random.choice(FISH_ITEMS)
        earned = random.randint(lo, hi)
        await db.execute("UPDATE economy SET last_fish=? WHERE user_id=?", (now(), ctx.author.id))
        await db.commit()
        await add_cash(ctx.author.id, earned)
        await ctx.reply(f"🎣 Hai pescato **{item}** e guadagnato **{earned}** 💰")

    @commands.hybrid_command(name="hunt", description="Vai a caccia")
    async def hunt(self, ctx: commands.Context):
        db = await get_db()
        await get_balance(ctx.author.id)
        cur = await db.execute("SELECT last_hunt FROM economy WHERE user_id=?", (ctx.author.id,))
        last = (await cur.fetchone())[0] or 0
        if now() - last < HUNT_COOLDOWN:
            remaining = HUNT_COOLDOWN - (now() - last)
            return await ctx.reply(f"⏳ Potrai cacciare di nuovo tra **{remaining // 60} minuti**.")
        item, lo, hi = random.choice(HUNT_ITEMS)
        earned = random.randint(lo, hi) if hi else 0
        await db.execute("UPDATE economy SET last_hunt=? WHERE user_id=?", (now(), ctx.author.id))
        await db.commit()
        await add_cash(ctx.author.id, earned)
        if earned:
            await ctx.reply(f"🏹 Hai cacciato **{item}** e guadagnato **{earned}** 💰")
        else:
            await ctx.reply("🏹 Non hai trovato nulla questa volta.")

    @commands.hybrid_command(name="blackjack", description="Gioca a blackjack contro il banco")
    @app_commands.describe(bet="Quanto vuoi puntare")
    async def blackjack(self, ctx: commands.Context, bet: int):
        if bet <= 0:
            return await ctx.reply("❌ La puntata deve essere positiva.")
        cash_bal, _ = await get_balance(ctx.author.id)
        if cash_bal < bet:
            return await ctx.reply("❌ Non hai abbastanza contanti.")
        view = BlackjackView(self, ctx.author, bet)
        await ctx.reply(embed=view.render(), view=view)

    @commands.hybrid_command(name="roulette", description="Gioca alla roulette: rosso, nero o verde")
    @app_commands.describe(bet="Quanto vuoi puntare", color="rosso, nero o verde")
    async def roulette(self, ctx: commands.Context, bet: int, color: str):
        color = color.lower()
        if color not in ("rosso", "nero", "verde"):
            return await ctx.reply("❌ Colore non valido. Usa: rosso, nero o verde.")
        cash_bal, _ = await get_balance(ctx.author.id)
        if bet <= 0 or cash_bal < bet:
            return await ctx.reply("❌ Puntata non valida o saldo insufficiente.")
        roll = random.choices(["rosso", "nero", "verde"], weights=[47, 47, 6])[0]
        if roll == color:
            multiplier = 14 if color == "verde" else 2
            winnings = bet * multiplier
            await add_cash(ctx.author.id, winnings - bet)
            await ctx.reply(f"🎡 È uscito **{roll}**! Hai vinto **{winnings}** 💰")
        else:
            await add_cash(ctx.author.id, -bet)
            await ctx.reply(f"🎡 È uscito **{roll}**. Hai perso **{bet}** 💰")

    @commands.hybrid_command(name="coinflip", description="Lancia una moneta: testa o croce")
    @app_commands.describe(bet="Quanto vuoi puntare", choice="testa o croce")
    async def coinflip(self, ctx: commands.Context, bet: int, choice: str):
        choice = choice.lower()
        if choice not in ("testa", "croce"):
            return await ctx.reply("❌ Scegli 'testa' o 'croce'.")
        cash_bal, _ = await get_balance(ctx.author.id)
        if bet <= 0 or cash_bal < bet:
            return await ctx.reply("❌ Puntata non valida o saldo insufficiente.")
        result = random.choice(["testa", "croce"])
        if result == choice:
            await add_cash(ctx.author.id, bet)
            await ctx.reply(f"🪙 È uscito **{result}**! Hai vinto **{bet}** 💰")
        else:
            await add_cash(ctx.author.id, -bet)
            await ctx.reply(f"🪙 È uscito **{result}**. Hai perso **{bet}** 💰")

    @commands.hybrid_command(name="give", description="Dai del denaro a un altro utente")
    @app_commands.describe(member="Utente a cui inviare denaro", amount="Quantità")
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.reply("❌ Importo non valido.")
        cash_bal, _ = await get_balance(ctx.author.id)
        if cash_bal < amount:
            return await ctx.reply("❌ Non hai abbastanza contanti.")
        await add_cash(ctx.author.id, -amount)
        await add_cash(member.id, amount)
        await ctx.reply(f"💸 Hai inviato **{amount}** 💰 a {member.mention}.")

    @commands.hybrid_command(name="add", description="[Admin economia] Aggiunge denaro a un utente")
    @app_commands.describe(member="Utente", amount="Quantità")
    async def add(self, ctx: commands.Context, member: discord.Member, amount: int):
        if ctx.author.id != ECONOMY_ADMIN_ID:
            return await ctx.reply("❌ Non sei autorizzato a usare questo comando.")
        await add_cash(member.id, amount)
        await ctx.reply(f"✅ Aggiunti **{amount}** 💰 a {member.mention}.")

    @commands.hybrid_command(name="remove", description="[Admin economia] Rimuove denaro a un utente")
    @app_commands.describe(member="Utente", amount="Quantità")
    async def remove(self, ctx: commands.Context, member: discord.Member, amount: int):
        if ctx.author.id != ECONOMY_ADMIN_ID:
            return await ctx.reply("❌ Non sei autorizzato a usare questo comando.")
        await add_cash(member.id, -amount)
        await ctx.reply(f"✅ Rimossi **{amount}** 💰 a {member.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
