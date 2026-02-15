"""
Convergence - A Unified Network Observability Platform

This package provides a comprehensive multi-vendor network observability solution
that unifies telemetry collection from Cisco, Juniper, and Arista hardware.
"""

__version__ = "0.1.0"
__author__ = "Convergence Team"
__license__ = "MIT"

from loguru import logger

# Configure default logger
logger.add(
    "logs/convergence.log",
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
)
