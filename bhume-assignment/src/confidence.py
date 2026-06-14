"""Per-plot confidence scoring from multiple signals."""

from __future__ import annotations

import numpy as np
from rasterio.mask import mask
from shapely.geometry.base import BaseGeometry

from bhume.geo import geom_to_imagery_crs
from src.utils import largest_part


def boundary_strength_score(village, corrected_geom: BaseGeometry, boundaries_src) -> float:
    """Sample boundaries.tif under the corrected polygon, return mean [0,1]."""
    if boundaries_src is None:
        return 0.0
    try:
        geom_m = geom_to_imagery_crs(boundaries_src, largest_part(corrected_geom))
        out, _ = mask(boundaries_src, [geom_m], crop=True, nodata=np.nan)
        data = out[0].astype(np.float64)
        valid = data[~np.isnan(data)]
        if valid.size == 0:
            return 0.0
        mean_val = float(np.nanmean(valid))
        if mean_val <= 1.0:
            return float(np.clip(mean_val, 0.0, 1.0))
        return float(np.clip(mean_val / 255.0, 0.0, 1.0))
    except Exception:
        return 0.0


def area_ratio_score(map_area: float | None, recorded_area: float | None, pot_kharaba_ha: float | None) -> float:
    """Score how close map/recorded is to 1.0. Returns [0,1]."""
    if recorded_area is None or recorded_area <= 0 or map_area is None:
        return 0.35
    pot_sqm = (pot_kharaba_ha or 0.0) * 10_000.0
    total = recorded_area + pot_sqm
    if total <= 0:
        return 0.35
    ratio = map_area / total
    return float(np.clip(1.0 - abs(ratio - 1.0), 0.0, 1.0))


def correlation_sharpness(corr_surface: np.ndarray) -> float:
    """Ratio of peak to mean of cross-correlation surface. Normalize to [0,1]."""
    if corr_surface.size == 0:
        return 0.0
    peak = float(np.max(corr_surface))
    mean = float(np.mean(np.abs(corr_surface)))
    if mean < 1e-8:
        return 0.0
    ratio = peak / mean
    return float(np.clip((ratio - 1.0) / 8.0, 0.0, 1.0))


def shift_penalty(shift_meters: float, max_expected: float = 50.0) -> float:
    """Penalize implausibly large shifts. Returns [0,1]."""
    return float(np.clip(max(0.0, 1.0 - shift_meters / max_expected), 0.0, 1.0))


def combine_confidence(boundary: float, area: float, sharpness: float, shift: float) -> float:
    """Weighted combination → clipped to [0.05, 0.95]."""
    confidence = 0.35 * boundary + 0.25 * area + 0.30 * sharpness + 0.10 * shift
    return float(np.clip(confidence, 0.05, 0.95))
