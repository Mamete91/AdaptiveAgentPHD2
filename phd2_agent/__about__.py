"""
Identità del progetto Adaptive Agent for PHD2.

Modulo unico di branding: tutte le costanti di identità (nome, autore,
versione, copyright, canale di contatto) vivono qui. Banner d'avvio,
endpoint `/about`, footer dashboard, metadata `.exe`, copertina manuale e
header del config leggono tutti da queste costanti.

Aggiornare la versione qui significa aggiornarla ovunque. Non duplicare
stringhe hard-coded altrove nel codebase.
"""

from __future__ import annotations

# --- Identità progetto ------------------------------------------------------

__project_name__: str = "Adaptive Agent for PHD2"
__short_name__:   str = "Adaptive Agent"
__author__:       str = "Alessandro Curci"
__version__:      str = "2.15.1"
__version_tuple__: tuple[int, int, int, int] = (2, 15, 1, 0)  # major, minor, patch, build

# --- Licenza / copyright ----------------------------------------------------

__copyright__: str = "Copyright © 2026 Alessandro Curci"
__license__:   str = "BSD-3-Clause"

# --- Canale di contatto unico (community Telegram) --------------------------

__contact_telegram__: str = "https://t.me/+eewRNpvElSs5OWY8"

# Nessuna email: tutti i feedback transitano dal gruppo Telegram sopra.

# --- Helper -----------------------------------------------------------------

def banner_lines() -> list[str]:
    """Righe del banner d'avvio (loggate da main.py prima della connessione)."""
    bar = "=" * 60
    return [
        bar,
        f"{__project_name__} v{__version__}",
        f"by {__author__}",
        __copyright__,
        "Telegram:",
        __contact_telegram__,
        bar,
    ]


def about_payload() -> dict[str, str]:
    """Payload JSON per l'endpoint /about della dashboard."""
    return {
        "project_name":     __project_name__,
        "short_name":       __short_name__,
        "author":           __author__,
        "version":          __version__,
        "copyright":        __copyright__,
        "license":          __license__,
        "contact_telegram": __contact_telegram__,
    }
