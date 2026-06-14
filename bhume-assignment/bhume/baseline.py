"""A deliberately naive baseline — a floor to beat, and a worked load→predict→score loop."""

from __future__ import annotations

import statistics

import geopandas as gpd
from shapely.affinity import translate


def _utm_for(geom) -> str:
    lon = geom.centroid.x
    return f'EPSG:{32600 + int((lon + 180) // 6) + 1}'


def global_median_shift(village, confidence: float = 0.5) -> gpd.GeoDataFrame:
    """Estimate ONE translation from the example truths and apply it to every plot.

    The error is mostly a coherent per-village offset, so a single shift helps a lot of plots —
    and visibly misses the ones whose drift differs (rotation, local stretch, outliers). That gap
    is the interesting part this baseline leaves for you. Returns a contract-shaped predictions
    GeoDataFrame (all `corrected`, uniform `confidence` — note how flat confidence tanks the
    calibration score).
    """
    if village.example_truths is None:
        raise ValueError(f'{village.slug} has no example_truths.geojson to estimate a shift from')

    utm = _utm_for(village.example_truths.geometry.iloc[0])
    official_u = village.plots.to_crs(utm)
    truth_u = village.example_truths.to_crs(utm)

    dxs, dys = [], []
    for pn in village.example_truths.index:
        if pn in official_u.index:
            o = official_u.loc[pn, 'geometry'].centroid
            t = truth_u.loc[pn, 'geometry'].centroid
            dxs.append(t.x - o.x)
            dys.append(t.y - o.y)
    if not dxs:
        raise ValueError('no overlapping plots between example truths and the cadastre')
    mdx, mdy = statistics.median(dxs), statistics.median(dys)

    shifted = official_u.copy()
    shifted['geometry'] = shifted.geometry.apply(lambda g: translate(g, mdx, mdy))
    preds = shifted.to_crs('EPSG:4326')
    preds['status'] = 'corrected'
    preds['confidence'] = confidence
    preds['method_note'] = f'global median shift dx={mdx:.1f}m dy={mdy:.1f}m'
    return preds[['plot_number', 'status', 'confidence', 'method_note', 'geometry']]
