# Original editorial motion study

`line-study.mp4` is an original local animation for the inline video component. It is an abstract design demonstration, **not business data**, and contains no Anthropic media or remote assets.

- H.264 MP4, 960 × 540, 24 fps, 7 seconds, 168 frames, no audio.
- `line-study-poster.png`: 960 × 540 poster from frame 112.
- Paper background, olive contour lines, a moving circular endpoint, restrained serif title. The animation draws a continuous line and settles into a still frame; it does not loop itself.
- Fonts: existing pinned `../fonts/LiberationSerif-Regular.ttf` and `../fonts/LiberationSans-Regular.ttf`; licenses remain in the fonts directory.

## Reproduce

Use a Python environment with Pillow installed to run `generate-film.py`. It renders antialiased frames to `/tmp/editorial-motion-frames` and writes the poster here. Run the system Swift interpreter with `encode-film.swift FRAME_DIR OUTPUT.mp4` to encode using macOS AVFoundation. The commands below require both dependencies to be available locally.

```sh
python3 docs/design/dashboard-demos/editorial/media/generate-film.py
swift -module-cache-path /tmp/editorial-swift-module-cache docs/design/dashboard-demos/editorial/media/encode-film.swift /tmp/editorial-motion-frames docs/design/dashboard-demos/editorial/media/line-study.mp4
```

The encoding command may require access outside the filesystem sandbox to contact the macOS system encoder. Sandbox-only execution returned AVFoundation `Cannot Encode`; the same authorized local command outside that sandbox succeeded. The output was fully decoded using AVAssetReader: **168 frames, 7.0 seconds, 960 × 540, zero audio tracks**. The poster was inspected. Browser playback and component interaction are separate checks performed by the integrating agent.
