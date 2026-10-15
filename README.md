# Old City Films

Short clips of American cities, cut from ephemeral films in the [Prelinger Archives](https://archive.org/details/prelinger) on the Internet Archive. The sources are city promotions, industrial films, educational films, newsreels, and home movies from the first half of the twentieth century, not feature films.

529 clips from 104 films are included. Years run from 1906 to 1968 where the source states a year. San Francisco, New York, and Detroit make up most of the set.

Each Internet Archive page states that film's license. This set keeps only items that allow redistribution and clips: public domain, CC0, CC BY, CC BY-SA, CC BY-NC, and CC BY-NC-SA. No-derivatives (ND) licenses are excluded. A few items are CC BY-NC, so those clips are not for commercial use.

## What is in the repository

- `data/clips/`: the clips, each with a poster still.
- `data/clips.jsonl`: start time, duration, city, license, and the link back to the source film.
- `data/catalog.jsonl`: one row per source film. City and year are read from the title and description.
- `data/catalog.html`: the films grouped by city.
- `data/index.html`: a local player for the clips.

Scene words are taken from the film's own description. They are not a frame-by-frame label. Blank frames, color bars, title cards, and studio logos were removed after review.

Full-length downloads are not in this repository. Two catalog films were not cut because the download did not finish: *Lost Landscapes of Detroit 2* (2011) and *Yesterday And Tomorrow In Detroit*.

## Rebuild

From this folder:

```powershell
python build.py catalog
python build.py sample
```

`sample` with `--films 0` walks the whole catalog. A second run skips films that already have clips. Each film keeps at most `--clips` segments, spread across its running time, usually 3 to 10 seconds long.
