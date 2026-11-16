# Estante · Marca y publicaciones actuales

[English](README.en.md)

Esta carpeta contiene las versiones actuales en español e inglés. Los vídeos verticales muestran una única ventana completa, sin la vista ampliada duplicada. No se ha publicado ni programado contenido en redes.

## Para usar los materiales

| Contenido | Ubicación |
| --- | --- |
| Galería en español | [index.es.html](index.es.html) |
| Galería en inglés | [index.en.html](index.en.html) |
| Identidad e imágenes en español | [es/](es/) |
| Identidad e imágenes en inglés | [en/](en/) |
| Vídeos y subtítulos en español | [promo/es/](promo/es/) |
| Vídeos y subtítulos en inglés | [promo/en/](promo/en/) |
| Publicaciones finales de LinkedIn | [social/linkedin/](social/linkedin/) |

Cada idioma tiene cinco diseños de marca en PNG/SVG y veinte clips de 20 segundos: diez temas en horizontal y vertical. LinkedIn contiene tres publicaciones por idioma, con texto y su recurso correspondiente.

## Para editar o reconstruir

- `es/sources/` y `en/sources/`: proyectos de identidad de FigCraft.
- `promo/projects/`: proyectos de FilmCraft y sus másteres limpios. Mantener cada `.fcproj` junto a su `-base.mp4`.
- `promo/media/`: grabaciones originales necesarias para reconstruir los vídeos.
- `originals/`: icono y capturas de producto originales utilizados en los diseños.
- `sources/`: scripts vigentes y registro de procedencia. `brand-tokens.json` es la paleta de entrada para el constructor; las carpetas de idioma conservan sus tokens localizados.
- `promo/qa/`, `promo/verification.json` y `promo/qa-summary.json`: comprobaciones de la última entrega.

Los recursos y editables de LinkedIn son enlaces relativos a los originales actuales, para evitar copias que puedan quedarse desactualizadas. Los archivos siguen accesibles dentro de cada publicación. Las instrucciones específicas están en [social/linkedin/README.es.md](social/linkedin/README.es.md).

Se han retirado los borradores previos, las copias españolas repetidas, los ZIP antiguos y las carpetas descomprimidas de entregas anteriores. No se conservan archivos comprimidos duplicando toda la carpeta.

Para actualizar las galerías:

```sh
python brand/sources/package_delivery.py
```

Para crear un único paquete actual cuando haga falta compartirlo:

```sh
python brand/sources/package_delivery.py --output /tmp/estante-brand-actual.zip
```

El ZIP incluye ambos idiomas, las publicaciones y las fuentes necesarias. Los enlaces a recursos se incluyen como archivos, para que el paquete sea portable.
