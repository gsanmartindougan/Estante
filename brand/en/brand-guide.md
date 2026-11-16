# Estante · Visual identity

Version 2.0 · 28 October 2026 · **Proposed identity; bilingual production**.

## Context and creative direction

Observed facts: Estante is a Linux game library. The project README describes imports from Steam, Faugus and Heroic, local shell scripts and AppImages, gamepad/keyboard/mouse navigation, and four layouts: List, Grid, Carousel and Sense. The documented release is 0.3.0. The distributed icon is a blue and white bookshelf; product images focus on game covers with configurable backgrounds.

Inferred audience: people organizing games from several sources on Linux. Proposed personality: approachable, orderly and restrained. These are creative assumptions, not audience research findings or approved positioning.

Recommended direction: **Night library**. Dark backgrounds leave room for game artwork, blue continues the existing identity, and a shelf motif relates the name to collection organization. **Light catalog**, shown on the identity board, is an editorial alternative for guides and documentation. This does not prescribe a fixed application theme: Estante remains customizable.

Proposed English tagline: **“Your library. Your next game.”** Spanish counterpart: “Tu biblioteca. Tu próxima partida.” Descriptor: “A game library for Linux.” Use short, concrete sentences. Avoid universal compatibility claims, unsupported performance numbers or implied endorsements by game stores.

## Palette

The existing icon is raster artwork inside an SVG wrapper, with varied pixel colors. `#0B91FF` is the modal opaque blue sample, not an exact flat fill for the entire original. White is also present in the icon. Other colors are proposed system colors; the darker blue is a proposed accessibility variant.

| Token | HEX | RGB | Role |
| --- | --- | --- | --- |
| ink | #101923 | 16, 25, 35 | Primary background; text on original blue |
| panel | #192638 | 25, 38, 56 | Cards and plates |
| blue | #0B91FF | 11, 145, 255 | Identity, selection, dark-context accent |
| blueLight | #0067BD | 0, 103, 189 | Accessible blue for light backgrounds |
| paper | #F4F7FB | 244, 247, 251 | Main text; light editorial background |
| muted | #AAB8C9 | 170, 184, 201 | Secondary text on dark surfaces |
| border | #667D96 | 102, 125, 150 | Functional outlines |
| white | #FFFFFF | 255, 255, 255 | Text on dark blue |

The name `blueLight` means “blue for light contexts,” not higher luminance. Suggested dark-piece distribution: 75% background/surfaces, 20% text/light space, 5% blue. This is composition guidance, not a rule for game artwork.

Contrast is calculated from linearized sRGB luminance: `(lighter + .05)/(darker + .05)`.

| Foreground / background | Ratio | Use |
| --- | --- | --- |
| paper / ink | 16.49:1 | Normal text |
| paper / panel | 14.21:1 | Normal text |
| muted / ink | 8.78:1 | Normal text |
| muted / panel | 7.57:1 | Normal text |
| blue / ink | 5.49:1 | Normal text and links |
| ink / blue | 5.49:1 | Primary dark-context button |
| blueLight / paper | 5.32:1 | Normal text on light backgrounds |
| white / blueLight | 5.71:1 | Light-context button |
| white / blue | 3.23:1 | Avoid for normal text |
| blue / paper | 3.00:1 | Avoid for normal text |

Border contrast: 3.59:1 against panel, 4.17:1 against ink. Use it for control boundaries, not small text. A panel fill alone does not sufficiently distinguish an interactive boundary. Never communicate state only by color. Put text over a stable plate when background imagery varies. These checks do not certify the entire application’s accessibility.

## Typography

Use **Noto Sans**, Regular 400 and Bold 700, actual installed files version 2.015. Both were rendered in FigCraft; coverage of Spanish accents, ñ, punctuation and digits was checked in font metadata and the identity board. No claim is made that the original icon used this font.

SIL OFL 1.1 was checked in the TTF metadata and the [official Noto license](https://github.com/notofonts/latin-greek-cyrillic/blob/main/OFL.txt), accessed 28 October 2026. The distribution’s generic license file says Apache, so the specific license embedded in these font files takes precedence in this record. Font binaries are not bundled or installed by this production. Editing on another machine requires the actual Regular and Bold fonts; review line breaks after substitution.

| Role | Size / line height | Weight |
| --- | --- | --- |
| Landscape headline | 100 / 124 px | 700 |
| Square headline | 92 / 114 px | 700 |
| Identity-board headline | 72 / 89 px | 700 |
| Product headline | 58 / 72 px | 700 |
| Body | 28 / 35 px | 400 |
| Editorial label | 18 / 22 px | 700 |
| Product caption | 20 / 25 px | 400 |

These sizes refer to export canvases, not implemented interface sizes. Square-ad body is 32/40 px. Left-align headlines; limit to three lines, about 28 characters per landscape line or 20 in a square. Preserve natural letter spacing; do not fake weights or compress letters.

## Icon, signature and composition

The existing icon is preserved. The proposed signature combines it with “Estante” in Noto Sans Bold and the tagline in Regular. Do not stretch, tilt, recolor, dismantle or redraw the icon. On light backgrounds, use an ink plate so the original white shapes remain visible.

Clear space: at least one quarter of icon width, measured from visible pixels. Small compositions use a 104–108 px icon box with a 20 px name gap; the original image contains internal transparent margins. Proposed minimum icon box: 96 px wide; full signature: 500 px wide. Below this size, use the typographic name in communications. The original has transparency irregularities; optimizing desktop icons for 16–48 px is a separate task and has not been done here.

Base spacing unit: 8 px; steps 8, 16, 24, 32, 48, 64, 72, 96. Standard margins: 64 px, or 72 px on the cover. Reference grid: 12 columns, 24 px gutters. Card radius 16 px, chip 14 px, motif 12 px.

The shelf motif uses four explicit rectangular spines resting on a line. It is a decorative editorial device, not an alternative logo. Use it once per composition. The signature, editorial label, origin card and screenshot frame are editable layers; native FigCraft component instances and global styles were not created.

Use real, proportional product captures. Do not recolor the application or invent features. Game covers and third-party marks are not Estante-owned artwork and must not be extracted as standalone advertising resources. Their use here demonstrates the product; no advertising license is inferred. Typographic pieces avoid dependence on third-party artwork.

Specific errors to avoid: small white text on original blue; original-blue body text on paper; a white icon on an unplated light surface; substituting decorative spines for the icon; presenting a mockup as an implemented theme; implying store endorsement.

## Produced assets

| Asset | Canvas | Files |
| --- | --- | --- |
| Identity board, A/B directions | 1600 × 1200 | `exports/01-identidad.png`, `.svg` |
| Landscape cover | 1600 × 900 | `exports/02-portada.png`, `.svg` |
| Square announcement | 1080 × 1080 | `exports/03-anuncio.png`, `.svg` |
| Real product capture | 1600 × 1320 | `exports/04-producto.png`, `.svg` |
| Signature on dark plate | 1000 × 280 | `exports/05-firma.png`, `.svg` |

Native source: `sources/estante-identity.figcraft`. SVG typography is outlined and the icon is an embedded raster; edit the text in FigCraft. PNGs are RGB/RGBA for sRGB digital use, without an embedded ICC profile. Canvas sizes are editorial choices, not promises about a specific social platform’s crop.

English application captures use the application’s existing English language setting. Some built-in labels remain Spanish in the current application, and game metadata remains in its stored language. Promotional copy, titles, guide and subtitles are fully localized; untranslated application labels have not been fabricated or silently painted over.

The product capture uses List, default pastel color mode and Qt Fusion’s standard palette (`window #EFEFEF`, `accent #308CC6`), without the user’s qt6ct theme. Square cover corners are a real per-view setting used to avoid the software renderer’s unsupported rounded mask. Launcher command details are hidden for presentation. Captures use a temporary profile and verify that the original library/settings do not change. No game, launcher, remote import or update is executed by the recording workflow.

For reuse: duplicate a native frame, replace its text layers and maintain line limits. Replace product captures with genuine 16:9 images in the 1408 × 792 region; update version/caption. Review the signature after changing the tagline. Tokens do not live-link to native layers: update the JSON and rebuild with `../sources/build_brand.py --language en` when changing colors.

## Provenance and verification

Original icon: `../../packaging/io.github.estante.Launcher.svg`, copied into `../originals/`; PNG extracted without retouching. Author/license were not specified in the supplied resource. English capture: `../originals/estante-list-default-en.png`, captured from the real Qt app. Game images and marks retain third-party ownership. Noto fonts: system-installed files, unmodified, not redistributed. Text, geometry, layout and system decisions were created for this commission without generative media.

Tools actually used: FigCraft CLI 0.11.2 for native design/export; Qt for real captures; FilmCraft CLI 0.13.0 for caption projects; FFmpeg for video layout and final encoding. PhotoCraft was unnecessary. The graphical editor UI was not inspected. No publication, installation or global configuration change was performed.

PNG/SVG exports are inspected, SVG XML is validated, native files are checked for missing fonts, and calculated contrasts are persisted in `brand-tokens.json`. Video verification, scope, timing and limitations are documented in `../promo/README.en.md`.

Change history: 1.0 initial system; 1.1 Grid/theme capture replaced with default-color List; 1.2 cover restored using square-corner capture settings; 2.0 bilingual static deliverables and promotional production. Spanish capture was accepted by the user (“Vale perfecto”); new English adaptations and videos remain reviewable deliverables, not separately approved artwork.
