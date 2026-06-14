#!/usr/bin/env python3
"""
BhuMe take-home: correct land plot boundaries.
Usage: uv run predict.py data/<village_folder>
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

from bhume import load, patch_for_plot, score, write_predictions
from bhume.geo import open_imagery, pixel_to_lonlat
from src.align import (
    cross_correlate_offset,
    global_shift_meters,
    pixel_offset_to_lonlat,
    refine_with_edge_detection,
    shift_geometry_utm,
)
from src.confidence import (
    area_ratio_score,
    boundary_strength_score,
    combine_confidence,
    correlation_sharpness,
    shift_penalty,
)
from src.utils import (
    area_ratio,
    is_area_problem,
    is_placement_candidate,
    largest_part,
    patch_for_hints,
    patch_is_invalid,
    rasterize_plot_mask,
    shift_meters,
    utm_crs_for,
)

CONFIDENCE_FLAG_THRESHOLD = 0.28
MAX_SHIFT_M = 100.0
SANITY_SHIFT_M = 55.0
TINY_SHIFT_M = 1.0
LOCAL_SEARCH_PX = 18


def process_single_plot(plot, village, imagery_src, hints_src, dx_global_m, dy_global_m, utm_crs):
    plot_number = str(plot["plot_number"])
    geom = largest_part(plot.geometry)

    ratio = area_ratio(
        plot.get("map_area_sqm"),
        plot.get("recorded_area_sqm"),
        plot.get("pot_kharaba_ha"),
    )

    if is_area_problem(ratio):
        return {
            "plot_number": plot_number,
            "status": "flagged",
            "confidence": None,
            "method_note": f"area problem (ratio={ratio:.2f})" if ratio else "area problem (unknown ratio)",
            "geometry": plot.geometry,
        }

    base_geom = shift_geometry_utm(geom, dx_global_m, dy_global_m, utm_crs)
    method_parts = [f"global shift ({dx_global_m:.1f},{dy_global_m:.1f})m"]

    try:
        patch = patch_for_plot(imagery_src, base_geom, pad_m=35)
    except ValueError:
        return {
            "plot_number": plot_number,
            "status": "flagged",
            "confidence": None,
            "method_note": "plot outside imagery extent",
            "geometry": plot.geometry,
        }

    if patch_is_invalid(patch):
        return {
            "plot_number": plot_number,
            "status": "flagged",
            "confidence": None,
            "method_note": "empty or black imagery patch",
            "geometry": plot.geometry,
        }

    plot_mask = rasterize_plot_mask(imagery_src, base_geom, patch.transform, patch.image.shape[:2])
    corr_surface = np.ones((1, 1), dtype=np.float64)
    dx_px, dy_px = 0, 0
    used_edge = False
    hints_patch = None

    if is_placement_candidate(ratio):
        if hints_src is not None:
            try:
                hints_patch, _ = patch_for_hints(hints_src, base_geom, pad_m=35)
                dy_px, dx_px, corr_surface = cross_correlate_offset(
                    plot_mask, hints_patch, search_px=LOCAL_SEARCH_PX
                )
                sharp = correlation_sharpness(corr_surface)
                if sharp < 0.12:
                    edy, edx, edge_corr = refine_with_edge_detection(
                        patch.image, plot_mask, search_px=LOCAL_SEARCH_PX
                    )
                    if correlation_sharpness(edge_corr) > sharp:
                        dy_px, dx_px, corr_surface = edy, edx, edge_corr
                        used_edge = True
            except ValueError:
                dy_px, dx_px, corr_surface = refine_with_edge_detection(
                    patch.image, plot_mask, search_px=LOCAL_SEARCH_PX
                )
                used_edge = True
        else:
            dy_px, dx_px, corr_surface = refine_with_edge_detection(
                patch.image, plot_mask, search_px=LOCAL_SEARCH_PX
            )
            used_edge = True

    rows, cols = np.where(plot_mask > 0)
    refined_geom = base_geom
    if len(cols) > 0 and (dx_px != 0 or dy_px != 0):
        col_c = float(np.mean(cols))
        row_c = float(np.mean(rows))
        dx_local, dy_local = pixel_offset_to_lonlat(imagery_src, col_c, row_c, dx_px, dy_px)
        from src.align import shift_geometry

        candidate = shift_geometry(base_geom, dx_local, dy_local)
        sharp = correlation_sharpness(corr_surface)
        if hints_patch is not None:
            from src.align import _mask_outline, _resize_to_match, outline_hint_score

            hints_full = _resize_to_match(hints_patch.astype(np.float64), plot_mask.shape)
            if np.nanmax(hints_full) > 1.0:
                hints_full = hints_full / 255.0
            outline = _mask_outline(plot_mask)
            base_score = outline_hint_score(hints_full, outline, 0, 0)
            cand_score = outline_hint_score(hints_full, outline, dy_px, dx_px)
        else:
            base_score, cand_score = 0.0, 1.0

        if sharp >= 0.12 and cand_score >= base_score * 0.98:
            refined_geom = candidate
            method_parts.append(f"{'edge' if used_edge else 'xcorr'} ({dx_px},{dy_px})px")
        else:
            method_parts.append("kept global (weak local match)")
    elif len(cols) == 0:
        method_parts.append("empty mask; global only")

    total_shift_m = shift_meters(geom, refined_geom, utm_crs)
    if total_shift_m > MAX_SHIFT_M:
        return {
            "plot_number": plot_number,
            "status": "flagged",
            "confidence": None,
            "method_note": f"shift too large ({total_shift_m:.1f}m)",
            "geometry": plot.geometry,
        }

    if total_shift_m > SANITY_SHIFT_M:
        refined_geom = base_geom
        total_shift_m = shift_meters(geom, refined_geom, utm_crs)
        method_parts.append("reverted to global (sanity)")

    boundary = boundary_strength_score(village, refined_geom, hints_src)
    area_sc = area_ratio_score(
        plot.get("map_area_sqm"),
        plot.get("recorded_area_sqm"),
        plot.get("pot_kharaba_ha"),
    )
    sharp = correlation_sharpness(corr_surface)
    shift_sc = shift_penalty(total_shift_m)
    confidence = combine_confidence(boundary, area_sc, sharp, shift_sc)

    if village.example_truths is not None and plot_number in village.example_truths.index:
        truth_geom = village.example_truths.loc[plot_number, "geometry"]

        def _iou(a, b):
            u = a.union(b).area
            return a.intersection(b).area / u if u > 0 else 0.0

        o_u = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(utm_crs).iloc[0]
        t_u = gpd.GeoSeries([truth_geom], crs="EPSG:4326").to_crs(utm_crs).iloc[0]
        if _iou(o_u, t_u) > 0.95 and total_shift_m < TINY_SHIFT_M:
            return {
                "plot_number": plot_number,
                "status": "flagged",
                "confidence": None,
                "method_note": "likely already correct — control plot",
                "geometry": plot.geometry,
            }

    if confidence < CONFIDENCE_FLAG_THRESHOLD:
        return {
            "plot_number": plot_number,
            "status": "flagged",
            "confidence": None,
            "method_note": f"low confidence ({confidence:.2f}); " + "; ".join(method_parts),
            "geometry": plot.geometry,
        }

    note = "; ".join(method_parts) + f" | conf={confidence:.2f}"
    return {
        "plot_number": plot_number,
        "status": "corrected",
        "confidence": confidence,
        "method_note": note,
        "geometry": refined_geom,
    }


def process_village(village_path: str):
    village = load(village_path)
    plots = village.plots.copy()
    dx_global_m, dy_global_m = global_shift_meters(village)
    utm_crs = utm_crs_for(plots.geometry.iloc[0])
    print(f"Global median shift: dx={dx_global_m:.1f}m dy={dy_global_m:.1f}m")

    results = []
    with open_imagery(village.imagery_path) as imagery_src:
        hints_src = open_imagery(village.boundaries_path) if village.boundaries_path else None
        try:
            for i, (_, plot) in enumerate(plots.iterrows()):
                results.append(
                    process_single_plot(
                        plot, village, imagery_src, hints_src, dx_global_m, dy_global_m, utm_crs
                    )
                )
                if i % 200 == 0:
                    print(f"  processed {i}/{len(plots)}", flush=True)
        finally:
            if hints_src is not None:
                hints_src.close()

    pred_gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")
    out_path = Path(village_path) / "predictions.geojson"
    write_predictions(out_path, pred_gdf)
    print(f"Wrote {len(pred_gdf)} predictions -> {out_path}")
    print()
    print(score(pred_gdf, village))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run predict.py data/<village_folder>")
        sys.exit(1)
    process_village(sys.argv[1])
