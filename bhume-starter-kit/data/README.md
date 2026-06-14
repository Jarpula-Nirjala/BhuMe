# Drop village bundles here

Download a bundle from the site's **Get started** page and unzip it into this folder, so you have:

```
data/<village_slug>/
  input.geojson
  imagery.tif
  boundaries.tif
  example_truths.geojson
```

Then, from the kit root: `uv run quickstart.py data/<village_slug>`
