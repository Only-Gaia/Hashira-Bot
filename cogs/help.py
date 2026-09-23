import discord
from discord import app_commands
from discord.ext import commands

from config import EMBED_COLOR

# Nome visualizzato + emoji per ogni cog (nome classe -> etichetta)
CATEGORY_LABELS = {
    "Moderation": "🔨 Moderazione",
    "Logs": "📋 Log",
    "Invites": "📨 Inviti",
    "Leveling": "📊 Livelli",
    "Giveaway": "🎉 Giveaway",
    "EmbedsWelcome": "👋 Benvenuto / Embed / Sticky",
    "AutoMod": "🛡️ Automod",
    "Info": "ℹ️ Info",
    "Economy": "💰 Economia",
    "Fun": "🎮 Divertimento",
    "Staff": "⭐ Staff",
    "Help": "❓ Aiuto",
}

# Ordine in cui mostrare le categorie nel menu
CATEGORY_ORDER = [
    "Moderation", "AutoMod", "Logs", "Invites", "Leveling",
    "Giveaway", "EmbedsWelcome", "Economy", "Fun", "Staff", "Info", "Help",
]


def format_command(cmd: commands.Command) -> str:
    params = ""
    if hasattr(cmd, "clean_params"):
        params = " ".join(f"<{p}>" for p in cmd.clean_params.keys())
    desc = cmd.description or cmd.short_doc or "Nessuna descrizione"
    return f"**`.{cmd.qualified_name} {params}`**\n{desc}".strip()


class CategorySelect(discord.ui.Select):
    def __init__(self, cog_map: dict[str, list[commands.Command]]):
        options = []
        for key in CATEGORY_ORDER:
            if key in cog_map and cog_map[key]:
                label = CATEGORY_LABELS.get(key, key)
                options.append(discord.SelectOption(label=label, value=key))
        super().__init__(placeholder="📂 Scegli una categoria...", options=options, min_values=1, max_values=1)
        self.cog_map = cog_map

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        label = CATEGORY_LABELS.get(key, key)
        commands_list = self.cog_map.get(key, [])

        e = discord.Embed(title=label, color=EMBED_COLOR)
        e.description = "\n\n".join(format_command(c) for c in commands_list) or "Nessun comando in questa categoria."
        e.set_footer(text="Ogni comando funziona sia con \".\" che come slash \"/\" (salvo dove indicato).")
        await interaction.response.edit_message(embed=e, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, cog_map: dict[str, list[commands.Command]]):
        super().__init__(timeout=120)
        self.add_item(CategorySelect(cog_map))


class Help(commands.Cog):
    """Comando di aiuto: elenca tutti i comandi del bot per categoria."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.help_command = None  # disattiva l'help command di default di discord.py

    def build_cog_map(self) -> dict[str, list[commands.Command]]:
        cog_map: dict[str, list[commands.Command]] = {}
        for cog_name, cog in self.bot.cogs.items():
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if cmds:
                cog_map[cog_name] = sorted(cmds, key=lambda c: c.name)
        return cog_map

    @commands.hybrid_command(name="help", description="Mostra tutti i comandi del bot organizzati per categoria")
    @app_commands.describe(categoria="Nome di una categoria specifica (facoltativo)")
    async def help_cmd(self, ctx: commands.Context, categoria: str = None):
        cog_map = self.build_cog_map()

        if categoria:
            match = None
            for key in cog_map:
                if key.lower() == categoria.lower() or CATEGORY_LABELS.get(key, "").lower().find(categoria.lower()) != -1:
                    match = key
                    break
            if not match:
                return await ctx.reply(f"❌ Categoria `{categoria}` non trovata. Usa `/help` senza argomenti per vedere l'elenco.")
            label = CATEGORY_LABELS.get(match, match)
            e = discord.Embed(title=label, color=EMBED_COLOR)
            e.description = "\n\n".join(format_command(c) for c in cog_map[match])
            return await ctx.reply(embed=e)

        total_commands = sum(len(v) for v in cog_map.values())
        e = discord.Embed(
            title="📖 Menu di aiuto — Hashira Bot",
            description=(
                f"Ho **{total_commands}** comandi disponibili, divisi in categorie.\n"
                "Seleziona una categoria dal menu qui sotto per vederli, oppure usa `/help <categoria>`.\n\n"
                "Ogni comando funziona sia con il prefisso `.` sia come slash `/` (salvo `/purge`, disponibile solo come slash)."
            ),
            color=EMBED_COLOR,
        )
        for key in CATEGORY_ORDER:
            if key in cog_map:
                e.add_field(name=CATEGORY_LABELS.get(key, key), value=f"{len(cog_map[key])} comandi", inline=True)

        view = HelpView(cog_map)
        await ctx.reply(embed=e, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
