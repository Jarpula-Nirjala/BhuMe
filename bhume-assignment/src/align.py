"""Boundary alignment: global shift, cross-correlation, edge refinement."""

from __future__ import annotations

import statistics

import numpy as np
from scipy import ndimage
from scipy.signal import correlate2d
from shapely.affinity import translate
from shapely.geometry.base import BaseGeometry

from bhume.baseline import _utm_for


def compute_global_shift(village) -> tuple[float, float]:
    """Use example truths to find median (dx, dy) in lon/lat degrees."""
    if village.example_truths is None:
        return 0.0, 0.0

    dxs: list[float] = []
    dys: list[float] = []
    for pn in village.example_truths.index:
        if pn not in village.plots.index:
            continue
        official = village.plots.loc[pn, "geometry"].centroid
        truth = village.example_truths.loc[pn, "geometry"].centroid
        dxs.append(truth.x - official.x)
        dys.append(truth.y - official.y)

    if not dxs:
        return 0.0, 0.0
    return statistics.median(dxs), statistics.median(dys)


def global_shift_meters(village) -> tuple[float, float]:
    """Median example-truth shift in UTM metres."""
    if village.example_truths is None:
        return 0.0, 0.0

    utm = _utm_for(village.example_truths.geometry.iloc[0])
    official_u = village.plots.to_crs(utm)
    truth_u = village.example_truths.to_crs(utm)
    dxs, dys = [], []
    for pn in village.example_truths.index:
        if pn in official_u.index:
            o = official_u.loc[pn, "geometry"].centroid
            t = truth_u.loc[pn, "geometry"].centroid
            dxs.append(t.x - o.x)
            dys.append(t.y - o.y)
    if not dxs:
        return 0.0, 0.0
    return statistics.median(dxs), statistics.median(dys)


def meters_to_degrees(meters: float, lat: float) -> tuple[float, float]:
    """Convert a distance in meters to (dlon, dlat) degrees at a given latitude."""
    import math

    dlat = meters / 111_320.0
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    dlon = meters / (111_320.0 * cos_lat)
    return dlon, dlat


def shift_geometry(geom: BaseGeometry, dx_deg: float, dy_deg: float) -> BaseGeometry:
    """Translate a shapely geometry by (dx, dy) in degrees."""
    return translate(geom, xoff=dx_deg, yoff=dy_deg)


def shift_geometry_utm(geom: BaseGeometry, dx_m: float, dy_m: float, utm_crs: str) -> BaseGeometry:
    """Translate geometry by metres in local UTM, return EPSG:4326 geometry."""
    import geopandas as gpd

    gs = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(utm_crs)
    shifted = gs.apply(lambda g: translate(g, dx_m, dy_m))
    return shifted.to_crs("EPSG:4326").iloc[0]


def _resize_to_match(arr: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    if arr.shape == shape:
        return arr
    from scipy.ndimage import zoom

    zy = shape[0] / arr.shape[0]
    zx = shape[1] / arr.shape[1]
    return zoom(arr, (zy, zx), order=1)


def _mask_outline(mask: np.ndarray) -> np.ndarray:
    m = mask.astype(bool)
    eroded = ndimage.binary_erosion(m)
    return (m & ~eroded).astype(np.float64)


def _downsample(arr: np.ndarray, max_dim: int = 96) -> tuple[np.ndarray, float]:
    """Downsample for fast correlation; return array and scale factor."""
    h, w = arr.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale >= 1.0:
        return arr, 1.0
    from scipy.ndimage import zoom

    order = 0 if arr.dtype == np.uint8 or arr.max() <= 1 else 1
    return zoom(arr, scale, order=order), scale


def outline_hint_score(hints: np.ndarray, template: np.ndarray, dy: int, dx: int) -> float:
    """Mean boundary-hint strength along the plot outline at a pixel offset."""
    ys, xs = np.where(template > 0)
    if ys.size == 0:
        return 0.0
    ys2 = ys + dy
    xs2 = xs + dx
    h, w = hints.shape
    valid = (ys2 >= 0) & (ys2 < h) & (xs2 >= 0) & (xs2 < w)
    if not valid.any():
        return 0.0
    return float(hints[ys2[valid], xs2[valid]].mean())


def cross_correlate_offset(
    plot_mask: np.ndarray,
    hint_patch: np.ndarray,
    search_px: int = 18,
) -> tuple[int, int, np.ndarray]:
    """Return (dy_px, dx_px) peak offset within ±search_px and correlation surface."""
    hints = _resize_to_match(hint_patch.astype(np.float64), plot_mask.shape)
    if np.nanmax(hints) > 1.0:
        hints = hints / 255.0
    hints = np.nan_to_num(hints, nan=0.0)

    template = _mask_outline(plot_mask)
    if template.sum() < 5 or hints.std() < 1e-6:
        return 0, 0, np.ones((1, 1), dtype=np.float64)

    template_s, scale = _downsample(template)
    hints_s, _ = _downsample(hints, max_dim=96)
    if template_s.shape != hints_s.shape:
        hints_s = _resize_to_match(hints_s, template_s.shape)

    corr = correlate2d(hints_s, template_s, mode="same")
    cy, cx = corr.shape[0] // 2, corr.shape[1] // 2
    search_s = max(2, int(search_px * scale))
    y0, y1 = max(0, cy - search_s), min(corr.shape[0], cy + search_s + 1)
    x0, x1 = max(0, cx - search_s), min(corr.shape[1], cx + search_s + 1)
    region = corr[y0:y1, x0:x1]
    peak = np.unravel_index(int(np.argmax(region)), region.shape)
    dy_px = int(round((peak[0] + y0 - cy) / scale))
    dx_px = int(round((peak[1] + x0 - cx) / scale))
    dy_px = max(-search_px, min(search_px, dy_px))
    dx_px = max(-search_px, min(search_px, dx_px))
    return dy_px, dx_px, corr


def refine_with_edge_detection(
    patch_rgb: np.ndarray,
    plot_mask: np.ndarray,
    search_px: int = 18,
) -> tuple[int, int, np.ndarray]:
    """Correlate plot outline with Sobel edges in the satellite patch."""
    from skimage.filters import sobel

    gray = patch_rgb.mean(axis=2).astype(np.float64)
    edges = sobel(gray)
    edges = ndimage.gaussian_filter(edges, sigma=1.0)
    if edges.max() > 0:
        edges = edges / edges.max()
    return cross_correlate_offset(plot_mask, edges, search_px=search_px)


def pixel_offset_to_lonlat(
    src,
    col: float,
    row: float,
    dx_px: int,
    dy_px: int,
) -> tuple[float, float]:
    """Convert pixel offset to lon/lat shift using imagery georeferencing."""
    from bhume.geo import pixel_to_lonlat

    lon0, lat0 = pixel_to_lonlat(src, col, row)
    lon1, lat1 = pixel_to_lonlat(src, col + dx_px, row + dy_px)
    return lon1 - lon0, lat1 - lat0
