"""FastAPI application — /health, /metrics, /api/report endpoints."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app import state
from app.scheduler import start_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield


app = FastAPI(
    title="Convergence Threat Intelligence",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "report_available": bool(state.latest_report)}


@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/api/report")
async def report():
    if not state.latest_report:
        return JSONResponse({"error": "No report available yet"}, status_code=503)
    return state.latest_report


@app.get("/api/report/blocked")
async def report_blocked():
    if not state.latest_report:
        return JSONResponse({"error": "No report available yet"}, status_code=503)
    return {
        "generated_at": state.latest_report.get("generated_at"),
        "blocked_ips": state.latest_report.get("blocked_ips", []),
    }


@app.get("/api/report/outbound")
async def report_outbound():
    if not state.latest_report:
        return JSONResponse({"error": "No report available yet"}, status_code=503)
    return {
        "generated_at": state.latest_report.get("generated_at"),
        "outbound_ips": state.latest_report.get("outbound_ips", []),
    }


# ---------------------------------------------------------------------------
# Infinity-friendly endpoints — return arrays so the Infinity datasource
# backend proxy can process them without needing root_is_not_array support.
# ---------------------------------------------------------------------------

@app.get("/api/infinity/summary")
async def infinity_summary():
    """Return summary + generated_at as a 1-row array for Infinity stat panels."""
    if not state.latest_report:
        return [{}]
    s = state.latest_report.get("summary", {})
    return [{
        "overall_risk_level": s.get("overall_risk_level", "unknown"),
        "known_bad_actors_inbound": s.get("known_bad_actors_inbound", 0),
        "known_bad_actors_outbound": s.get("known_bad_actors_outbound", 0),
        "critical_ports_targeted": s.get("critical_ports_targeted", 0),
        "total_blocked_ips": s.get("total_blocked_ips", 0),
        "generated_at": state.latest_report.get("generated_at", ""),
    }]


@app.get("/api/infinity/narrative")
async def infinity_narrative():
    """Return narrative as a 1-row array for Infinity table panels."""
    if not state.latest_report:
        return [{}]
    n = state.latest_report.get("narrative", {})
    return [{
        "executive_summary": n.get("executive_summary", "No narrative available."),
        "risk_level": n.get("risk_level", "unknown"),
        "model": n.get("model", ""),
        "inbound_analysis": n.get("inbound_analysis", ""),
        "outbound_analysis": n.get("outbound_analysis", ""),
        "port_analysis": n.get("port_analysis", ""),
    }]


@app.get("/api/infinity/threats")
async def infinity_threats():
    """Return top_threats as an array of objects for Infinity table panels."""
    if not state.latest_report:
        return []
    threats = state.latest_report.get("narrative", {}).get("top_threats", [])
    return [{"threat": t} for t in threats]


@app.get("/api/infinity/actions")
async def infinity_actions():
    """Return recommended_actions as an array of objects for Infinity table panels."""
    if not state.latest_report:
        return []
    actions = state.latest_report.get("narrative", {}).get("recommended_actions", [])
    return [{"action": a} for a in actions]


@app.get("/api/infinity/outbound_suspicious")
async def infinity_outbound_suspicious():
    """Return suspicious outbound destinations as a flat array for Infinity table panels.

    Flattens intel.* nested fields so Infinity backend proxy can read them directly.
    Pre-filtered: only is_known_bad_actor=True entries.
    """
    if not state.latest_report:
        return []
    rows = []
    for e in state.latest_report.get("outbound_ips", []):
        intel = e.get("intel", {})
        if not intel.get("is_known_bad_actor"):
            continue
        src_ips = e.get("src_ips", [])
        # pfSense NAT hides the true internal source; src_ip from VM is the WAN IP
        from app.analysis.vm_client import _is_rfc1918 as _rfc
        internal = [ip for ip in src_ips if _rfc(ip)]
        wan_ips = [ip for ip in src_ips if not _rfc(ip)]
        if internal:
            src_label = ", ".join(internal)
        elif wan_ips:
            src_label = f"pfSense NAT ({wan_ips[0]})"
        else:
            src_label = "Check pfSense States"
        rows.append({
            "ip": e["ip"],
            "events": e["count"],
            "org": intel.get("org", ""),
            "country": intel.get("country", "US"),
            "score": intel.get("composite_score", 0),
            "threat_level": intel.get("threat_level", "none"),
            "abuse_score": intel.get("abuse_confidence_score", 0),
            "otx_pulses": intel.get("pulse_count", 0),
            "greynoise": intel.get("gn_classification", "unknown"),
            "source": src_label,
        })
    return rows


@app.get("/api/infinity/outbound_all")
async def infinity_outbound_all():
    """Return ALL outbound destinations as a flat array for Infinity table panels."""
    if not state.latest_report:
        return []
    rows = []
    for e in state.latest_report.get("outbound_ips", []):
        intel = e.get("intel", {})
        src_ips = e.get("src_ips", [])
        rows.append({
            "ip": e["ip"],
            "events": e["count"],
            "org": intel.get("org", ""),
            "country": intel.get("country", "US"),
            "score": intel.get("composite_score", 0),
            "threat_level": intel.get("threat_level", "none"),
            "abuse_score": intel.get("abuse_confidence_score", 0),
            "otx_pulses": intel.get("pulse_count", 0),
            "greynoise": intel.get("gn_classification", "unknown"),
            "is_known_bad_actor": intel.get("is_known_bad_actor", False),
            "internal_sources": ", ".join(src_ips) if src_ips else "Check pfSense States",
        })
    return rows


@app.get("/api/infinity/ports")
async def infinity_ports():
    """Return top blocked ports as a flat array for Infinity table panels."""
    if not state.latest_report:
        return []
    return state.latest_report.get("port_analysis", {}).get("top_blocked_ports", [])


@app.get("/api/infinity/critical_ports")
async def infinity_critical_ports():
    """Return critical-risk blocked ports as a flat array."""
    if not state.latest_report:
        return []
    return state.latest_report.get("port_analysis", {}).get("critical_ports_hit", [])


@app.get("/api/infinity/blocked_ips")
async def infinity_blocked_ips():
    """Return blocked IPs as a flat array for Infinity table panels."""
    if not state.latest_report:
        return []
    rows = []
    for e in state.latest_report.get("blocked_ips", []):
        intel = e.get("intel", {})
        rows.append({
            "ip": e["ip"],
            "events": e["count"],
            "org": intel.get("org", ""),
            "country": intel.get("country", ""),
            "score": intel.get("composite_score", 0),
            "threat_level": intel.get("threat_level", "none"),
            "abuse_score": intel.get("abuse_confidence_score", 0),
            "otx_pulses": intel.get("pulse_count", 0),
            "greynoise": intel.get("gn_classification", "unknown"),
            "is_known_bad_actor": intel.get("is_known_bad_actor", False),
        })
    return rows
