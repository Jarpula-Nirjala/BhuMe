"""Self-scoring against the example truths.

This mirrors the objective half (L1) of how your submission is graded — accuracy, confidence
calibration, and restraint — but it runs only over the handful of public example truths, so treat
its numbers as a rough directional check, not your grade (calibration in particular needs more
plots than this to mean much). Your real grade uses a larger, hidden set. All geometry is measured
in local UTM (true metres / area).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
from scipy.stats import spearmanr
from shapely.geometry.base import BaseGeometry

ACC_IOU = 0.5          # a "corrected" plot counts as accurate at IoU >= this
CONTROL_SHIFT_M = 5.0  # moving an already-correct plot more than this is a false shift


@dataclass
class Scorecard:
    village: str
    n_truth: int
    n_corrected: int
    n_flagged: int
    median_iou_pred: float | None
    median_iou_official: float | None
    median_improvement: float | None
    median_centroid_err_m: float | None
    accurate_rate: float | None
    improved_frac: float | None
    spearman_conf_vs_iou: float | None
    auc_accurate_vs_conf: float | None
    n_controls: int
    false_shift_rate: float | None
    violations: list = field(default_factory=list)

    def __str__(self) -> str:
        def f(x):
            return '—' if x is None else (f'{x:.3f}' if isinstance(x, float) else str(x))
        lines = [
            f'=== {self.village} · scored on {self.n_truth} example truths ===',
            f'coverage:    {self.n_corrected} corrected + {self.n_flagged} flagged',
            f'accuracy:    median IoU pred={f(self.median_iou_pred)} vs official='
            f'{f(self.median_iou_official)}  (improvement={f(self.median_improvement)}, '
            f'improved {f(self.improved_frac)})',
            f'             median centroid err={f(self.median_centroid_err_m)} m · '
            f'accurate(IoU>=.5)={f(self.accurate_rate)}',
            f'calibration: Spearman(conf,IoU)={f(self.spearman_conf_vs_iou)} · '
            f'AUC={f(self.auc_accurate_vs_conf)}   (higher = confidence tracks accuracy)',
            f'restraint:   {"N/A — graded on the hidden set (no control plots here)" if not self.n_controls else f"false-shift {f(self.false_shift_rate)} over {self.n_controls} controls"}',
        ]
        if self.violations:
            lines.append(f'⚠ {len(self.violations)} schema issue(s): ' + '; '.join(self.violations[:5]))
        return '\n'.join(lines)


def _utm_for(geom: BaseGeometry) -> str:
    lon = geom.centroid.x
    return f'EPSG:{32600 + int((lon + 180) // 6) + 1}'


def _iou(a: BaseGeometry, b: BaseGeometry) -> float:
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    union = a.union(b).area
    return float(a.intersection(b).area / union) if union > 0 else 0.0


def _auc(scores: list[float], labels: list[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    return round(xs[len(xs) // 2], 3) if xs else None


def _as_indexed(obj) -> gpd.GeoDataFrame:
    gdf = obj if isinstance(obj, gpd.GeoDataFrame) else gpd.read_file(obj)
    gdf = gdf.copy()
    gdf['plot_number'] = gdf['plot_number'].astype(str)
    return gdf.set_index('plot_number', drop=False)


def score(predictions, village) -> Scorecard:
    """Score `predictions` (a GeoDataFrame or a path) against `village.example_truths`.

    Returns a Scorecard you can print. Plots you didn't predict simply don't count; `flagged`
    plots count as "did not move." Raises ValueError if the village has no example truths yet.
    """
    if village.example_truths is None:
        raise ValueError(f'{village.slug} has no example_truths.geojson — download it into {village.dir}/')

    pred = _as_indexed(predictions)
    truth = village.example_truths
    official = village.plots

    utm = _utm_for(truth.geometry.iloc[0])
    truth_u = truth.to_crs(utm)
    official_u = official.to_crs(utm)
    pred_u = pred.to_crs(utm)

    violations = []
    rows = []
    for pn in truth.index:
        t = truth_u.loc[pn, 'geometry']
        o = official_u.loc[pn, 'geometry']
        iou_official = _iou(o, t)
        is_control = str(truth.loc[pn].get('status')) == 'already_correct'
        rec = {'control': is_control, 'iou_official': iou_official, 'status': None,
               'confidence': None, 'iou_pred': None, 'improvement': None,
               'centroid_err_m': None, 'control_shift_m': None}
        if pn in pred_u.index:
            row = pred.loc[pn]
            status = str(row.get('status'))
            rec['status'] = status
            if status == 'corrected':
                conf = row.get('confidence')
                if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
                    violations.append(f'{pn}: confidence {conf!r} not in [0,1]')
                pg = pred_u.loc[pn, 'geometry']
                if pg.is_empty or not pg.is_valid:
                    violations.append(f'{pn}: invalid/empty geometry')
                else:
                    rec['confidence'] = conf if isinstance(conf, (int, float)) else None
                    rec['iou_pred'] = _iou(pg, t)
                    rec['improvement'] = rec['iou_pred'] - iou_official
                    rec['centroid_err_m'] = pg.centroid.distance(t.centroid)
                    if is_control:
                        rec['control_shift_m'] = pg.centroid.distance(o.centroid)
            elif status not in ('flagged', 'corrected'):
                violations.append(f'{pn}: bad status {status!r}')
        rows.append(rec)

    corrected = [r for r in rows if r['status'] == 'corrected' and r['iou_pred'] is not None]
    controls = [r for r in rows if r['control']]
    confs_ious = [(r['confidence'], r['iou_pred']) for r in corrected if isinstance(r['confidence'], (int, float))]

    spearman = None
    if len(confs_ious) >= 3:
        cs, iz = [c for c, _ in confs_ious], [i for _, i in confs_ious]
        if len(set(cs)) > 1 and len(set(iz)) > 1:
            spearman = round(spearmanr(cs, iz).correlation, 3)

    ious = [r['iou_pred'] for r in corrected]
    fs = [r for r in controls if r['control_shift_m'] is not None and r['control_shift_m'] > CONTROL_SHIFT_M]

    return Scorecard(
        village=village.slug,
        n_truth=len(truth),
        n_corrected=len(corrected),
        n_flagged=sum(r['status'] == 'flagged' for r in rows),
        median_iou_pred=_median(ious),
        median_iou_official=_median([r['iou_official'] for r in rows]),
        median_improvement=_median([r['improvement'] for r in corrected]),
        median_centroid_err_m=_median([r['centroid_err_m'] for r in corrected]),
        accurate_rate=round(sum(i >= ACC_IOU for i in ious) / len(ious), 3) if ious else None,
        improved_frac=round(sum(r['improvement'] > 0 for r in corrected) / len(corrected), 3) if corrected else None,
        spearman_conf_vs_iou=spearman,
        auc_accurate_vs_conf=_auc([c for c, _ in confs_ious], [i >= ACC_IOU for _, i in confs_ious]) if confs_ious else None,
        n_controls=len(controls),
        false_shift_rate=round(len(fs) / len(controls), 3) if controls else None,
        violations=violations,
    )


def score_file(predictions_path: str | Path, village) -> Scorecard:
    """Convenience: score a predictions.geojson on disk."""
    return score(Path(predictions_path), village)
