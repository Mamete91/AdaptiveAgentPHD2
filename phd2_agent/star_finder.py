"""
star_finder.py - analisi centroide/saturazione su frame salvato.

§75: NON e' piu' il vecchio "AI Star Finder" per le emergenze StarLost
(quel ramo e' stato rimosso: la selezione della stella di guida e'
competenza di PHD2). Resta VIVO come strumento del Path B, che lo usa
per riselezionare una stella NON satura quando l'esposizione cambia -
compito diverso, e che PHD2 da solo non copre.

Localizza il blob piu' consistente in un FITS PHD2 anche se la stella e'
satura (palloni bianchi) che PHD2 normalmente scarterebbe.

Output: (cx, cy, info) dove info include peak_adu, is_saturated, blob_size.
La saturation flag viene usata dal controller per attivare il timer 300s
e per emettere warning di "Elongation Bias" sulla dashboard.
"""
from __future__ import annotations

import logging

import numpy as np
import scipy.ndimage as ndi

log = logging.getLogger(__name__)

# Soglia saturazione per camere 16-bit (ZWO ASI120, ASI174, ASI290 mini, ecc.).
# Ridotta a 60000 invece del massimo teorico 65535 per gestire margine di
# sicurezza: anche le camere 12-bit espanse a 16-bit hanno saturazione reale
# attorno a 60k ADU.
SATURATION_THRESHOLD_ADU = 60000


def parse_simple_fits(filepath: str) -> np.ndarray:
    """Legge l'header ASCII FITS in Python puro estraendo l'immagine."""
    with open(filepath, "rb") as f:
        width = None
        height = None
        bitpix = None
        bzero = 0  # offset standard FITS per int16 firmato -> uint16

        while True:
            chunk = f.read(2880)
            if not chunk:
                raise ValueError("Fine file raggiunta prima della fine header")

            lines = [chunk[i:i + 80].decode("ascii", errors="ignore")
                     for i in range(0, 2880, 80)]
            for line in lines:
                if line.startswith("BITPIX "):
                    try:
                        bitpix = int(line[line.find("=") + 1:line.find("/")
                                          if "/" in line else len(line)].strip())
                    except Exception:
                        bitpix = int(line[8:30].strip())
                elif line.startswith("NAXIS1 "):
                    try:
                        width = int(line[line.find("=") + 1:line.find("/")
                                         if "/" in line else len(line)].strip())
                    except Exception:
                        width = int(line[8:30].strip())
                elif line.startswith("NAXIS2 "):
                    try:
                        height = int(line[line.find("=") + 1:line.find("/")
                                          if "/" in line else len(line)].strip())
                    except Exception:
                        height = int(line[8:30].strip())
                elif line.startswith("BZERO "):
                    try:
                        bzero = int(float(line[line.find("=") + 1:line.find("/")
                                               if "/" in line else len(line)].strip()))
                    except Exception:
                        bzero = 0

            if any(line.strip() == "END" or line.startswith("END ") for line in lines):
                break

        if width is None or height is None or bitpix is None:
            raise ValueError(
                f"Dati mancanti header FITS: {width}x{height} bitpix:{bitpix}"
            )

        if bitpix == 16:
            # FITS standard: BITPIX=16 = int16 firmato + BZERO=32768 -> uint16
            if bzero >= 32768:
                dtype = ">i2"
                signed = True
            else:
                dtype = ">u2"
                signed = False
        elif bitpix == 8:
            dtype = "u1"
            signed = False
        elif bitpix == -32:
            dtype = ">f4"
            signed = False
        else:
            raise ValueError(f"BITPIX {bitpix} non supportato")

        payload = f.read()
        expected = height * width * np.dtype(dtype).itemsize
        if len(payload) < expected:
            raise ValueError(f"Incomplete payload: {len(payload)} < {expected}")

        data = np.frombuffer(payload[:expected], dtype=dtype)
        data = data.reshape((height, width))

        if bitpix == 16 and signed:
            data = data.astype(np.int32) + bzero
            data = np.clip(data, 0, 65535).astype(np.uint16)

        return data


def find_best_star(filepath: str,
                   prefer_unsaturated: bool = False) -> tuple[float | None, float | None, dict]:
    """
    Trova la stella migliore in un FITS PHD2.

    Args:
        prefer_unsaturated: §35 — se True scarta i blob saturi (peak >= soglia) e
            ritorna la migliore stella NON satura (None,None se non ce ne sono).
            Usato dalla riselezione Path B per evitare la stella che satura al nuovo tempo.

    Returns:
        (cx, cy, info_dict) con:
            cx, cy : coordinate centroide (None se nessun blob valido)
            info_dict : peak_adu, is_saturated, blob_size_px, num_blobs
    """
    info = {
        "peak_adu": 0,
        "is_saturated": False,
        "blob_size_px": 0,
        "num_blobs": 0,
    }

    try:
        data = parse_simple_fits(filepath)
        raw_data = data.copy()
        data = data.astype(float)

        back = np.median(data)
        data = data - back
        data[data < 0] = 0

        smoothed = ndi.gaussian_filter(data, sigma=1.2)
        threshold = np.percentile(smoothed, 99.8)
        if threshold <= 0:
            return None, None, info

        mask = smoothed > threshold
        labeled_array, num_features = ndi.label(mask)
        info["num_blobs"] = int(num_features)

        if num_features == 0:
            return None, None, info

        best_sum = 0
        best_cy: float | None = None
        best_cx: float | None = None
        best_blob_idx: int | None = None

        for i in range(1, num_features + 1):
            comp_mask = labeled_array == i
            if np.sum(comp_mask) < 3:
                continue

            # §35 — se richiesto, scarta i blob saturi: vogliamo la migliore stella
            # NON satura (peak sotto soglia), anche se piu' debole di una satura.
            if prefer_unsaturated and int(np.max(raw_data[comp_mask])) >= SATURATION_THRESHOLD_ADU:
                continue

            intensity = np.sum(data[comp_mask])
            if intensity > best_sum:
                best_sum = intensity
                cy, cx = ndi.center_of_mass(data, labels=labeled_array, index=i)
                best_cy, best_cx = cy, cx
                best_blob_idx = i

        if best_cx is not None and best_cy is not None and best_blob_idx is not None:
            best_mask = labeled_array == best_blob_idx
            peak_adu = int(np.max(raw_data[best_mask]))
            blob_size = int(np.sum(best_mask))
            info["peak_adu"] = peak_adu
            info["is_saturated"] = peak_adu >= SATURATION_THRESHOLD_ADU
            info["blob_size_px"] = blob_size

            # Mitigazione bias centroide su stelle sature:
            # usiamo il centroide geometrico dei pixel saturi (piu' robusto)
            if info["is_saturated"]:
                sat_mask = (raw_data >= SATURATION_THRESHOLD_ADU) & best_mask
                if np.sum(sat_mask) >= 3:
                    ys, xs = np.where(sat_mask)
                    best_cy = float(np.median(ys))
                    best_cx = float(np.median(xs))

            return float(best_cx), float(best_cy), info

        return None, None, info

    except Exception as e:
        log.error("Errore nell'analisi blob visivo FITS: %s", e)
        return None, None, info
