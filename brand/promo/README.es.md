# Estante · Clips promocionales

Entrega bilingüe · 28 de octubre de 2026.

**40 MP4: 10 temas × español/inglés × horizontal/vertical.** Todos duran 20 segundos y tienen subtítulos integrados, además de SRT UTF-8 y ASS separados. Vídeo H.264, 24 fps, píxel cuadrado, YUV 4:2:0 y señalización BT.709. Horizontal: 1920 × 1080; vertical: 1080 × 1920. Sin locución ni música añadidas.

## Serie

| Nº | Tema | Contenido |
| --- | --- | --- |
| 01 | Presentación | Biblioteca para Linux, orígenes, navegación y apariencias |
| 02 | Reúne tus juegos | Steam/Faugus/Heroic, scripts, AppImages, argumentos y arranque de launchers |
| 03 | Organización | Búsqueda, categorías, paginación y salto por inicial |
| 04 | Apariencias | Lista, Grid, Carousel y Sense |
| 05 | Personalización | Fichas, sinopsis, carátulas, logos, selección y fondos |
| 06 | Controles | Idiomas, tipo de mando, teclado integrado, ratón y atajos |
| 07 | Actividad | Tiempo jugado, sesiones e historial por juego |
| 08 | Durante y entre partidas | Mantener abierto, cerrar/restaurar, bandeja y salvapantallas |
| 09 | Instalación y actualización | AppImage x86_64, dependencias incluidas y actualizaciones |
| 10 | Imágenes y fichas | SteamGridDB, IGDB, Wikidata, archivos locales y URL |

Las afirmaciones se basan en `README.md`, `README.en.md`, `RELEASE_NOTES.md` y `qt_app/settings_schema.py` del proyecto. Los clips son una presentación de las funciones principales: los pasos de instalación, la ejecución de juegos, las descargas y los imports reales no se escenifican ni se ejecutan. Se muestran sus formularios y ajustes reales, con subtítulos que explican la función. Los servicios externos pueden necesitar credenciales propias; los launchers necesitan estar instalados. No se promete compatibilidad universal ni resultados de rendimiento.

## Encuadre y subtítulos

El horizontal conserva la ventana completa en una placa de marca y sitúa los subtítulos fuera del área de la aplicación. El vertical muestra una única ventana completa de la aplicación, encajada proporcionalmente, con título y subtítulos fuera de la interfaz. No añade zoom, recortes ni vistas duplicadas, ni simula una pantalla móvil de Estante.

Dos segundos de apertura, cuatro planos de cuatro segundos y dos segundos de cierre. Cortes limpios; metraje a velocidad real. Las acciones, paneles y teclado se capturan en Qt. Las tarjetas son composición de texto, formas e icono existente; no hay imágenes ni vídeos generativos.

El texto promocional, los títulos y los subtítulos tienen versiones española e inglesa. La interfaz se graba con el idioma correspondiente. Algunas etiquetas internas de la versión actual de Estante siguen en español aun seleccionando inglés; los metadatos de juegos también conservan su idioma original. Se mantienen visibles como parte de la aplicación real, sin pintarlos encima ni atribuir una traducción inexistente al producto.

## Fuentes editables y reproducción

- `media/es/` y `media/en/`: grabaciones originales de las escenas, PNG de referencia y registros de captura. Se conservan sin retoque de color.
- `es/horizontal`, `es/vertical`, `en/horizontal`, `en/vertical`: MP4 finales, SRT, ASS, miniatura JPG y manifiesto JSON de cada clip.
- `projects/<idioma>/<formato>/`: proyectos `.fcproj` de FilmCraft con máster limpio y pista de subtítulos editable; junto a cada proyecto queda su vídeo `-base.mp4` necesario para abrirlo.
- `../sources/promo_plan.py`: textos y selección de planos de ambos idiomas.
- `../sources/record_promos.py`: captura aislada reproducible con Qt.
- `../sources/render_promos.py`: composición y codificación reproducibles.

FilmCraft CLI 0.13.0 importó los másteres y creó las secuencias y pistas de subtítulos nativas. Se verificó la apertura y el render de proyectos guardados. FFmpeg compuso y codificó los MP4 finales. Las tarjetas y rótulos están incorporados al máster; los subtítulos nativos sí conservan su texto y sus tiempos. Para cambiar el montaje o las tarjetas, modificar el plan/script y regenerar el máster. No se presenta el máster como una secuencia con todos los cortes y textos en capas nativas. La apariencia del subtítulo al volver a exportar desde otro motor puede variar ligeramente; los MP4 entregados son la referencia visual.

Ejecutar desde el proyecto con Qt, FFmpeg, Pillow, Noto Sans Regular/Bold y las CLI de FigCraft/FilmCraft disponibles. Las AppImages se extrajeron temporalmente en `.artcraft-work/`, sin instalación ni cambio de configuración global; esa carpeta no se incluye en los paquetes.

## Material y verificación

Grabaciones de la biblioteca real en perfiles temporales. Se comprueba por bytes que `library.json` y `settings.json` originales no cambian. No se lanzan juegos, actualizaciones, imports ni compras. Colores: modo pastel y paleta estándar Qt Fusion, sin el tema personal qt6ct. Se usan carátulas con esquinas rectas para evitar una máscara no soportada por el renderizador software. Las imágenes originales de los juegos conservan sus derechos de terceros; esta entrega no concede una licencia sobre ellas.

Cada MP4 se decodifica completo y se comprueban duración, resolución, fps y ausencia de audio. Cada SRT tiene cuatro segmentos, sincronizados con los cuatro planos. Se inspeccionan muestras de los cuatro planos de cada vídeo, aperturas/cierres representativos y los diseños estáticos de ambos idiomas. Este muestreo visual no equivale a reproducir manualmente los 800 segundos completos. Los proyectos nativos conservan rutas relativas a sus másteres; se verifica un render de muestra tras guardarlos. Datos técnicos: `verification.json` y JSON de cada clip.

Los formatos son composiciones propuestas para uso digital; no se ha verificado una plataforma concreta ni se ha publicado contenido. La identidad y las piezas estáticas también se entregan en `../es/` y `../en/`. Consulta las galerías `../index.es.html` y `../index.en.html`.

Revisión de verticales: retirada la segunda vista ampliada a petición del usuario; regenerados los 20 verticales, másteres limpios, proyectos nativos, miniaturas, manifiestos y paquetes ES/EN.
