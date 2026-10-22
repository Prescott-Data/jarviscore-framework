# README media (images live in jarviscore/docs/assets/readme/)

- `how-it-works.png` is drawn by `scripts/readme_media/how_it_works.py` (writes `how-it-works.svg`), then
  rendered at 2.4x with Chromium: open the SVG in a 1000x540 page and screenshot it.
- `components.png` is drawn by `scripts/readme_media/components.py` (writes `components.svg`), rendered
  the same way in a 1000x456 page.
- `desk-research-team.mp4` is attached to each GitHub release so the README can link a playable
  video: `gh release upload vX.Y.Z jarviscore/docs/assets/readme/desk-research-team.mp4`.
- `mesh-vs-orchestrator.png` is drawn by `scripts/readme_media/mesh_vs_orchestrator.py` (writes
  `mesh-vs-orchestrator.svg`) and rendered the same way, in a 1000x500 page.
- `video-overview.jpg` is the overview film's own YouTube thumbnail with a play control and its
  length: `scripts/readme_media/video_card.py` writes an HTML page; screenshot it at 1280x720.
- Each GIF is a real run of a script in `examples/showcase/`, recorded with
  `asciinema rec --headless --window-size 100x44 -i 1.5` and rendered with
  `agg --theme github-dark --font-size 16 --idle-time-limit 2`. Waiting is
  compressed; each recording prints the run's real elapsed time at the end.
- The crash recording starts the workflow in the background, waits until Redis
  holds step 1's output, then runs `kill -9` on the process and starts it again.
