"""Raster + CRS helpers.

The plots are EPSG:4326 (lon/lat); the imagery is EPSG:3857 (web-mercator metres). These
functions hide that mismatch so you can think in lon/lat and pixels, not projections.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform


@dataclass
class Patch:
    """An image crop around a plot.

    `image` is (H, W, 3) uint8 RGB. `transform` maps pixel (col, row) → imagery-CRS (x, y);
    `bounds` is (left, bottom, right, top) in the imagery CRS. Use `bhume.geo.pixel_to_lonlat`
    with the source dataset to go back to lon/lat.
    """

    image: np.ndarray
    transform: object
    crs: str
    bounds: tuple[float, float, float, float]


def open_imagery(path):
    """Open the imagery GeoTIFF (a rasterio dataset). Use as a context manager:
    `with open_imagery(village.imagery_path) as src: ...`."""
    return rasterio.open(path)


def _to_imagery_crs(src):
    return Transformer.from_crs('EPSG:4326', src.crs, always_xy=True)


def _to_lonlat_crs(src):
    return Transformer.from_crs(src.crs, 'EPSG:4326', always_xy=True)


def lonlat_to_pixel(src, lon: float, lat: float) -> tuple[int, int]:
    """Map a lon/lat point to (col, row) pixel coordinates in the imagery."""
    x, y = _to_imagery_crs(src).transform(lon, lat)
    row, col = src.index(x, y)
    return int(col), int(row)


def pixel_to_lonlat(src, col: float, row: float) -> tuple[float, float]:
    """Map a (col, row) pixel back to (lon, lat). Pixel centres."""
    x, y = src.xy(row, col)
    lon, lat = _to_lonlat_crs(src).transform(x, y)
    return float(lon), float(lat)


def geom_to_imagery_crs(src, geom_4326: BaseGeometry) -> BaseGeometry:
    """Reproject a lon/lat geometry into the imagery CRS (for overlaying / measuring in pixels)."""
    tf = _to_imagery_crs(src)
    return shp_transform(lambda xs, ys, z=None: tf.transform(xs, ys), geom_4326)


def patch_for_plot(src, geom_4326: BaseGeometry, pad_m: float = 25.0) -> Patch:
    """Read the image crop covering a plot (in lon/lat), padded by `pad_m` metres on each side.

    Pass the plot's official geometry; you get back the RGB array around it plus the transform
    to relate pixels to coordinates. Clipped to the imagery extent.
    """
    g = geom_to_imagery_crs(src, geom_4326)
    minx, miny, maxx, maxy = g.bounds
    left, bottom, right, top = minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m

    # clip request to the dataset footprint
    dl, db, dr, dt = src.bounds
    left, bottom, right, top = max(left, dl), max(bottom, db), min(right, dr), min(top, dt)
    if right <= left or top <= bottom:
        raise ValueError('plot bounding box does not overlap the imagery extent')

    window = from_bounds(left, bottom, right, top, transform=src.transform)
    rgb = src.read([1, 2, 3], window=window)  # (3, H, W)
    image = np.transpose(rgb, (1, 2, 0))
    return Patch(
        image=image,
        transform=src.window_transform(window),
        crs=str(src.crs),
        bounds=(left, bottom, right, top),
    )
