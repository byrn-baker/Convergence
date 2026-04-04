from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class AgentRole(str, Enum):
    NOC_OFFICER = "NOC_OFFICER"
    NETWORK_ENGINEER = "NETWORK_ENGINEER"
    SECURITY_ENGINEER = "SECURITY_ENGINEER"
    SECURITY_EXPERT = "SECURITY_EXPERT"
    NAS_ENGINEER = "NAS_ENGINEER"
    CCIE_ARCHITECT = "CCIE_ARCHITECT"
    INTERFACE_RECONCILER = "INTERFACE_RECONCILER"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Finding(BaseModel):
    role: AgentRole
    severity: Severity
    device: str
    summary: str
    details: str
    timestamp: datetime = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            from datetime import timezone
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc))


class ShiftReport(BaseModel):
    timestamp: datetime
    findings: List[Finding]
    open_issues: int
    escalations: int


class TeamStatus(BaseModel):
    last_poll: Optional[datetime]
    findings_count: int
    active_escalations: int
    netclaw_available: bool
