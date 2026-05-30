"""
Adaptive Agent for PHD2 — package root.

Identità progetto (nome, versione, autore, copyright, contatti) centralizzata
in `phd2_agent/__about__.py`. Le costanti sono ri-esportate qui per comodità.
"""
from .__about__ import (
    __project_name__,
    __short_name__,
    __author__,
    __version__,
    __copyright__,
    __contact_telegram__,
)
from .client import PHD2Client
from .analyzer import StatisticsAnalyzer
from .controller import AdaptiveController

__all__ = [
    "PHD2Client",
    "StatisticsAnalyzer",
    "AdaptiveController",
    "__project_name__",
    "__short_name__",
    "__author__",
    "__version__",
    "__copyright__",
    "__contact_telegram__",
]
