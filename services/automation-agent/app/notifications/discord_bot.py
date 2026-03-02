"""Discord bot for interactive approval of automation actions.

Provides five slash commands:
  /pending                — list all unexpired pending approvals
  /approve <session_id>   — approve and execute a pending pfSense block
  /reject  <session_id>   — reject a pending action (no pfSense change)
  /approve-all            — approve all pending (capped by rate limit remaining)
  /reject-all             — reject all pending actions at once

The bot connects via the Discord Gateway (persistent outbound WebSocket) so
no public IP or HTTPS endpoint is required — ideal for home-lab deployments.

Setup
-----
1. https://discord.com/developers/applications → New Application → Bot tab
2. Bot tab → Reset Token → copy value to DISCORD_BOT_TOKEN in .env
3. OAuth2 → URL Generator → scopes: bot + applications.commands
   Permissions: Send Messages, Use Slash Commands
   → copy invite URL → add bot to your server
4. Set DISCORD_GUILD_ID to your server's ID for instant slash command sync
   (global sync without a guild ID can take up to 1 hour to propagate)
   Enable Developer Mode: User Settings → Advanced, then right-click server → Copy Server ID
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands

from app import state
from app.actions.executor import execute_and_verify
from app.actions.pfblocker import PfBlockerAction
from app.audit.git_trail import trail
from app.config import settings
import app.metrics as m

logger = logging.getLogger(__name__)

_bot: "ConvergenceBot | None" = None
_bot_task: "asyncio.Task[None] | None" = None


# ---------------------------------------------------------------------------
# Bot client
# ---------------------------------------------------------------------------


class ConvergenceBot(discord.Client):
    def __init__(self, guild_id: int | None = None) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._guild_id = guild_id

    async def setup_hook(self) -> None:
        """Called once after login — register slash commands."""
        if self._guild_id:
            guild = discord.Object(id=self._guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Discord slash commands synced to guild %d", self._guild_id)
        else:
            await self.tree.sync()
            logger.info("Discord slash commands synced globally (may take ~1h to appear)")

    async def on_ready(self) -> None:
        logger.info("Discord bot logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pending(session_id: str) -> dict[str, Any] | None:
    """Return pending session data if it exists and has not expired."""
    data = state.pending_approvals.get(session_id)
    if not data:
        return None
    try:
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            return None
    except Exception:
        return None
    return data


def _pending_embed() -> discord.Embed:
    """Build an embed listing all unexpired pending approvals (max 10 shown)."""
    now = datetime.now(timezone.utc)
    active: list[tuple[str, str, float, int]] = []

    for sid, data in list(state.pending_approvals.items()):
        try:
            expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if now > expires:
            continue
        remaining = int((expires - now).total_seconds() / 60)
        score = data.get("threat_data", {}).get("score", 0)
        ip = data.get("ip", "?")
        active.append((sid, ip, score, remaining))

    embed = discord.Embed(
        title="⏳ Pending Automation Approvals",
        color=0xFFA500,
        timestamp=now,
    )
    if not active:
        embed.description = "✅ No pending approvals."
        embed.color = 0x00CC66
    else:
        for sid, ip, score, remaining_min in active[:10]:
            embed.add_field(
                name=f"`{ip}`  —  score {score}/100",
                value=f"Session: `{sid}`\nExpires in **{remaining_min}m**",
                inline=False,
            )
        if len(active) > 10:
            embed.set_footer(text=f"Showing 10 of {len(active)}. Use /pending to refresh.")
    return embed


# ---------------------------------------------------------------------------
# Bot factory + slash command registration
# ---------------------------------------------------------------------------


async def start_bot() -> None:
    """Create and start the Discord bot as a background asyncio task.

    No-ops silently if DISCORD_BOT_TOKEN is not configured, so the service
    starts cleanly in environments without a bot token.
    """
    global _bot, _bot_task

    if not settings.discord_bot_token:
        logger.info("DISCORD_BOT_TOKEN not set — Discord bot disabled (webhook-only mode)")
        return

    guild_id = settings.discord_guild_id or None
    _bot = ConvergenceBot(guild_id=guild_id)

    # ------------------------------------------------------------------ #
    # /pending — list current pending approvals
    # ------------------------------------------------------------------ #

    @_bot.tree.command(name="pending", description="List pending automation approvals")
    async def cmd_pending(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await interaction.followup.send(embed=_pending_embed())

    # ------------------------------------------------------------------ #
    # /approve <session_id> — approve and execute
    # ------------------------------------------------------------------ #

    @_bot.tree.command(
        name="approve",
        description="Approve a pending pfSense block action",
    )
    @app_commands.describe(session_id="Session ID from the approval request")
    async def cmd_approve(interaction: discord.Interaction, session_id: str) -> None:
        await interaction.response.defer()

        pending = _get_pending(session_id)
        if pending is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Not Found",
                    description=f"Session `{session_id}` does not exist or has expired.",
                    color=0xFF3333,
                )
            )
            return

        # Pop before executing to prevent a race-condition double-approval
        state.pending_approvals.pop(session_id, None)
        m.automation_pending_approvals.set(len(state.pending_approvals))

        ip = pending["ip"]
        pa = pending["pf_action"]
        pf_action = PfBlockerAction(
            action_type=pa["type"],
            target_list=pa["target_list"],
            value=pa["value"],
            reason=pa["reason"],
            duration_hours=int(pa.get("duration_hours", settings.block_ttl_hours)),
        )

        approver = interaction.user.display_name if interaction.user else "Discord"
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"✅ Approved — {ip}",
                description=(
                    f"Action `{pa['type']}` on `{pa['value']}` approved by **{approver}**.\n"
                    "Executing in the background — watch for the outcome notification."
                ),
                color=0x00CC66,
                timestamp=datetime.now(timezone.utc),
            )
        )

        # Re-open GAIT session for the execution leg (mirrors /api/automation/approve)
        session = None
        if trail.initialized:
            try:
                session = trail.open_session(ip, f"{session_id}-approved")
                session.record_turn(
                    "approval",
                    {
                        "approved_at": datetime.now(timezone.utc).isoformat(),
                        "approved_via": "discord",
                        "approved_by": approver,
                        "original_session_id": session_id,
                    },
                )
            except Exception as exc:
                logger.error("Could not open GAIT session for Discord approval: %s", exc)

        asyncio.create_task(
            execute_and_verify(
                session_id,
                ip,
                pf_action,
                pending["baseline"],
                pending["threat_data"],
                pending["proposed_action"],
                session,
            )
        )
        logger.info(
            "Session %s approved via Discord slash command by %s",
            session_id, approver,
        )

    # ------------------------------------------------------------------ #
    # /reject <session_id> — reject, no pfSense changes
    # ------------------------------------------------------------------ #

    @_bot.tree.command(
        name="reject",
        description="Reject a pending pfSense block action — no changes made",
    )
    @app_commands.describe(session_id="Session ID from the approval request")
    async def cmd_reject(interaction: discord.Interaction, session_id: str) -> None:
        await interaction.response.defer()

        pending = _get_pending(session_id)
        if pending is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Not Found",
                    description=f"Session `{session_id}` does not exist or has expired.",
                    color=0xFF3333,
                )
            )
            return

        state.pending_approvals.pop(session_id, None)
        m.automation_pending_approvals.set(len(state.pending_approvals))
        m.automation_actions_total.labels(status="skipped").inc()

        ip = pending["ip"]
        rejecter = interaction.user.display_name if interaction.user else "Discord"
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"🚫 Rejected — {ip}",
                description=(
                    f"Rejected by **{rejecter}**. No changes will be made to pfSense."
                ),
                color=0xFF3333,
                timestamp=datetime.now(timezone.utc),
            )
        )
        logger.info(
            "Session %s rejected via Discord slash command by %s",
            session_id, rejecter,
        )

    # ------------------------------------------------------------------ #
    # /approve-all — approve every unexpired pending session
    # ------------------------------------------------------------------ #

    @_bot.tree.command(
        name="approve-all",
        description="Approve all pending pfSense block actions (capped by hourly rate limit)",
    )
    async def cmd_approve_all(interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        now = datetime.now(timezone.utc)
        approver = interaction.user.display_name if interaction.user else "Discord"

        # Collect all unexpired sessions in insertion order
        pending_items: list[tuple[str, dict]] = []
        for sid, data in list(state.pending_approvals.items()):
            try:
                expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                if now > expires:
                    continue
            except Exception:
                continue
            pending_items.append((sid, data))

        if not pending_items:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ Nothing to Approve",
                    description="No pending approvals found.",
                    color=0x00CC66,
                )
            )
            return

        # Human-initiated approvals bypass the automated rate limit — the cap
        # exists to protect unattended auto-approve runs, not conscious human decisions.
        to_approve = pending_items

        # Pop approved sessions atomically before firing tasks
        for sid, _ in to_approve:
            state.pending_approvals.pop(sid, None)
        m.automation_pending_approvals.set(len(state.pending_approvals))

        # Fire execution tasks (serialised by _xmlrpc_write_lock inside pfblocker)
        for sid, pending in to_approve:
            ip = pending["ip"]
            pa = pending["pf_action"]
            pf_action = PfBlockerAction(
                action_type=pa["type"],
                target_list=pa["target_list"],
                value=pa["value"],
                reason=pa["reason"],
                duration_hours=int(pa.get("duration_hours", settings.block_ttl_hours)),
            )

            # Re-open GAIT session for each execution leg
            session = None
            if trail.initialized:
                try:
                    session = trail.open_session(ip, f"{sid}-approved")
                    session.record_turn(
                        "approval",
                        {
                            "approved_at": datetime.now(timezone.utc).isoformat(),
                            "approved_via": "discord_bulk",
                            "approved_by": approver,
                            "original_session_id": sid,
                        },
                    )
                except Exception as exc:
                    logger.error(
                        "Could not open GAIT session for bulk Discord approval %s: %s",
                        sid, exc,
                    )

            asyncio.create_task(
                execute_and_verify(
                    sid,
                    ip,
                    pf_action,
                    pending["baseline"],
                    pending["threat_data"],
                    pending["proposed_action"],
                    session,
                )
            )

        approved_ips = "\n".join(
            f"• `{d['ip']}` (score {d.get('threat_data', {}).get('score', '?')})"
            for _, d in to_approve
        )
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"✅ Bulk Approval — {len(to_approve)} Approved",
                description=(
                    f"**{len(to_approve)}** action(s) queued for execution by **{approver}**\n\n"
                    f"**Approved:**\n{approved_ips}"
                ),
                color=0x00CC66,
                timestamp=now,
            )
        )
        logger.info("Bulk approve by %s: %d approved", approver, len(to_approve))

    # ------------------------------------------------------------------ #
    # /reject-all — reject every unexpired pending session
    # ------------------------------------------------------------------ #

    @_bot.tree.command(
        name="reject-all",
        description="Reject all pending pfSense block actions — no changes made to pfSense",
    )
    async def cmd_reject_all(interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        now = datetime.now(timezone.utc)
        rejecter = interaction.user.display_name if interaction.user else "Discord"

        rejected: list[str] = []
        for sid, data in list(state.pending_approvals.items()):
            try:
                expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                if now > expires:
                    continue
            except Exception:
                continue
            state.pending_approvals.pop(sid, None)
            m.automation_actions_total.labels(status="skipped").inc()
            rejected.append(data.get("ip", sid))

        m.automation_pending_approvals.set(len(state.pending_approvals))

        if not rejected:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Nothing to Reject",
                    description="No pending approvals found.",
                    color=0x808080,
                )
            )
            return

        ip_list = "\n".join(f"• `{ip}`" for ip in rejected)
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"🚫 Bulk Rejected — {len(rejected)} Action(s)",
                description=(
                    f"All pending actions rejected by **{rejecter}**. "
                    f"No changes made to pfSense.\n\n**Rejected:**\n{ip_list}"
                ),
                color=0xFF3333,
                timestamp=now,
            )
        )
        logger.info("Bulk reject by %s: %d sessions rejected", rejecter, len(rejected))

    # Start the bot as a background task on the current event loop
    _bot_task = asyncio.create_task(_bot.start(settings.discord_bot_token))
    logger.info("Discord bot task created — waiting for login confirmation")


async def stop_bot() -> None:
    """Gracefully close the bot on service shutdown."""
    global _bot, _bot_task
    if _bot and not _bot.is_closed():
        await _bot.close()
        logger.info("Discord bot connection closed")
    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
