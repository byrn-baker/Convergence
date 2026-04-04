"""
NET-OPS Team Discord Bot

Provides slash commands and free-form conversation with the agent team.
Slash commands:
  /netops status   — current team health summary
  /netops report   — latest shift report
  /netops ask <question> — route question to appropriate agent
  /netops security — run security expert immediately
  /netops interfaces — run interface reconciliation immediately

Free-form: in #netops channel, any message gets routed to the supervisor.
"""

import logging

import discord
from discord import app_commands

from ..config import settings
from . import supervisor, security_expert, interface_reconciler

logger = logging.getLogger(__name__)

_bot: "ConvergenceTeamBot | None" = None

_MAX_MSG_LEN = 1900  # Leave some headroom under Discord's 2000-char limit


def _chunk_message(text: str) -> list[str]:
    """Split a long message into Discord-safe chunks."""
    chunks = []
    while len(text) > _MAX_MSG_LEN:
        split_at = text.rfind("\n", 0, _MAX_MSG_LEN)
        if split_at == -1:
            split_at = _MAX_MSG_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def _format_status(status_data: dict) -> str:
    last_poll = status_data.get("last_poll") or "Never"
    findings = status_data.get("findings_count", 0)
    escalations = status_data.get("active_escalations", 0)
    netclaw = "OK" if status_data.get("netclaw_available") else "UNAVAILABLE"
    return (
        f"**NET-OPS Team Status**\n"
        f"Last poll: {last_poll}\n"
        f"Findings: {findings} | Escalations: {escalations}\n"
        f"Netclaw: {netclaw}"
    )


def _format_report(report) -> str:
    if report is None:
        return "No shift report available yet."
    ts = report.timestamp.strftime("%Y-%m-%d %H:%M UTC") if report.timestamp else "unknown"
    lines = [
        f"**Shift Report** — {ts}",
        f"Open issues: {report.open_issues} | Escalations: {report.escalations}",
        "",
    ]
    if not report.findings:
        lines.append("No findings recorded.")
    else:
        for f in report.findings[:10]:  # Cap at 10 findings to stay within Discord limits
            icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🟢"}.get(f.severity.value, "⚪")
            lines.append(f"{icon} **{f.severity.value}** [{f.role.value}] {f.device}: {f.summary}")
        if len(report.findings) > 10:
            lines.append(f"_...and {len(report.findings) - 10} more findings._")
    return "\n".join(lines)


class ConvergenceTeamBot(discord.Client):
    def __init__(self, guild_id: int | None = None, message_content: bool = True):
        intents = discord.Intents.default()
        intents.message_content = message_content
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    def _register_commands(self):
        netops = app_commands.Group(name="netops", description="NET-OPS team commands")

        @netops.command(name="status", description="Current team health summary")
        async def cmd_status(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                # Import and read the module-level state from main
                from .. import main as app_main
                report = app_main._latest_report
                if report is None:
                    status_text = (
                        "**NET-OPS Team Status**\n"
                        "Last poll: Never\n"
                        "No data available yet."
                    )
                else:
                    ts = report.timestamp.strftime("%Y-%m-%d %H:%M UTC") if report.timestamp else "unknown"
                    netclaw_ok = True  # Can't easily call async here; omit check
                    status_text = (
                        f"**NET-OPS Team Status**\n"
                        f"Last poll: {ts}\n"
                        f"Findings: {len(report.findings)} | Escalations: {report.escalations}\n"
                        f"Open issues: {report.open_issues}"
                    )
                await interaction.followup.send(status_text[:_MAX_MSG_LEN])
            except Exception as e:
                await interaction.followup.send(f"Error fetching status: {e}")

        @netops.command(name="report", description="Latest shift report summary")
        async def cmd_report(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                from .. import main as app_main
                report = app_main._latest_report
                text = _format_report(report)
                chunks = _chunk_message(text)
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            except Exception as e:
                await interaction.followup.send(f"Error fetching report: {e}")

        @netops.command(name="ask", description="Ask the net-ops team a question")
        @app_commands.describe(question="Your question for the net-ops team")
        async def cmd_ask(interaction: discord.Interaction, question: str):
            await interaction.response.defer()
            try:
                user_name = interaction.user.display_name
                answer = await supervisor.route_question(question, user_name)
                chunks = _chunk_message(answer)
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            except Exception as e:
                await interaction.followup.send(f"Error routing question: {e}")

        @netops.command(name="security", description="Run security expert analysis immediately")
        async def cmd_security(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                answer = await security_expert.answer_question(
                    "Run a full security analysis and provide your findings and recommendations."
                )
                chunks = _chunk_message(answer)
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            except Exception as e:
                await interaction.followup.send(f"Error running security analysis: {e}")

        @netops.command(name="interfaces", description="Run interface reconciliation check immediately")
        async def cmd_interfaces(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                answer = await interface_reconciler.answer_question(
                    "Run a full interface reconciliation check for all switches."
                )
                chunks = _chunk_message(answer)
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            except Exception as e:
                await interaction.followup.send(f"Error running interface reconciliation: {e}")

        self.tree.add_command(netops)

    async def setup_hook(self):
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Slash commands synced to guild %s", self.guild_id)
        else:
            await self.tree.sync()
            logger.info("Slash commands synced globally")

    async def on_ready(self):
        logger.info("Discord bot logged in as %s (id=%s)", self.user, self.user.id)

    async def on_message(self, message: discord.Message):
        # Ignore messages from the bot itself
        if message.author == self.user:
            return

        channel_id = settings.netops_channel_id
        should_respond = False

        if channel_id:
            # Only respond in the configured channel
            if message.channel.id == channel_id:
                should_respond = True
        else:
            # Respond to DMs or @mentions
            if isinstance(message.channel, discord.DMChannel):
                should_respond = True
            elif self.user in message.mentions:
                should_respond = True

        if not should_respond:
            return

        # Strip bot mention from the message content
        content = message.content
        if self.user.mention in content:
            content = content.replace(self.user.mention, "").strip()

        if not content:
            await message.channel.send("How can the net-ops team help you?")
            return

        try:
            async with message.channel.typing():
                user_name = message.author.display_name
                answer = await supervisor.route_question(content, user_name)

            chunks = _chunk_message(answer)
            for chunk in chunks:
                await message.channel.send(chunk)
        except Exception as e:
            logger.exception("Error handling Discord message")
            await message.channel.send(f"Error: {e}")


async def start_bot():
    if not settings.discord_bot_token:
        logger.info("DISCORD_BOT_TOKEN not set, bot disabled")
        return
    global _bot
    # Try with message_content intent first; fall back to slash-commands-only if not enabled in portal
    for message_content in (True, False):
        try:
            _bot = ConvergenceTeamBot(
                guild_id=settings.discord_guild_id or None,
                message_content=message_content,
            )
            await _bot.start(settings.discord_bot_token)
            return
        except discord.errors.PrivilegedIntentsRequired:
            if message_content:
                logger.warning(
                    "Message Content Intent not enabled in Discord developer portal — "
                    "falling back to slash-commands-only mode. "
                    "To enable free-form chat: discord.com/developers/applications → "
                    "your app → Bot → Privileged Gateway Intents → Message Content Intent → ON"
                )
                await _bot.close()
            else:
                raise
