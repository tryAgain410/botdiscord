"""
Discord Bot — Stats + Voice Tracker
Commands:
.топдня
.топвся
.топвойс
.стата
"""

import os
import json
import threading
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from flask import Flask

# CONFIG

PREFIX = "."
DATA_FILE = "data.json"
MOSCOW_TZ = timezone(timedelta(hours=3))
ACCENT_COLOR = 0x8B5CF6

# FLASK

app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is alive"

def run_flask():
    port = int(os.environ.get("FLASK_PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()

# TIME

def moscow_now():
    return datetime.now(MOSCOW_TZ)

def today_date():
    return moscow_now().strftime("%Y-%m-%d")

# DATA

def empty_data():
    return {
        "messages": {"daily": {}, "all_time": {}},
        "voice": {"all_time": {}},
        "usernames": {},
        "last_reset": today_date()
    }

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return empty_data()

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# HELPERS

def format_voice(seconds):
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        return f"{hours} ч. {minutes} мин."

    return f"{minutes} мин."

def get_name(uid):
    uid = str(uid)
    return data["usernames"].get(uid, f"User#{uid[-4:]}")

# BOT

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

data = {}
voice_join_times = {}

# DAILY RESET

@tasks.loop(minutes=1)
async def daily_reset():
    current = today_date()

    if data.get("last_reset") != current:
        data["messages"]["daily"] = {}
        data["last_reset"] = current
        save_data(data)

# EVENTS

@bot.event
async def on_ready():
    global data
    data = load_data()

    if not daily_reset.is_running():
        daily_reset.start()

    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    uid = str(message.author.id)

    data["usernames"][uid] = message.author.display_name
    data["messages"]["daily"][uid] = data["messages"]["daily"].get(uid, 0) + 1
    data["messages"]["all_time"][uid] = data["messages"]["all_time"].get(uid, 0) + 1

    save_data(data)

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    uid = member.id
    uid_str = str(uid)

    data["usernames"][uid_str] = member.display_name

    if before.channel is None and after.channel is not None:
        voice_join_times[uid] = datetime.now(timezone.utc)

    elif before.channel is not None:
        if uid in voice_join_times:
            elapsed = (
                datetime.now(timezone.utc) - voice_join_times.pop(uid)
            ).total_seconds()

            data["voice"]["all_time"][uid_str] = (
                data["voice"]["all_time"].get(uid_str, 0) + elapsed
            )

            save_data(data)

        if after.channel is not None:
            voice_join_times[uid] = datetime.now(timezone.utc)

# LEADERBOARD

class LeaderboardView(View):
    def __init__(self, ctx, ranking, title, mode="messages"):
        super().__init__(timeout=180)

        self.ctx = ctx
        self.ranking = ranking
        self.title = title
        self.mode = mode

        self.page = 0
        self.per_page = 5
        self.max_pages = max(1, (len(ranking)-1)//self.per_page+1)

        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        buttons = [
            Button(emoji="⏪", style=discord.ButtonStyle.secondary),
            Button(emoji="◀", style=discord.ButtonStyle.secondary),
            Button(emoji="▶", style=discord.ButtonStyle.secondary),
            Button(emoji="⏩", style=discord.ButtonStyle.secondary),
            Button(emoji="❌", style=discord.ButtonStyle.danger)
        ]

        async def first(i):
            if i.user != self.ctx.author:
                return await i.response.send_message("Это меню не твоё", ephemeral=True)
            self.page = 0
            await i.response.edit_message(embed=self.make_embed(), view=self)

        async def prev(i):
            if i.user != self.ctx.author:
                return await i.response.send_message("Это меню не твоё", ephemeral=True)
            if self.page > 0:
                self.page -= 1
            await i.response.edit_message(embed=self.make_embed(), view=self)

        async def next_(i):
            if i.user != self.ctx.author:
                return await i.response.send_message("Это меню не твоё", ephemeral=True)
            if self.page < self.max_pages - 1:
                self.page += 1
            await i.response.edit_message(embed=self.make_embed(), view=self)

        async def last(i):
            if i.user != self.ctx.author:
                return await i.response.send_message("Это меню не твоё", ephemeral=True)
            self.page = self.max_pages - 1
            await i.response.edit_message(embed=self.make_embed(), view=self)

        async def close(i):
            if i.user != self.ctx.author:
                return await i.response.send_message("Это меню не твоё", ephemeral=True)
            await i.message.delete()

        callbacks = [first, prev, next_, last, close]

        for btn, cb in zip(buttons, callbacks):
            btn.callback = cb
            self.add_item(btn)

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

        # АВАТАР ТОП-1
        if self.ranking:
            top_uid = int(self.ranking[0][0])
            member = self.ctx.guild.get_member(top_uid)

            if member:
                embed.set_thumbnail(url=member.display_avatar.url)

        separator = "────────────────────────────"

        for i, (uid, value) in enumerate(sliced, start=start):
            medal = medals.get(i, f"`#{i+1}`")

            stat = (
                format_voice(value)
                if self.mode == "voice"
                else f"{value} сообщ."
            )

            embed.add_field(
                name=f"{medal} {get_name(uid)}",
                value=f"**{stat}**\n{separator}",
                inline=False
            )

        embed.set_footer(
            text=f"Страница {self.page+1}/{self.max_pages}"
        )

        return embed

# COMMANDS

@bot.command(name="топдня")
async def top_day(ctx):
    ranking = sorted(
        data["messages"]["daily"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return await ctx.send("Сегодня никто не писал")

    view = LeaderboardView(ctx, ranking, "Топ дня")
    await ctx.send(embed=view.make_embed(), view=view)

@bot.command(name="топвся")
async def top_all(ctx):
    ranking = sorted(
        data["messages"]["all_time"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return await ctx.send("Нет данных")

    view = LeaderboardView(ctx, ranking, "Топ вся")
    await ctx.send(embed=view.make_embed(), view=view)

@bot.command(name="топвойс")
async def top_voice(ctx):
    ranking = sorted(
        data["voice"]["all_time"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return await ctx.send("Нет данных")

    view = LeaderboardView(ctx, ranking, "Топ войс", mode="voice")
    await ctx.send(embed=view.make_embed(), view=view)

@bot.command(name="стата")
async def stats(ctx):
    uid = str(ctx.author.id)

    embed = discord.Embed(
        title="📊 Ваша статистика",
        color=ACCENT_COLOR
    )

    embed.add_field(
        name="Сообщений сегодня",
        value=str(data["messages"]["daily"].get(uid, 0)),
        inline=False
    )

    embed.add_field(
        name="Сообщений всего",
        value=str(data["messages"]["all_time"].get(uid, 0)),
        inline=False
    )

    embed.add_field(
        name="Время в войсе",
        value=format_voice(data["voice"]["all_time"].get(uid, 0)),
        inline=False
    )

    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)

# RUN

if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")

    if not token:
        raise RuntimeError("Set DISCORD_TOKEN")

    keep_alive()
    bot.run(token)
