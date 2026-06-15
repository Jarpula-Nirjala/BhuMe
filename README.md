# BhuMe

**BhuMe Boundary Take-Home** — automated correction of shifted Maharashtra cadastral plot boundaries using satellite imagery and ML boundary hints.

**Author:** [Jarpula Nirjala](https://github.com/Jarpula-Nirjala)

---

## Problem

Official land-record plot outlines in Maharashtra were drawn on paper and later georeferenced onto satellite imagery. The result: boundaries often sit metres away from where the fields actually are. For each plot, this solution decides **whether** the boundary can be nudged onto the real field, **where** it should go, and **how confident** we are — or flags plots we cannot place reliably.

---

## Approach

1. **Global median shift** — estimate a village-wide translation (UTM metres) from the public `example_truths.geojson` and apply it to every plot as a baseline.
2. **Per-plot local refinement** — rasterize the globally-shifted plot outline and cross-correlate it with `boundaries.tif` hint edges (resampled from 2× coarser resolution to match imagery). Search is constrained to ±18 px.
3. **Accept/reject guard** — apply the local offset only when correlation sharpness and on-outline hint strength beat the global-only position.
4. **Confidence scoring** — weighted combination of boundary-hint strength, area-ratio plausibility, correlation sharpness, and shift-magnitude penalty (clipped 0.05–0.95).
5. **Restraint** — flag plots with extreme area mismatch, missing imagery, shifts >100 m, or confidence below 0.28; return the official geometry unchanged.

---

## Results (Vadnerbhairav)

Validated on [hiring.bhume.in/test](https://hiring.bhume.in/test):

| Metric | Result |
|--------|--------|
| Coverage | 6 corrected · 0 flagged (of 6 public truths) |
| Median IoU (you) | **0.807** (official 0.612) |
| Improvement | **+0.203** (100% of plots improved) |
| Accurate @ IoU≥0.5 | **100%** |
| Median centroid error | **6.4 m** |
| Calibration ρ (Spearman) | **0.83** |

Village-wide (2,457 plots): **2,236 corrected · 221 flagged** · max shift **40 m** · confidence range **0.28–0.64**

Local self-score output:

```
=== 34855_vadnerbhairav_chandavad_nashik · scored on 6 example truths ===
coverage:    6 corrected + 0 flagged
accuracy:    median IoU pred=0.807 vs official=0.612  (improvement=0.203, improved 1.000)
             median centroid err=6.329 m · accurate(IoU>=.5)=1.000
calibration: Spearman(conf,IoU)=0.829 · AUC=—
restraint:   N/A — graded on the hidden set (no control plots here)
```

> AUC is not computed on the 6 public truths because all are accurate (IoU ≥ 0.5). The hidden grading set is larger and includes plots where flagging is correct.

---

## Quick start

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Install

```bash
git clone https://github.com/Jarpula-Nirjala/BhuMe.git
cd BhuMe
uv sync
```

### Download data

Get a village bundle from [hiring.bhume.in/start](https://hiring.bhume.in/start) and place it under `data/`:

```
data/34855_vadnerbhairav_chandavad_nashik/
  input.geojson
  imagery.tif          # ~14 MB — not in repo, download separately
  boundaries.tif         # ~16 MB — not in repo, download separately
  example_truths.geojson
```

### Run predictions

```bash
uv run predict.py data/34855_vadnerbhairav_chandavad_nashik
```

Output: `data/<village>/predictions.geojson`

### Baseline comparison

```bash
uv run quickstart.py data/34855_vadnerbhairav_chandavad_nashik
```

Runs the starter-kit global-median-shift baseline (~+0.11 IoU improvement).

### Validate output

Upload `predictions.geojson` to [hiring.bhume.in/test](https://hiring.bhume.in/test).

---

## Project structure

```
BhuMe/
├── bhume/                  # BhuMe starter-kit helpers (load, score, geo, baseline)
├── src/
│   ├── align.py            # Global shift, cross-correlation, edge fallback
│   ├── confidence.py       # Multi-signal confidence scoring
│   └── utils.py            # Raster masks, area-ratio helpers
├── data/
│   └── <village_slug>/
│       ├── input.geojson
│       ├── example_truths.geojson
│       └── predictions.geojson
├── predict.py              # Main entry point
├── quickstart.py           # Starter-kit baseline demo
├── transcripts/            # AI chat transcript links
├── pyproject.toml
├── uv.lock
├── CONTRACT.md             # Input/output contract from BhuMe
└── README.md
```

---

## What worked / what didn't

| Worked | Didn't |
|--------|--------|
| Global UTM median shift captures most village-wide drift | Raw phase cross-correlation on mismatched raster resolutions |
| Constrained outline↔hint correlation after global shift | Applying local offset without accept/reject guard |
| Resampling coarse `boundaries.tif` (2× imagery GSD) before correlation | Flat uniform confidence (baseline) — fixed with multi-signal scoring |
| Flagging area-ratio outliers and low-confidence plots | AUC on 6 public truths — needs mixed outcomes |

---

## Next steps (with more time)

- Per-plot shift clustering for sub-village drift patterns
- Rotation/skew search where translation is insufficient
- Validate on Malatavadi (dense small parcels) without parameter changes
- Learned confidence calibration on a held-out truth set

---

## Dependencies

Managed via `uv` / `pyproject.toml`:

- geopandas, shapely, rasterio, numpy, scipy, pillow, scikit-image

---

## Submission

- **Test:** [hiring.bhume.in/test](https://hiring.bhume.in/test)
- **Submit:** [hiring.bhume.in/submit](https://hiring.bhume.in/submit)

---

## License

This project is licensed under the MIT License.

Copyright (c) 2026 Jarpula Nirjala

See the [LICENSE](LICENSE) file for details.
