import asyncio
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import get_db, dumps, loads, now
from config import EMBED_COLOR

DURATION_RE = re.compile(r"(\d+)([smhdSMHD])")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int:
    """Converte '1h30m', '2d', '45m' in secondi."""
    total = 0
    for value, unit in DURATION_RE.findall(text):
        total += int(value) * UNIT_SECONDS[unit.lower()]
    if total == 0:
        raise ValueError("Formato durata non valido. Usa es: 1h, 30m, 2d, 1h30m")
    return total


def fmt_time(seconds: int) -> str:
    seconds = max(0, seconds)
    if seconds < 60:
        return f"{seconds} secondi"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minuti"
    hours = minutes // 60
    return f"{hours} ore"


class JoinView(discord.ui.View):
    """Bottone Join + Participants su un giveaway attivo."""

    def __init__(self, cog: "Giveaway", message_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.message_id = message_id
        self.join.custom_id = f"giveaway_join_{message_id}"
        self.participants.custom_id = f"giveaway_participants_{message_id}"

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="🎉")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, self.message_id)

    @discord.ui.button(label="Participants", style=discord.ButtonStyle.secondary, emoji="👥")
    async def participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_show_participants(interaction, self.message_id)


class ClaimView(discord.ui.View):
    """Bottone Claim prize per il vincitore; se scade, riparte un reroll."""

    def __init__(self, cog: "Giveaway", message_id: int, winner_id: int, claim_seconds: int):
        super().__init__(timeout=claim_seconds)
        self.cog = cog
        self.message_id = message_id
        self.winner_id = winner_id
        self.claim.custom_id = f"giveaway_claim_{message_id}_{winner_id}"

    @discord.ui.button(label="Claim prize", style=discord.ButtonStyle.success, emoji="🎟️")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.winner_id:
            return await interaction.response.send_message("❌ Solo il vincitore può riscattare questo premio.", ephemeral=True)
        self.stop()
        await self.cog.open_claim_ticket(interaction, self.message_id, self.winner_id)

    async def on_timeout(self):
        await self.cog.reroll(self.message_id, exclude_id=self.winner_id)


class DeliveredView(discord.ui.View):
    """Bottone 'Consegnato ✅' dentro il ticket, elimina il canale."""

    def __init__(self):
        super().__init__(timeout=None)
        self.delivered.custom_id = "giveaway_delivered"

    @discord.ui.button(label="Consegnato ✅", style=discord.ButtonStyle.success)
    async def delivered(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ Premio consegnato. Il canale verrà eliminato tra pochi secondi.")
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason="Premio consegnato")
        except discord.HTTPException:
            pass


class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checker.start()

    def cog_unload(self):
        self.checker.cancel()

    # -------------- Task: chiude i giveaway scaduti --------------
    @tasks.loop(seconds=10)
    async def checker(self):
        db = await get_db()
        cur = await db.execute("SELECT message_id FROM giveaways WHERE ended=0 AND end_time<=?", (now(),))
        rows = await cur.fetchall()
        for (message_id,) in rows:
            await self.end_giveaway(message_id)

    @checker.before_loop
    async def before_checker(self):
        await self.bot.wait_until_ready()

    # -------------- Comando: giveaway create --------------
    @commands.hybrid_group(name="giveaway", description="Gestisci i giveaway del server")
    async def giveaway_group(self, ctx: commands.Context):
        pass

    @giveaway_group.command(name="create", description="Crea un nuovo giveaway")
    @app_commands.describe(
        prize="Oggetto/premio del giveaway",
        duration="Durata (es: 1h, 30m, 2d, 1h30m)",
        channel="Canale dove pubblicare il giveaway",
        winners="Numero di vincitori",
        claim_time="Tempo per riscattare il premio prima del reroll (es: 1m, 5m)",
        invites_required="Numero minimo di inviti richiesti (facoltativo)",
        messages_required="Numero minimo di messaggi richiesti (facoltativo)",
        role_required="Ruolo richiesto per partecipare (facoltativo)",
        role_blacklisted="Ruolo che NON può partecipare (facoltativo)",
    )
    @commands.has_permissions(manage_guild=True)
    async def giveaway_create(
        self,
        ctx: commands.Context,
        prize: str,
        duration: str,
        channel: discord.TextChannel,
        winners: int,
        claim_time: str,
        invites_required: int = 0,
        messages_required: int = 0,
        role_required: discord.Role = None,
        role_blacklisted: discord.Role = None,
    ):
        try:
            duration_seconds = parse_duration(duration)
            claim_seconds = parse_duration(claim_time)
        except ValueError as e:
            return await ctx.reply(f"❌ {e}")

        end_ts = now() + duration_seconds
        requirements = {
            "invites": invites_required,
            "messages": messages_required,
            "role_required": role_required.id if role_required else None,
            "role_blacklisted": role_blacklisted.id if role_blacklisted else None,
            "claim_seconds": claim_seconds,
        }

        e = discord.Embed(
            title="🎉 | 🎉 GIVEAWAY 🎉",
            color=EMBED_COLOR,
        )
        e.add_field(name="🎁 Premio", value=prize, inline=False)
        e.add_field(name="🎉 Premi il pulsante Join per partecipare!", value="\u200b", inline=False)
        e.add_field(name="⏳ Termina", value=f"<t:{end_ts}:R>\n<t:{end_ts}:F>", inline=True)
        req_lines = []
        if invites_required:
            req_lines.append(f"📨 Inviti richiesti: {invites_required}")
        if messages_required:
            req_lines.append(f"💬 Messaggi richiesti: {messages_required}")
        if role_required:
            req_lines.append(f"✅ Ruolo richiesto: {role_required.mention}")
        if role_blacklisted:
            req_lines.append(f"🚫 Ruolo escluso: {role_blacklisted.mention}")
        if req_lines:
            e.add_field(name="📋 Requisiti", value="\n".join(req_lines), inline=False)
        e.add_field(name="🏆 Vincitori", value=str(winners), inline=True)
        e.add_field(name="👥 Partecipanti", value="0", inline=True)
        e.set_footer(text=f"Giveaway ospitato da {ctx.author}")

        temp_view = discord.ui.View(timeout=None)
        msg = await channel.send(embed=e, view=temp_view)

        db = await get_db()
        await db.execute(
            """INSERT INTO giveaways (message_id, guild_id, channel_id, host_id, prize, end_time,
               winners_count, reroll_interval, requirements, participants, ended)
               VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
            (
                msg.id, ctx.guild.id, channel.id, ctx.author.id, prize, end_ts,
                winners, claim_seconds, dumps(requirements), dumps([]),
            ),
        )
        await db.commit()

        view = JoinView(self, msg.id)
        await msg.edit(view=view)
        self.bot.add_view(view, message_id=msg.id)

        await ctx.reply(f"✅ Giveaway creato in {channel.mention}!", ephemeral=True if ctx.interaction else False)

    @giveaway_group.command(name="end", description="Termina subito un giveaway (via ID messaggio)")
    @app_commands.describe(message_id="ID del messaggio del giveaway")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx: commands.Context, message_id: str):
        await self.end_giveaway(int(message_id))
        await ctx.reply("✅ Giveaway terminato.")

    @giveaway_group.command(name="delete", description="Elimina un giveaway senza estrarre vincitori")
    @app_commands.describe(message_id="ID del messaggio del giveaway")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_delete(self, ctx: commands.Context, message_id: str):
        db = await get_db()
        cur = await db.execute("SELECT channel_id FROM giveaways WHERE message_id=?", (int(message_id),))
        row = await cur.fetchone()
        if not row:
            return await ctx.reply("❌ Giveaway non trovato.")
        channel = ctx.guild.get_channel(row[0])
        if channel:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except discord.NotFound:
                pass
        await db.execute("DELETE FROM giveaways WHERE message_id=?", (int(message_id),))
        await db.commit()
        await ctx.reply("🗑️ Giveaway eliminato.")

    # -------------- Logica interna --------------
    async def _get_giveaway(self, message_id: int):
        db = await get_db()
        cur = await db.execute("SELECT * FROM giveaways WHERE message_id=?", (message_id,))
        row = await cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    async def check_requirements(self, member: discord.Member, requirements: dict) -> str | None:
        """Ritorna un messaggio di errore se i requisiti non sono soddisfatti, altrimenti None."""
        db = await get_db()
        if requirements.get("role_blacklisted") and any(r.id == requirements["role_blacklisted"] for r in member.roles):
            return "❌ Non puoi partecipare a questo giveaway (ruolo escluso)."
        if requirements.get("role_required") and not any(r.id == requirements["role_required"] for r in member.roles):
            return "❌ Non hai il ruolo richiesto per partecipare."
        if requirements.get("invites"):
            cur = await db.execute("SELECT count FROM invites WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
            row = await cur.fetchone()
            if (row[0] if row else 0) < requirements["invites"]:
                return f"❌ Ti servono almeno {requirements['invites']} inviti per partecipare."
        if requirements.get("messages"):
            cur = await db.execute("SELECT messages FROM levels WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
            row = await cur.fetchone()
            if (row[0] if row else 0) < requirements["messages"]:
                return f"❌ Ti servono almeno {requirements['messages']} messaggi per partecipare."
        return None

    async def handle_join(self, interaction: discord.Interaction, message_id: int):
        gw = await self._get_giveaway(message_id)
        if not gw or gw["ended"]:
            return await interaction.response.send_message("❌ Questo giveaway non è più attivo.", ephemeral=True)

        requirements = loads(gw["requirements"], {})
        error = await self.check_requirements(interaction.user, requirements)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        participants = loads(gw["participants"], [])
        if interaction.user.id in participants:
            participants.remove(interaction.user.id)
            msg_text = "👋 Hai lasciato il giveaway."
        else:
            participants.append(interaction.user.id)
            msg_text = "🎉 Partecipazione registrata!"

        db = await get_db()
        await db.execute("UPDATE giveaways SET participants=? WHERE message_id=?", (dumps(participants), message_id))
        await db.commit()

        await interaction.response.send_message(msg_text, ephemeral=True)

        # aggiorna il contatore partecipanti nell'embed
        try:
            msg = interaction.message
            embed = msg.embeds[0]
            for i, field in enumerate(embed.fields):
                if field.name.startswith("👥"):
                    embed.set_field_at(i, name="👥 Partecipanti", value=str(len(participants)), inline=True)
                    break
            await msg.edit(embed=embed)
        except (IndexError, discord.HTTPException):
            pass

    async def handle_show_participants(self, interaction: discord.Interaction, message_id: int):
        gw = await self._get_giveaway(message_id)
        participants = loads(gw["participants"], []) if gw else []
        if not participants:
            return await interaction.response.send_message("Nessun partecipante ancora.", ephemeral=True)
        text = ", ".join(f"<@{uid}>" for uid in participants[:50])
        await interaction.response.send_message(f"👥 **Partecipanti ({len(participants)}):**\n{text}", ephemeral=True)

    async def end_giveaway(self, message_id: int):
        gw = await self._get_giveaway(message_id)
        if not gw or gw["ended"]:
            return
        db = await get_db()
        await db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (message_id,))
        await db.commit()

        guild = self.bot.get_guild(gw["guild_id"])
        channel = guild.get_channel(gw["channel_id"]) if guild else None
        if not channel:
            return
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return

        participants = loads(gw["participants"], [])
        await self._pick_and_announce_winner(gw, channel, msg, participants, already_tried=[])

    async def _pick_and_announce_winner(self, gw: dict, channel: discord.TextChannel, msg: discord.Message, pool: list, already_tried: list):
        candidates = [uid for uid in pool if uid not in already_tried]
        requirements = loads(gw["requirements"], {})
        claim_seconds = requirements.get("claim_seconds", 60)

        if not candidates:
            e = discord.Embed(title="😢 Nessun vincitore", description=f"Nessun partecipante valido per **{gw['prize']}**.", color=0xE74C3C)
            await channel.send(embed=e)
            return

        winner_id = random.choice(candidates)

        e = discord.Embed(title="🎉 | 🎊 WE HAVE A WINNER!", color=0xF1C40F)
        e.add_field(name="🎁", value=gw["prize"], inline=False)
        e.add_field(name="🥇🎊 Congratulazioni", value=f"<@{winner_id}>!", inline=False)
        e.add_field(name="⚡ Premi 🎟️ Claim prize per aprire un ticket", value="\u200b", inline=False)
        e.add_field(name="⏳ Tempo per riscattare", value=fmt_time(claim_seconds), inline=True)
        e.add_field(name="⚠️ Attenzione", value="Se non riscatti in tempo, verrà fatto un reroll automatico. 🔁", inline=True)
        e.set_footer(text=f"Giveaway • Host: {gw['host_id']}")

        view = ClaimView(self, gw["message_id"], winner_id, claim_seconds)
        winner_msg = await channel.send(content=f"<@{winner_id}>", embed=e, view=view)

        # salva stato per reroll (memorizziamo il tentativo corrente)
        db = await get_db()
        await db.execute(
            "UPDATE giveaways SET requirements=? WHERE message_id=?",
            (dumps({**requirements, "_already_tried": already_tried + [winner_id], "_winner_msg_id": winner_msg.id}), gw["message_id"]),
        )
        await db.commit()

    async def reroll(self, message_id: int, exclude_id: int):
        gw = await self._get_giveaway(message_id)
        if not gw:
            return
        guild = self.bot.get_guild(gw["guild_id"])
        channel = guild.get_channel(gw["channel_id"]) if guild else None
        if not channel:
            return
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return
        requirements = loads(gw["requirements"], {})
        already_tried = requirements.get("_already_tried", [])
        if exclude_id not in already_tried:
            already_tried.append(exclude_id)
        participants = loads(gw["participants"], [])

        e = discord.Embed(description=f"⏰ <@{exclude_id}> non ha riscattato in tempo, reroll in corso...", color=0xE67E22)
        await channel.send(embed=e)

        await self._pick_and_announce_winner(gw, channel, msg, participants, already_tried)

    async def open_claim_ticket(self, interaction: discord.Interaction, message_id: int, winner_id: int):
        gw = await self._get_giveaway(message_id)
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.get_member(winner_id): discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        ticket_channel = await guild.create_text_channel(
            name=f"premio-{interaction.user.name}"[:90],
            overwrites={k: v for k, v in overwrites.items() if k is not None},
            reason="Ticket riscatto premio giveaway",
        )
        e = discord.Embed(
            title="🎁 Riscatto premio",
            description=f"Congratulazioni <@{winner_id}>! Hai vinto: **{gw['prize']}**\n\nUno staff member ti consegnerà il premio qui. Una volta consegnato, premi **Consegnato ✅**.",
            color=0x2ECC71,
        )
        await ticket_channel.send(content=f"<@{winner_id}>", embed=e, view=DeliveredView())

        db = await get_db()
        await db.execute(
            "INSERT INTO giveaway_tickets (channel_id, guild_id, message_id, winner_id, prize) VALUES (?,?,?,?,?)",
            (ticket_channel.id, guild.id, message_id, winner_id, gw["prize"]),
        )
        await db.commit()

        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
