#!/usr/bin/env python3
"""
Worked end-to-end example — load → look → predict → score.

This is the whole loop in ~15 lines of real work. It drops you exactly where the interesting
part starts: you have the image under a plot, a naive prediction, and a score. Everything after
this — a better correction, a confidence that means something — is yours.

Run (after downloading a bundle into data/<village>/):
    uv run quickstart.py data/34855_vadnerbhairav_chandavad_nashik
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from bhume import load, patch_for_plot, score, write_predictions
from bhume.baseline import global_median_shift
from bhume.geo import open_imagery

DEFAULT_VILLAGE = 'data/34855_vadnerbhairav_chandavad_nashik'


def main(village_dir: str) -> None:
    village = load(village_dir)
    n_truth = 0 if village.example_truths is None else len(village.example_truths)
    print(f'Loaded {village.slug}')
    print(f'  {len(village.plots)} plots · {n_truth} example truths · '
          f'boundaries={"yes" if village.boundaries_path else "none"}')

    # 1) Look at the imagery under one plot — this is your substrate.
    pn = village.plots.index[0]
    with open_imagery(village.imagery_path) as src:
        patch = patch_for_plot(src, village.plot(pn), pad_m=30)
    Image.fromarray(patch.image).save('patch_example.png')
    print(f'  image patch under plot {pn}: {patch.image.shape} → saved patch_example.png')

    # 2) Make a naive prediction (the floor to beat).
    preds = global_median_shift(village)
    out = write_predictions(Path(village_dir) / 'predictions.geojson', preds)
    print(f'  wrote {len(preds)} predictions → {out}')

    # 3) Self-score it against the example truths.
    print()
    print(score(preds, village))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VILLAGE)
