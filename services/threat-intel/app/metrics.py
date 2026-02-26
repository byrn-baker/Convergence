"""Prometheus metrics definitions for the threat-intel service."""
from prometheus_client import Gauge, Counter, CollectorRegistry, REGISTRY

# Use the default registry so /metrics exposes everything automatically.

threat_intel_ip_score = Gauge(
    "threat_intel_ip_score",
    "Composite threat score 0-100 for an IP",
    ["ip", "direction", "country", "org", "classification"],
)

threat_intel_ip_event_count = Gauge(
    "threat_intel_ip_event_count",
    "Firewall event count seen for an IP",
    ["ip", "direction", "action"],
)

threat_intel_abuseipdb_score = Gauge(
    "threat_intel_abuseipdb_score",
    "AbuseIPDB confidence score 0-100",
    ["ip", "direction"],
)

threat_intel_otx_pulses = Gauge(
    "threat_intel_otx_pulses",
    "Number of OTX threat pulses referencing this IP",
    ["ip", "direction"],
)

threat_intel_greynoise_classification = Gauge(
    "threat_intel_greynoise_classification",
    "GreyNoise classification: 2=malicious 1=unknown 0=benign -1=riot",
    ["ip", "direction"],
)

threat_intel_known_bad_actor = Gauge(
    "threat_intel_known_bad_actor",
    "1 if IP is flagged as a known bad actor, 0 otherwise",
    ["ip", "direction", "country"],
)

threat_intel_port_event_count = Gauge(
    "threat_intel_port_event_count",
    "Number of blocked events targeting a given destination port",
    ["port", "port_service", "risk_level"],
)

threat_intel_enrichment_last_success_timestamp = Gauge(
    "threat_intel_enrichment_last_success_timestamp",
    "Unix timestamp of the last successful enrichment run",
)

threat_intel_enrichment_ips_processed_total = Gauge(
    "threat_intel_enrichment_ips_processed_total",
    "Total number of IPs processed in the last enrichment run",
)

threat_intel_cache_hits_total = Counter(
    "threat_intel_cache_hits_total",
    "Cumulative Redis cache hits",
)
