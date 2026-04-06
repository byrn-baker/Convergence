from __future__ import annotations

import asyncio
import logging

import discord

from .config import settings

logger = logging.getLogger("convergence-scheduler")

_ask_netclaw = None  # set by main.py at startup


def set_netclaw_fn(fn):
    global _ask_netclaw
    _ask_netclaw = fn


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    logger.info("Discord bot connected as %s (listening in channel %s)", bot.user, settings.discord_channel_id or "ALL")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return
    if settings.discord_channel_id and message.channel.id != settings.discord_channel_id:
        logger.debug("Ignoring message in channel %s (expected %s)", message.channel.id, settings.discord_channel_id)
        return
    if not _ask_netclaw:
        await message.reply("NetClaw proxy not available yet.")
        return

    prompt = message.content.strip()
    if not prompt:
        return

    logger.info("Discord question from %s: %.100s", message.author, prompt)
    await message.reply("⏳ Asking NetClaw... (this can take a few minutes if a poll cycle is running)")
    response = await _ask_netclaw(prompt, timeout=600)

    if not response:
        await message.channel.send("❌ NetClaw didn't respond in time. It may be busy with a poll cycle — try again in a minute.")
        return

    # Discord has a 2000 char limit per message
    for i in range(0, len(response), 1900):
        chunk = response[i:i + 1900]
        if i == 0:
            await message.reply(chunk)
        else:
            await message.channel.send(chunk)


async def start_bot():
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set — bot disabled")
        return
    logger.info("Starting Discord bot...")
    try:
        await bot.start(settings.discord_bot_token)
    except Exception as e:
        logger.error("Discord bot failed: %s", e)


async def stop_bot():
    if bot.is_ready():
        await bot.close()
