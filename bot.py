import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
import json
import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo
import requests

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID"))
MYT = ZoneInfo("Asia/Kuala_Lumpur")
# SGT = ZoneInfo("Asia/Singapore")
ANNOUNCE_TIME = datetime.time(hour=0, minute=0, tzinfo=MYT)
FETCH_TIME = dtime(hour=3, minute=0, tzinfo=MYT)

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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


with open("data/birthdays.json") as f:
    BIRTHDAYS = json.load(f)
with open("data//operator_art.json") as f:
    ART = json.load(f)

@bot.tree.command(name="birthday", description="Look up an operator's birthday")
@app_commands.describe(operator="Operator name, e.g. Amiya")
async def birthday(interaction: discord.Interaction, operator: str):
    '''Look up operators' birthday'''
    name = operator.strip().title()
    bday = BIRTHDAYS.get(name)
    if bday:
        await interaction.response.send_message(f"🎂 **{name}**'s birthday is **{bday}**.")
    else:
        await interaction.response.send_message(f"I do not have the birthday data for **{operator}** yet.")

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
        await channel.send(
            f"It's a special day today, let's wish **{matches[0]}** a happy birthday! 🎂"
        )

    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i + 10]
        await channel.send(embeds=chunk)

@tasks.loop(time=FETCH_TIME)
async def refresh_data_task():
    '''Refresh data to catch up with latest'''
    import subprocess
    subprocess.run(["python", "fetch_ak_wiki_data.py"], cwd="data")
    global BIRTHDAYS, ART
    with open("data/birthdays.json") as f:
        BIRTHDAYS = json.load(f)
    with open ("data/operator_art.json") as f:
        ART = json.load(f)
    print("Refreshed birthday and art data.")


# ===== Testing =====
@bot.tree.command(name="testbirthday", description="Manually trigger the birthday check")
async def testbirthday(interaction: discord.Interaction):
    await daily_birthday_check()
    await interaction.response.send_message("Birthday check ran manually.", ephemeral=True)

@bot.tree.command(name="testart", description="Test operator artwork lookup")
async def testart(interaction: discord.Interaction, operator: str):
    name = operator.strip().title()
    image_url =ART.get(name)
    if not image_url:
        await interaction.response.send_message(f"No art found for '{operator}'.")
        return
    embed = discord.Embed(title=name, color=discord.Color.blue())
    embed.set_image(url=image_url)
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)