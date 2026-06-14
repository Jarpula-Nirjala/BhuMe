# Data & Submission Contract

This is the precise input/output specification for the assignment. **Your approach is entirely
yours**, this document only fixes the *shape* of the data you receive and the file you return,
so your work can be evaluated automatically and fairly.

> The deeper "what is this problem and why does it exist" walkthrough lives in the onboarding
> section of the site. This file is the technical contract only.

---

## The task, in one line

For each plot we give you, return your **best estimate of its true on-the-ground boundary**,
and a number saying **how confident you are**. The boundary we give you is the official one as
currently digitised in the land records; it may sit some distance from where the land actually is.

You are **not** expected to correct every plot. Returning a confident, honest answer for the plots
you can, and flagging the ones you cannot, is exactly the point.

**Submit a method, not hand-edited results.** Give us the code that turns a village bundle (the plots
in `input.geojson` plus `imagery.tif` and the optional boundary hints) into `predictions.geojson`; we
run it and read it. Hand-aligned geometry, or a solution overfit to the
example truths, scores poorly even when the numbers look good; we want a method that holds up on
data it wasn't tuned to. You receive the **whole village at once**, so use as much or as little neighbouring
context as you like.

---

## What you get

You receive a folder per village. Each contains:

```text
data/<village_slug>/
  input.geojson      # every plot in the village, this is what you transform
  imagery.tif        # georeferenced satellite mosaic of the whole village (provided)
  boundaries.tif     # OPTIONAL pre-computed field-boundary raster         (provided)
```

> `imagery.tif` and `boundaries.tif` are bundled so you never need an API key, a GPU, or any
> cloud budget. The boundary raster is *one possible* signal: use it, ignore it, or do better.

The two villages span deliberately different terrain so you can choose where to focus:

| Village | District | Plots | Village area | Median plot | Imagery |
|---|---|---:|---:|---:|---:|
| Malatavadi | Kolhapur | 2,508 | ~5.8 km² | 872 m² | ~0.6 m/px |
| Vadnerbhairav | Nashik | 2,457 | ~54 km² | 7,753 m² | ~1.2 m/px |

Each bundle is a **whole village**. Imagery resolution is matched to the parcel scale (finer for
dense small plots, coarser for large fields), which keeps every download a few–15 MB.

---

## Input: `input.geojson`

A GeoJSON `FeatureCollection` in **EPSG:4326 (WGS84 lon/lat)**. One feature per plot; geometry is
the official `Polygon`/`MultiPolygon` as digitised. Properties:

| Field | Type | Meaning |
|---|---|---|
| `plot_number` | string | The plot identifier. **Unique within a village.** Your output must echo this exactly. |
| `village` | string | Village name. |
| `map_area_sqm` | number | Area of the **drawn** polygon (what the cadastre draws on the map). |
| `recorded_area_sqm` | number \| null | The recorded **cultivable** 7/12 area in m², the sum of all holding areas in `surveys` (below) × 10,000. **Excludes pot-kharaba.** |
| `recorded_area_ha` | number \| null | Same, in hectares. |
| `pot_kharaba_ha` | number \| null | Recorded **uncultivable** ("pot-kharaba") area, in hectares, held *separately* from the cultivable area. The parcel's full recorded extent (what the drawn outline encloses) ≈ `recorded_area` + `pot_kharaba`, so compare your geometry against that **total**, not the cultivable figure alone. |
| `surveys` | array | The plot's record breakdown, see below. |

### What `surveys` means

A single drawn plot can bundle one or more **survey numbers** (e.g. `"1124/1"`, `"1124/2/अ"`, the
`/अ`, `/ब` suffixes are hissa subdivisions). Each survey is divided among **holdings**, separate
recorded portions held by different parties, and **each holding has its own area**. A plot's
recorded area is the sum of all its holdings across all its surveys.

```json
"surveys": [
  { "survey_no": "1124/1",   "holdings": [ { "holder": "Person A", "area_ha": 0.57 } ] },
  { "survey_no": "1124/2/अ", "holdings": [ { "holder": "Person B", "area_ha": 0.45 } ] },
  { "survey_no": "1124/2/ब", "holdings": [ { "holder": "Person C", "area_ha": 1.74 } ] }
]
```

- `holder` is an **anonymised** label (`Person A`, `Person B`, …), unique within the plot. Real holder/occupant identities are not shared: each marks a distinct recorded party (a khatedar), not a verified owner. 7/12 records are evidence, not title.
- A plot spanning several surveys/holdings is one where the single drawn shape covers multiple recorded parcels, so its recorded area reflects all of them, not necessarily what one polygon "should" measure on the ground.

Some plots have `null`/empty recorded fields or an empty `surveys` list (nothing on file). That is part of the real data.

---

## Output: `predictions.geojson`

Return one file per village you attempt, named `predictions.geojson`, placed at
`data/<village_slug>/predictions.geojson`. Same format: a `FeatureCollection` in **EPSG:4326**.

Include a feature for **every plot you make a claim about**. Plots you omit are treated as
"not attempted" (no penalty, no credit). Each feature:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `plot_number` | string | yes | Must match a `plot_number` from the village's `input.geojson`. |
| `status` | `"corrected"` \| `"flagged"` | yes | `corrected` = you are predicting a better boundary. `flagged` = you looked but are **not** confident, so you keep the official one. |
| `confidence` | number `0`–`1` | for `corrected` | Your self-assessed confidence that this prediction is right. **This is scored**, it should mean something. |
| `method_note` | string | optional | A short free-text note (how you got it / why you flagged it). |

Geometry rules:
- For `status: "corrected"`, geometry is **your predicted boundary** (`Polygon`/`MultiPolygon`). You may translate, rotate, and/or reshape it, whatever your method produces.
- For `status: "flagged"`, return the original geometry (kept as-is).

### Example feature

```json
{
  "type": "Feature",
  "geometry": { "type": "Polygon", "coordinates": [[[74.21, 20.33], [74.211, 20.33], ...]] },
  "properties": {
    "plot_number": "142",
    "status": "corrected",
    "confidence": 0.78,
    "method_note": "shifted onto the field edge visible in imagery"
  }
}
```

---

## How it's measured (so there are no surprises)

We hold a hidden set of carefully hand-aligned "true" boundaries inside these footprints. Your
output is scored on, among other things:

- **Accuracy**: how close your `corrected` boundaries land to the hidden truth, by **IoU** (intersection-over-union, the shared area ÷ the combined area of two shapes, 0–1) and centroid distance, vs the official starting position.
- **Confidence calibration**: whether the plots you marked high-confidence are actually the accurate ones. A confidence that doesn't track accuracy scores poorly.
- **Restraint**: whether you avoid moving plots that were already correct.

You also send a **5-minute video** walking through your approach to the problem, and your **AI
transcripts** (no written report). We expect AI used two ways, to understand the problem (web chats)
and to build the solution (coding tools); keep them in a `/transcripts` folder in your repo, with any
web-chat share links listed in `transcripts/README.md`. The metrics rank and filter submissions, but
what *decides* is your *approach to an open, messy problem*, how you reason and direct AI.

Everything (code, `predictions.geojson`, `/transcripts`) lives in **one GitHub repo**; you hand it
in through a short Google Form (repo URL, video link, résumé, name).

---

## Notes

- Coordinates are **lon, lat** order (GeoJSON / WGS84), as in the input.
- Areas in the input are in square metres / hectares as labelled. The "true" area of a plot is
  not something we hand you. Part of the problem is reasoning about which numbers to trust.
- Keep your output a valid GeoJSON `FeatureCollection`. That's the only hard formatting requirement.
