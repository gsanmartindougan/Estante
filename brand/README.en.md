# Estante · Current brand and publication assets

[Español](README.md)

This folder contains the current Spanish and English versions. Portrait videos show one complete application window, without the duplicated enlarged view. Nothing has been published or scheduled on social media.

## Using the assets

| Content | Location |
| --- | --- |
| Spanish gallery | [index.es.html](index.es.html) |
| English gallery | [index.en.html](index.en.html) |
| Spanish identity and images | [es/](es/) |
| English identity and images | [en/](en/) |
| Spanish videos and captions | [promo/es/](promo/es/) |
| English videos and captions | [promo/en/](promo/en/) |
| Final LinkedIn posts | [social/linkedin/](social/linkedin/) |

Each language has five PNG/SVG brand designs and twenty 20-second clips: ten topics in landscape and portrait. LinkedIn contains three posts per language, with copy and matching media.

## Editing or rebuilding

- `es/sources/`, `en/sources/`: native FigCraft identity projects.
- `promo/projects/`: FilmCraft projects and clean masters. Keep each `.fcproj` beside its `-base.mp4`.
- `promo/media/`: original recordings needed to rebuild the videos.
- `originals/`: original icon and product captures used in the designs.
- `sources/`: current scripts and provenance record. `brand-tokens.json` supplies the builder palette; the language folders retain localized tokens.
- `promo/qa/`, `promo/verification.json`, `promo/qa-summary.json`: current delivery checks.

LinkedIn media and editable sources are relative links to the current canonical files, avoiding copies that could become outdated. They remain accessible from each post folder. See [social/linkedin/README.en.md](social/linkedin/README.en.md) for posting instructions.

Earlier drafts, duplicate Spanish exports, old ZIPs and extracted copies of earlier deliveries have been removed. No compressed archives duplicate the entire folder.

Refresh the galleries:

```sh
python brand/sources/package_delivery.py
```

Create one current bundle when needed for sharing:

```sh
python brand/sources/package_delivery.py --output /tmp/estante-brand-current.zip
```

The ZIP includes both languages, posts and required sources. Resource links are included as files to make the bundle portable.
