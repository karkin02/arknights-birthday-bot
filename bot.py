import os
import sys
import json
import re
import asyncio
import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo
import requests
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID"))
MYT = ZoneInfo("Asia/Kuala_Lumpur")
# SGT = ZoneInfo("Asia/Singapore")
ANNOUNCE_TIME = datetime.time(hour=0, minute=0, tzinfo=MYT)
FETCH_TIME = dtime(hour=23, minute=0, tzinfo=MYT)

intents = discord.Intents.default()

class AKBirthdayBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        daily_birthday_check.start()
        refresh_data_task.start()


bot = AKBirthdayBot()


# ===== Data =====
def load_data():
    with open("data/birthdays.json") as f:
        birthdays = json.load(f)
    with open ("data/operator_art.json") as f:
        art = json.load(f)
    return birthdays, art

BIRTHDAYS, ART = load_data()

async def reload_data():
    '''Run fetch script without blocking bot, then reload JSON files'''
    global BIRTHDAYS, ART
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "fetch_ak_wiki_data.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        lines = err.decode().strip().splitlines()
        raise RuntimeError(lines[-1][:200] if lines else "unknown error")
    BIRTHDAYS, ART = load_data()
    print(f"Refreshed: {len(BIRTHDAYS)} birthdays, {len(ART)} art entries.")


def norm(s: str) -> str:
    return re.sub(r"\W", "", s.casefold())

def find_operator(data: dict, query: str):
    target = norm(query)
    for key in data:
        if norm(key) == target:
            return key
    return None


# ===== Events =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s):")
    for guild in bot.guilds:
        print(f" - {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_join(guild):
    print(f"Joined new server: {guild.name} (ID: {guild.id})")



# ===== Commands =====
@bot.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


@bot.tree.command(name="birthday", description="Look up an operator's birthday")
@app_commands.describe(operator="Operator name, e.g. Amiya")
async def birthday(interaction: discord.Interaction, operator: str):
    '''Look up operators' birthday'''
    name = find_operator(BIRTHDAYS, operator)
    bday = BIRTHDAYS.get(name) if name else None
    if bday:
        await interaction.response.send_message(f"🎂 **{name}**'s birthday is **{bday}**.")
    else:
        await interaction.response.send_message(f"I do not have the birthday data for **{operator}** yet.")


# ===== Daily Announcement =====
SINGLE_BIRTHDAY_MESSAGES = [
    "🎂 A special day today — let's wish **{name}** a happy birthday! 🎂",
    "🎉 Today's the day! **{name}** is celebrating their birthday! 🎉",
    "🥳 Everyone say happy birthday to **{name}**! 🥳",
]


@tasks.loop(time=ANNOUNCE_TIME)
async def daily_birthday_check():
    '''Check which operator's birthday is today'''
    today = datetime.datetime.now(MYT).strftime("%m-%d")
    matches = [op for op, bday in BIRTHDAYS.items() if bday == today]
    if not matches:
        return
    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if channel is None:
        print("Announce channel not found; check ANNOUNCE_CHANNEL_ID")
        return

    embeds=[]
    for op in matches:
        image_url = ART.get(op)
        bday = BIRTHDAYS.get(op)
        embed = discord.Embed(
            title=f"🎂 Happy Birthday, {op}! 🎂",
            description=f"Today is **{op}**'s birthday!",
            color=discord.Color.gold()
        )
        embed.add_field(name="Birthday", value=bday, inline=True)
        if image_url:
            embed.set_image(url=image_url)
        embeds.append(embed)

    if len(matches) > 1:
        names_list = ", ".join(matches)
        await channel.send(
            f"🎉 It's a **multi-birthday day**! 🎉 \n{len(matches)} operators are celebrating today: **{names_list}**"
        )
    else:
        message = random.choice(SINGLE_BIRTHDAY_MESSAGES).format(name=matches[0])
        await channel.send(message)

    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i + 10]
        await channel.send(embeds=chunk)


# ===== Data Refresh =====
@tasks.loop(time=FETCH_TIME)
async def refresh_data_task():
    try:
        await reload_data()
    except Exception as e:
        print(f"Refresh failed, keeping old data: {e}")

@refresh_data_task.before_loop
async def before_refresh():
    await bot.wait_until_ready()


# ===== Testing =====
@bot.tree.command(name="testbirthday", description="Manually trigger the birthday check")
async def testbirthday(interaction: discord.Interaction):
    await daily_birthday_check()
    await interaction.response.send_message("Birthday check ran manually.", ephemeral=True)

@bot.tree.command(name="testart", description="Test operator artwork lookup")
async def testart(interaction: discord.Interaction, operator: str):
    name = find_operator(ART, operator)
    image_url = ART.get(name) if name else None    
    if not image_url:
        await interaction.response.send_message(f"No art found for '{operator}'.")
        return
    embed = discord.Embed(title=name, color=discord.Color.blue())
    embed.set_image(url=image_url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="testrefresh", description="Manually refresh the data")
async def testrefresh(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await reload_data()
        await interaction.followup.send(
            f"Refreshed: {len(BIRTHDAYS)} birthdays, {len(ART)} art entries."
        )
    except Exception as e:
        await interaction.followup.send(f"Refresh failed: {e}")


bot.run(TOKEN)