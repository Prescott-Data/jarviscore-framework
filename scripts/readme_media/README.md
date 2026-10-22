# README media (images live in jarviscore/docs/assets/readme/)

- `how-it-works.png` is drawn by `scripts/readme_media/how_it_works.py` (writes `how-it-works.svg`), then
  rendered at 2.4x with Chromium: open the SVG in a 1000x540 page and screenshot it.
- Each GIF is a real run of a script in `examples/showcase/`, recorded with
  `asciinema rec --headless --window-size 100x44 -i 1.5` and rendered with
  `agg --theme github-dark --font-size 16 --idle-time-limit 2`. Waiting is
  compressed; each recording prints the run's real elapsed time at the end.
- The crash recording starts the workflow in the background, waits until Redis
  holds step 1's output, then runs `kill -9` on the process and starts it again.
