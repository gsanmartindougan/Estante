# Estante · Promotional clips

Bilingual delivery · 28 October 2026.

**40 MP4 files: 10 topics × Spanish/English × landscape/portrait.** Every clip runs 20 seconds and includes burned-in captions plus separate UTF-8 SRT and ASS files. H.264, 24 fps, square pixels, YUV 4:2:0, BT.709 signaling. Landscape: 1920 × 1080; portrait: 1080 × 1920. No added narration or music.

## Series

| No. | Topic | Coverage |
| --- | --- | --- |
| 01 | Introduction | Linux library, sources, navigation and layouts |
| 02 | Bring your games together | Steam/Faugus/Heroic, scripts, AppImages, arguments and launcher startup |
| 03 | Organization | Search, categories, pagination and initial-letter navigation |
| 04 | Layouts | List, Grid, Carousel and Sense |
| 05 | Personalization | Details, synopsis, covers, logos, selection and backgrounds |
| 06 | Controls | Languages, gamepad types, built-in keyboard, mouse and shortcuts |
| 07 | Activity | Playtime, sessions and per-game history |
| 08 | During and between games | Stay open, close/restore, tray and screensaver |
| 09 | Installation and updates | x86_64 AppImage, bundled dependencies and update controls |
| 10 | Artwork and details | SteamGridDB, IGDB, Wikidata, local files and URLs |

Claims are based on the project’s `README.md`, `README.en.md`, `RELEASE_NOTES.md` and the Qt legacy settings schema in the separate `estante-qt-legacy` project. These clips introduce the main functions. They do not stage or execute installation, game launches, downloads or actual imports; they show genuine forms/settings with captions explaining the function. External services may require credentials, and launchers must be installed. No universal compatibility or performance claim is made.

## Layout and captions

Landscape preserves the full window on a branded canvas with captions outside the application viewport. Portrait shows one complete application window, fitted proportionally, with the heading and captions outside the interface. It adds no zoom, crop or duplicate view and does not pretend that Estante has a mobile interface.

Two-second opening, four four-second shots, two-second closing. Clean cuts, real-speed footage. Qt captures real actions, panels and keyboard navigation. Cards use explicit typography, shapes and the existing icon. No generative images or video were used.

Promotional copy, titles and captions have Spanish and English versions. The app is recorded with the corresponding language setting. Some built-in labels in the current Estante version still remain Spanish even in English mode; game metadata also retains its original language. These are preserved as part of the real product, rather than painted over or represented as a completed product translation.

## Editable sources and rebuilding

- `media/es/`, `media/en/`: original scene recordings, reference PNGs and recording logs; color is not retouched.
- `es/horizontal`, `es/vertical`, `en/horizontal`, `en/vertical`: final MP4, SRT, ASS, JPG preview and per-clip JSON manifest.
- `projects/<language>/<format>/`: native FilmCraft `.fcproj` projects with a clean master and editable caption track. Keep the adjacent `-base.mp4` with the project.
- `../sources/promo_plan.py`: bilingual copy and shot selection.
- `estante-qt-legacy/tools/record_promos.py`: reproducible isolated Qt recording.
- `../sources/render_promos.py`: reproducible composition and encoding.

FilmCraft CLI 0.13.0 imported the masters and created native sequences/caption tracks. Saved-project loading and a sample render were verified. FFmpeg composed and encoded the final MP4 files. Cards and headings are baked into the clean master; native captions retain editable text and timing. To change the montage or cards, edit the plan/script and regenerate the master. The master is not presented as a native sequence containing every original cut or text layer. Caption appearance may vary slightly when re-exporting through another renderer; delivered MP4 files are the visual reference.

Rebuilding requires Qt, FFmpeg, Pillow, actual Noto Sans Regular/Bold fonts and the FigCraft/FilmCraft CLIs. AppImages were temporarily extracted under `.artcraft-work/`, without installation or global configuration changes; that directory is excluded from delivery packages.

## Sources and verification

The real library is copied into temporary profiles. Byte comparisons verify that the original `library.json` and `settings.json` do not change. No game, update, import or purchase is executed. Color uses default pastel mode and the standard Qt Fusion palette without the personal qt6ct theme. Square cover corners avoid an unsupported software-renderer mask. Game artwork remains third-party material; this delivery does not grant rights to that artwork.

Every MP4 is fully decoded, and duration, dimensions, frame rate and absence of audio are checked. Every SRT has four segments aligned to the four shots. Visual QA samples all four shots of each video, representative openings/endings and both languages’ static designs. This sampling is not a claim that all 800 seconds were manually watched. Native projects retain relative master paths; a saved-project frame render is checked. Technical records are in `verification.json` and the per-clip JSON files.

These are proposed digital formats, not platform-specific compliance guarantees. Nothing was published. Bilingual static identity assets are in `../es/` and `../en/`. Open `../index.es.html` or `../index.en.html` for the galleries.

Portrait revision: removed the enlarged duplicate view following user feedback; rebuilt all 20 portrait clips, clean masters, native projects, previews, manifests and ES/EN packages.
