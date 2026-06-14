# BhuMe Boundary Take-Home: Starter Kit

The official plot outlines in Maharashtra's land records sit metres off the real fields (an
artifact of how old paper maps were georeferenced onto satellite imagery). **Your job: for each
plot, return your best estimate of its true on-the-ground boundary, plus a confidence, and flag
the ones you can't place.**

Read the problem in full at the site's **Understand** and **The task** pages first. This kit just
removes the plumbing so you start at the interesting part.

## What this kit does (and doesn't)

It hands you the geospatial plumbing we are **not** assessing, so your hours go to the actual
problem. Each piece, and why it's here:

- **`load(village)`** — plots, imagery, boundary hints and example truths as one object, CRS sorted
  out. *Why: so you're not wiring up a GeoTIFF reader, a GeoJSON reader, and CRS handling before you
  can even look at a plot.*
- **`patch_for_plot(src, geom)`** — the RGB pixels under a plot. *Why: cropping a georeferenced
  raster to a polygon (the window + affine-transform math) is fiddly and isn't what we're testing.*
- **`lonlat_to_pixel` / `pixel_to_lonlat`** — convert between map coordinates and image pixels.
  *Why: the plots are lon/lat (EPSG:4326) but the imagery is web-mercator (EPSG:3857); mixing them
  up silently misaligns everything, and debugging that is a time sink, not a signal.*
- **`score(preds, village)`** — the exact accuracy + calibration + restraint metrics we grade on,
  run against the public example truths. *Why: a real feedback loop, you iterate against the same
  numbers we'll compute.*
- **`write_predictions(path, gdf)`** — emit a contract-valid `predictions.geojson`. *Why: so a
  schema slip never sinks an otherwise-good submission.*
- **`global_median_shift(village)`** — a deliberately naive baseline and a worked load→score loop.
  *Why: a floor to beat, and ~15 lines showing the whole cycle so you start at the interesting part.*

What it deliberately does **not** do: correct a plot for you. There's no align/snap/solve. The
method (how you find the true boundary, how you decide your confidence) is the whole point.

**Use any AI tools you like.** We expect it. We're assessing how you direct them, not whether you
typed every line. The plumbing above is exactly the kind of thing to let an LLM handle; the
judgment (which edge is right, what your confidence should mean, which records to trust) is not.

## Setup

This kit uses [uv](https://docs.astral.sh/uv/). Install it once
([instructions](https://docs.astral.sh/uv/getting-started/installation/)), then:

```bash
uv sync
```

That reads `pyproject.toml` / `uv.lock`, picks Python 3.12, and installs everything (geopandas,
rasterio, shapely, numpy, scipy, pillow) into a local `.venv`. The rasterio and geopandas wheels
bundle GDAL, so there's no system GDAL to install. Prefix commands with `uv run` (below) and you
never have to activate the venv yourself.

## Get the data

Download a village bundle from the site's **Get started** page and unzip it into `data/`:

```
data/
  34855_vadnerbhairav_chandavad_nashik/
    input.geojson         # the plots you transform (official, shifted)
    imagery.tif           # georeferenced satellite mosaic, your primary signal
    boundaries.tif        # rough, optional auto-detected field hints
    example_truths.geojson# a few hand-aligned truths, for self-scoring
```

## Run the worked example

```bash
uv run quickstart.py data/34855_vadnerbhairav_chandavad_nashik
```

You'll see the baseline's score, e.g.:

```
accuracy:    median IoU pred=0.71 vs official=0.61  (improvement=+0.11, improved 1.00)
calibration: Spearman(conf,IoU)=— · AUC=—   (flat confidence → no signal; this is the bar to clear)
```

Then make it better. A few directions (yours to choose, ignore, or replace):

- The error is mostly a coherent offset, but not entirely. What's left after a global shift?
- The imagery shows the real field edges. The boundary hints pre-detect some of them (roughly,
  and only where they're visible). How do you use the image where the hints are thin?
- Your confidence is scored. What makes a plot's correction trustworthy vs. a guess?
- Some plots can't be placed. Flagging them is a correct answer.

## Scoring notes

`score()` mirrors the objective (L1) half of grading: IoU vs the truth, improvement over the
official position, confidence calibration (does high confidence mean high accuracy?), and restraint
(don't move already-correct plots). It runs over the **public example truths only** — a handful — so
treat its output as a **rough directional check, not a grade**. Calibration in particular needs more
plots than this to mean much (and restraint shows nothing here: the public sample has no
already-correct control plots), so reason about what your confidence *should* represent rather than
maximizing the number on this sample. Your real grade uses a larger hidden set, so don't overfit to
these few. The contract spec is in `CONTRACT.md`.
