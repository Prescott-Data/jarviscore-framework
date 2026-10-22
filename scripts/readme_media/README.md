# README media (images live in jarviscore/docs/assets/readme/)

- `how-it-works.png` is drawn by `scripts/readme_media/how_it_works.py` (writes `how-it-works.svg`), then
  rendered at 2.4x with Chromium: open the SVG in a 1000x540 page and screenshot it.
- `mesh-vs-orchestrator.png` is drawn by `scripts/readme_media/mesh_vs_orchestrator.py` (writes
  `mesh-vs-orchestrator.svg`) and rendered the same way, in a 1000x500 page.
- `video-overview.jpg` is the overview film's own YouTube thumbnail with a play control and its
  length: `scripts/readme_media/video_card.py` writes an HTML page; screenshot it at 1280x720.
- `poster-*.png` (docs home) are the last frame of each showcase GIF, cropped to the end of the run.
- Each GIF is a real run of a script in `examples/showcase/`, recorded with
  `asciinema rec --headless --window-size 100x44 -i 1.5` and rendered with
  `agg --theme github-dark --font-size 16 --idle-time-limit 2`. Waiting is
  compressed; each recording prints the run's real elapsed time at the end.
- The crash recording starts the workflow in the background, waits until Redis
  holds step 1's output, then runs `kill -9` on the process and starts it again.
