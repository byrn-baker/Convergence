"""Pydantic response models for /api/report."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class IntelRecord(BaseModel):
    country: str = ""
    org: str = ""
    classification: str = "unknown"
    composite_score: float = 0.0
    abuseipdb_score: float = 0.0
    otx_pulse_count: int = 0
    greynoise_classification: str = "unknown"
    greynoise_name: str = ""
    is_riot: bool = False
    is_known_bad_actor: bool = False
    threat_level: str = "none"


class IPEntry(BaseModel):
    ip: str
    count: int
    direction: str
    action: str
    intel: IntelRecord = IntelRecord()


class PortEntry(BaseModel):
    port: str
    service: str
    risk_level: str
    count: int
    description: str = ""


class PortAnalysis(BaseModel):
    top_blocked_ports: list[PortEntry] = []
    critical_ports_hit: list[PortEntry] = []


class NarrativeSection(BaseModel):
    available: bool = False
    model: str = ""
    risk_level: str = "unknown"
    executive_summary: str = ""
    top_threats: list[str] = []
    inbound_analysis: str = ""
    outbound_analysis: str = ""
    port_analysis: str = ""
    recommended_actions: list[str] = []


class ReportSummary(BaseModel):
    total_blocked_ips: int = 0
    known_bad_actors_inbound: int = 0
    known_bad_actors_outbound: int = 0
    critical_ports_targeted: int = 0
    overall_risk_level: str = "none"


class ThreatReport(BaseModel):
    generated_at: str
    lookback_hours: int
    summary: ReportSummary = ReportSummary()
    narrative: NarrativeSection = NarrativeSection()
    blocked_ips: list[IPEntry] = []
    outbound_ips: list[IPEntry] = []
    port_analysis: PortAnalysis = PortAnalysis()
