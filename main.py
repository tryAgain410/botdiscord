"""
Discord Bot — voice time + message tracking
Prefix: "."
Commands:
.топ дня
.топвся
.топвойс

Visual styled like JuniperBot
Keep-alive: Flask
"""

import os
import json
import threading
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from flask import Flask

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

PREFIX = "."
DATA_FILE = "data.json"
MOSCOW_TZ = timezone(timedelta(hours=3))

EMBED_COLOR = 0x111214
ACCENT_COLOR = 0x8B5CF6

# ─────────────────────────────────────────────────────────────
# FLASK KEEP ALIVE
# ─────────────────────────────────────────────────────────────

app_flask = Flask(__name__)


@app_flask.route("/")
def home():
    return "Bot is alive"


def run_flask():
    port = int(os.environ.get("FLASK_PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)


def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()


# ─────────────────────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────────────────────

def _moscow_now():
    return datetime.now(MOSCOW_TZ)


def _today():
    return _moscow_now().strftime("%Y-%m-%d")


def _empty_data():
    return {
        "messages": {
            "all_time": {},
            "daily": {}
        },
        "voice": {
            "all_time": {}
        },
        "usernames": {},
        "last_reset": _today(),
    }


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                d.setdefault("usernames", {})
                return d
        except Exception:
            pass

    return _empty_data()


def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _format_voice(seconds):
    minutes = seconds / 60

    if minutes >= 60:
        return f"{minutes / 60:.1f} ч."

    return f"{int(minutes)} мин."


def _name(uid_str):
    return data["usernames"].get(uid_str, f"User#{uid_str[-4:]}")


# ─────────────────────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

voice_join_times = {}
data = {}


# ─────────────────────────────────────────────────────────────
# DAILY RESET
# ─────────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def daily_reset_task():
    today = _today()

    if data.get("last_reset") != today:
        data["messages"]["daily"] = {}
        data["last_reset"] = today

        save_data(data)

        print(f"[{today}] Daily stats reset.")


# ─────────────────────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global data

    data = load_data()

    today = _today()

    if data.get("last_reset") != today:
        data["messages"]["daily"] = {}
        data["last_reset"] = today
        save_data(data)

    daily_reset_task.start()

    print(
        f"✅ Logged in as {bot.user} — "
        f"Moscow: {_moscow_now().strftime('%Y-%m-%d %H:%M')}"
    )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    uid = str(message.author.id)

    data["usernames"][uid] = message.author.display_name

    data["messages"]["all_time"][uid] = (
        data["messages"]["all_time"].get(uid, 0) + 1
    )

    data["messages"]["daily"][uid] = (
        data["messages"]["daily"].get(uid, 0) + 1
    )

    save_data(data)

    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member, before, after):
    uid = member.id
    uid_str = str(uid)

    data["usernames"][uid_str] = member.display_name

    # JOIN
    if before.channel is None and after.channel is not None:
        voice_join_times[uid] = datetime.now(timezone.utc)

    # LEAVE / SWITCH
    elif before.channel is not None:

        if uid in voice_join_times:
            elapsed = (
                datetime.now(timezone.utc)
                - voice_join_times.pop(uid)
            ).total_seconds()

            data["voice"]["all_time"][uid_str] = (
                data["voice"]["all_time"].get(uid_str, 0)
                + elapsed
            )

            save_data(data)

        # SWITCH CHANNEL
        if after.channel is not None:
            voice_join_times[uid] = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────
# LEADERBOARD VIEW
# ─────────────────────────────────────────────────────────────

class LeaderboardView(View):

    def __init__(self, ctx, ranking, title, mode="messages"):
        super().__init__(timeout=180)

        self.ctx = ctx
        self.ranking = ranking
        self.title = title
        self.mode = mode

        self.page = 0
        self.per_page = 5

        self.max_pages = max(
            1,
            (len(ranking) - 1) // self.per_page + 1
        )

        self.update_buttons()

    # ─────────────────────────────────────────

    def update_buttons(self):

        self.clear_items()

        first_btn = Button(
            emoji="⏪",
            style=discord.ButtonStyle.secondary,
            row=0
        )

        prev_btn = Button(
            emoji="◀",
            style=discord.ButtonStyle.secondary,
            row=0
        )

        next_btn = Button(
            emoji="▶",
            style=discord.ButtonStyle.secondary,
            row=0
        )

        last_btn = Button(
            emoji="⏩",
            style=discord.ButtonStyle.secondary,
            row=0
        )

        close_btn = Button(
            emoji="❌",
            style=discord.ButtonStyle.danger,
            row=0
        )

        # ─────────────────────────────────────

        async def first_callback(interaction: discord.Interaction):

            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое.",
                    ephemeral=True
                )

            self.page = 0

            await interaction.response.edit_message(
                embed=self.make_embed(),
                view=self
            )

        async def prev_callback(interaction: discord.Interaction):

            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое.",
                    ephemeral=True
                )

            if self.page > 0:
                self.page -= 1

            await interaction.response.edit_message(
                embed=self.make_embed(),
                view=self
            )

        async def next_callback(interaction: discord.Interaction):

            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое.",
                    ephemeral=True
                )

            if self.page < self.max_pages - 1:
                self.page += 1

            await interaction.response.edit_message(
                embed=self.make_embed(),
                view=self
            )

        async def last_callback(interaction: discord.Interaction):

            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое.",
                    ephemeral=True
                )

            self.page = self.max_pages - 1

            await interaction.response.edit_message(
                embed=self.make_embed(),
                view=self
            )

        async def close_callback(interaction: discord.Interaction):

            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое.",
                    ephemeral=True
                )

            await interaction.response.defer()
            await interaction.message.delete()

        # ─────────────────────────────────────

        first_btn.callback = first_callback
        prev_btn.callback = prev_callback
        next_btn.callback = next_callback
        last_btn.callback = last_callback
        close_btn.callback = close_callback

        self.add_item(first_btn)
        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(last_btn)
        self.add_item(close_btn)

    # ─────────────────────────────────────────

    def make_embed(self):

        embed = discord.Embed(
            title=f"🏆 {self.title}",
            color=ACCENT_COLOR
        )

        start = self.page * self.per_page
        end = start + self.per_page

        sliced = self.ranking[start:end]

        medals = {
            0: "🥇",
            1: "🥈",
            2: "🥉"
        }

        desc = ""

        for i, (uid, value) in enumerate(sliced, start=start):

            medal = medals.get(i, f"`#{i+1}`")

            username = _name(uid)

            if self.mode == "voice":
                value_text = _format_voice(value)
                stat_label = "В голосовых"
            else:
                value_text = f"{value}"
                stat_label = "Сообщений"

            desc += (
                f"{medal} "
                f"**{username}**\n"
                f"> {stat_label}: **{value_text}**\n\n"
            )

        embed.description = desc

        # делаем embed шире визуально
        embed.add_field(
            name="",
            value="⠀",
            inline=False
        )

        embed.set_footer(
            text=(
                f"Страница {self.page + 1}/{self.max_pages} "
                f"• Всего участников: {len(self.ranking)}"
            )
        )

        if self.ctx.guild.icon:
            embed.set_thumbnail(
                url=self.ctx.guild.icon.url
            )

        return embed


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────

@bot.command(name="топ")
async def top_day(ctx, *, arg=""):

    if arg.strip() != "дня":
        await ctx.send("Используй: `.топ дня`")
        return

    ranking = sorted(
        data["messages"]["daily"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        await ctx.send("Сегодня ещё никто не писал 😴")
        return

    view = LeaderboardView(
        ctx,
        ranking,
        "Топ дня",
        mode="messages"
    )

    await ctx.send(
        embed=view.make_embed(),
        view=view
    )


@bot.command(name="топвся")
async def top_all(ctx):

    ranking = sorted(
        data["messages"]["all_time"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        await ctx.send("Данных пока нет.")
        return

    view = LeaderboardView(
        ctx,
        ranking,
        "Топ всего времени",
        mode="messages"
    )

    await ctx.send(
        embed=view.make_embed(),
        view=view
    )


@bot.command(name="топвойс")
async def top_voice(ctx):

    ranking = sorted(
        data["voice"]["all_time"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        await ctx.send("Пока никто не был в голосовых каналах.")
        return

    view = LeaderboardView(
        ctx,
        ranking,
        "Топ голосового",
        mode="voice"
    )

    await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    token = os.environ.get("DISCORD_TOKEN")

    if not token:
        raise RuntimeError(
            "Set DISCORD_TOKEN environment variable."
        )

    keep_alive()

    bot.run(token)
