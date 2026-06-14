"""Shared helpers for plot correction pipeline."""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio import features
from rasterio.windows import from_bounds
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from bhume.geo import Patch, geom_to_imagery_crs


def largest_part(geom: BaseGeometry) -> BaseGeometry:
    """Return the largest polygon if geometry is a MultiPolygon."""
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area)
    return geom


def patch_for_hints(src, geom_4326: BaseGeometry, pad_m: float = 30.0) -> tuple[np.ndarray, object]:
    """Read single-band boundary-hint crop aligned with imagery patches."""
    g = geom_to_imagery_crs(src, geom_4326)
    minx, miny, maxx, maxy = g.bounds
    left, bottom, right, top = minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m
    dl, db, dr, dt = src.bounds
    left, bottom, right, top = max(left, dl), max(bottom, db), min(right, dr), min(top, dt)
    if right <= left or top <= bottom:
        raise ValueError("plot bounding box does not overlap the hints extent")
    window = from_bounds(left, bottom, right, top, transform=src.transform)
    hints = src.read(1, window=window).astype(np.float32)
    transform = src.window_transform(window)
    return hints, transform


def rasterize_plot_mask(src, geom_4326: BaseGeometry, transform, shape: tuple[int, int]) -> np.ndarray:
    """Rasterize plot geometry into a binary mask for the given patch grid."""
    geom_m = geom_to_imagery_crs(src, largest_part(geom_4326))
    mask = features.rasterize(
        [(geom_m, 1)],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    return mask


def patch_is_invalid(patch: Patch | np.ndarray) -> bool:
    """True when imagery patch is empty or entirely black."""
    image = patch.image if isinstance(patch, Patch) else patch
    if image.size == 0:
        return True
    return bool(np.all(image == 0))


def area_ratio(map_area: float | None, recorded_area: float | None, pot_kharaba_ha: float | None) -> float | None:
    """Map area divided by total recorded area (cultivable + pot-kharaba)."""
    if map_area is None or recorded_area is None or recorded_area <= 0:
        return None
    pot_sqm = (pot_kharaba_ha or 0.0) * 10_000.0
    total = recorded_area + pot_sqm
    if total <= 0:
        return None
    return float(map_area) / total


def is_area_problem(ratio: float | None) -> bool:
    if ratio is None:
        return False
    return ratio < 0.3 or ratio > 3.0


def is_placement_candidate(ratio: float | None) -> bool:
    if ratio is None:
        return True
    return 0.5 <= ratio <= 2.0


def shift_meters(geom_a: BaseGeometry, geom_b: BaseGeometry, utm_crs: str) -> float:
    """Centroid shift between two geometries in metres."""
    import geopandas as gpd

    ga = gpd.GeoSeries([geom_a], crs="EPSG:4326").to_crs(utm_crs).iloc[0]
    gb = gpd.GeoSeries([geom_b], crs="EPSG:4326").to_crs(utm_crs).iloc[0]
    return float(ga.centroid.distance(gb.centroid))


def utm_crs_for(geom: BaseGeometry) -> str:
    lon = geom.centroid.x
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"
