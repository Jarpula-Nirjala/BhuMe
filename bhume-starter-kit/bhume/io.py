"""Loading a village bundle and writing predictions in the contract format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd


@dataclass
class Village:
    """One village bundle, loaded and CRS-sorted.

    `plots` is the official (shifted) cadastre you transform — a GeoDataFrame in EPSG:4326
    indexed by `plot_number`, carrying the recorded areas and survey breakdown. `example_truths`
    is the small public sample of hand-aligned boundaries you self-score against (None until you
    download it). The imagery/boundary rasters are referenced by path; open them with
    `bhume.geo` helpers (they handle the EPSG:3857 ↔ 4326 mismatch for you).
    """

    slug: str
    dir: Path
    plots: gpd.GeoDataFrame
    imagery_path: Path
    boundaries_path: Path | None
    example_truths: gpd.GeoDataFrame | None

    def plot(self, plot_number: str):
        """The official geometry for one plot (raises KeyError if unknown)."""
        return self.plots.loc[str(plot_number), 'geometry']


def load(village_dir: str | Path) -> Village:
    """Load a village bundle from a downloaded folder.

    Expects `input.geojson` + `imagery.tif`; `boundaries.tif` and `example_truths.geojson` are
    optional. Raises FileNotFoundError if the required files are missing.
    """
    d = Path(village_dir)
    input_path = d / 'input.geojson'
    imagery_path = d / 'imagery.tif'
    if not input_path.exists():
        raise FileNotFoundError(f'{input_path} not found — download the village bundle into {d}/')
    if not imagery_path.exists():
        raise FileNotFoundError(f'{imagery_path} not found — download the village bundle into {d}/')

    plots = gpd.read_file(input_path)
    plots['plot_number'] = plots['plot_number'].astype(str)
    plots = plots.set_index('plot_number', drop=False)

    boundaries_path = d / 'boundaries.tif'
    truths_path = d / 'example_truths.geojson'
    example_truths = None
    if truths_path.exists():
        example_truths = gpd.read_file(truths_path)
        example_truths['plot_number'] = example_truths['plot_number'].astype(str)
        example_truths = example_truths.set_index('plot_number', drop=False)

    return Village(
        slug=d.name,
        dir=d,
        plots=plots,
        imagery_path=imagery_path,
        boundaries_path=boundaries_path if boundaries_path.exists() else None,
        example_truths=example_truths,
    )


def write_predictions(path: str | Path, predictions: gpd.GeoDataFrame) -> Path:
    """Write a predictions GeoDataFrame to a contract-valid `predictions.geojson` (EPSG:4326).

    `predictions` must carry `plot_number` and `status` columns; `corrected` rows must also carry
    a `confidence` in [0, 1]. `method_note` is optional. Geometry is written as-is — make sure it
    is already in EPSG:4326 (lon, lat).
    """
    required = {'plot_number', 'status', 'geometry'}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f'predictions is missing required columns: {sorted(missing)}')

    gdf = predictions.copy()
    if gdf.crs is None:
        gdf = gdf.set_crs('EPSG:4326')
    else:
        gdf = gdf.to_crs('EPSG:4326')

    keep = [c for c in ('plot_number', 'status', 'confidence', 'method_note', 'geometry') if c in gdf.columns]
    out = Path(path)
    out.write_text(gdf[keep].to_json())
    return out


def read_predictions(path: str | Path) -> gpd.GeoDataFrame:
    """Read a predictions/truth GeoJSON back into a GeoDataFrame indexed by plot_number."""
    gdf = gpd.read_file(path)
    if 'plot_number' in gdf.columns:
        gdf['plot_number'] = gdf['plot_number'].astype(str)
        gdf = gdf.set_index('plot_number', drop=False)
    return gdf
