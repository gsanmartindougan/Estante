# Estante · Identidad visual

Versión 2.0 · 28 de octubre de 2026 · **Propuesta, pendiente de aprobación**.

## Punto de partida y dirección

Hechos observados: el README describe una biblioteca de juegos para Linux que reúne Steam, Faugus, Heroic, scripts y AppImages; admite mando, teclado y ratón y ofrece Grid, Carousel, Sense y Lista. La versión documentada es 0.3.0. El icono distribuido representa una estantería azul y blanca. Las capturas muestran carátulas como contenido principal y fondos adaptables a cada juego.

Público inferido: personas que juegan en Linux y organizan juegos de distintos orígenes. Personalidad propuesta: cercana, ordenada y sobria. No son atributos aprobados ni resultados de investigación de audiencia.

Dirección recomendada: **Biblioteca nocturna**. El fondo oscuro deja espacio a las carátulas; el azul continúa la identidad existente; la geometría de baldas relaciona el nombre con la organización de la colección. Es una decisión de composición, no una atribución psicológica universal al color. **Catálogo claro**, mostrado en el panel de identidad, sirve como variante editorial para guías y documentación; mantiene la misma familia y emplea azul oscuro accesible. La elección no presupone un tema fijo para la aplicación, que sigue siendo personalizable.

Lema propuesto: **«Tu biblioteca. Tu próxima partida.»** Describe colección y uso sin prometer compatibilidad universal. Texto descriptivo: «Una biblioteca de juegos para Linux». Voz: frases breves, segunda persona, vocabulario cotidiano. Usar «Reúne tus juegos»; evitar «todos tus juegos sin límites», afiliaciones a tiendas o cifras sin respaldo.

## Colores y contraste

Los originales contienen variaciones raster, no rellenos vectoriales planos. `#0B91FF` es la muestra de azul opaco más frecuente al filtrar los píxeles azules del icono, no una equivalencia exacta de todo el original. El blanco `#FFFFFF` también está presente. Los demás colores son propuestas. El SVG original es un contenedor de imagen raster; no se presenta como un logo vectorial redibujado.

| Token | HEX | RGB | Función |
| --- | --- | --- | --- |
| ink | #101923 | 16, 25, 35 | Fondo y texto sobre azul |
| panel | #192638 | 25, 38, 56 | Tarjetas y placas |
| blue | #0B91FF | 11, 145, 255 | Acento y selección en oscuro |
| blueLight | #0067BD | 0, 103, 189 | Variante accesible para fondos claros |
| paper | #F4F7FB | 244, 247, 251 | Texto principal y fondo editorial |
| muted | #AAB8C9 | 170, 184, 201 | Texto secundario en oscuro |
| border | #667D96 | 102, 125, 150 | Contornos funcionales |
| white | #FFFFFF | 255, 255, 255 | Texto sobre azul oscuro |

`blueLight` nombra la variante para **contexto claro**, no una mayor luminosidad.

Contraste calculado con luminancia sRGB linealizada y `(Lmayor + .05)/(Lmenor + .05)`. Cifras redondeadas a dos decimales; valores precisos y umbrales en los tokens.

| Texto / fondo | Ratio | Uso |
| --- | --- | --- |
| paper / ink | 16.49:1 | Texto normal |
| paper / panel | 14.21:1 | Texto normal |
| muted / ink | 8.78:1 | Texto normal |
| muted / panel | 7.57:1 | Texto normal |
| blue / ink | 5.49:1 | Texto normal y enlaces |
| ink / blue | 5.49:1 | Botón primario en oscuro |
| blueLight / paper | 5.32:1 | Texto normal y enlaces en claro |
| white / blueLight | 5.71:1 | Botón primario en claro |
| white / blue | 3.23:1 | Evitar texto normal; usar ink |
| blue / paper | 3.00:1 | Evitar texto normal; usar blueLight |

Los contornos `border` tienen 3.59:1 sobre panel y 4.17:1 sobre ink; sirven para identificar controles, no para texto pequeño. Los paneles solos no bastan para distinguir controles interactivos: añadir borde si el contorno es necesario. El motivo de baldas es decorativo.

Distribución orientativa para piezas oscuras: 75 % fondo y panel, 20 % texto y espacios claros, 5 % azul. No aplicar esta proporción a capturas o carátulas. Los estados necesitan etiqueta, icono o contorno además de color. Sobre fotografías, colocar texto en placa estable y verificar esa pareja.

## Tipografía

**Noto Sans**, una sola familia; Regular 400 y Bold 700 reales, instalados y usados en FigCraft. Versión local 2.015. Prueba de cobertura de tildes, ñ, signos españoles, cifras y nombres en `sources/resource-checks.json`; el panel muestra la fuente real, no una aproximación. No se atribuye esta fuente al dibujo original del icono.

Licencia SIL OFL 1.1 comprobada en metadatos de ambos TTF y en el [archivo oficial de Noto](https://github.com/notofonts/latin-greek-cyrillic/blob/main/OFL.txt), consultado el 28/10/2026. La licencia genérica de la distribución local indica Apache; se ha usado la declaración específica embebida en los archivos. No se redistribuyen ni instalan fuentes. Para editar en otro equipo se necesitan Noto Sans Regular y Bold; verificar licencia de la copia obtenida y revisar saltos si se sustituye.

| Rol / pieza | Tamaño / interlineado | Peso |
| --- | --- | --- |
| Titular de portada horizontal | 100 / 124 px | 700 |
| Titular cuadrado | 92 / 114 px | 700 |
| Titular del panel de identidad | 72 / 89 px | 700 |
| Título de producto | 58 / 72 px | 700 |
| Cuerpo habitual | 28 / 35 px | 400 |
| Etiqueta editorial | 18 / 22 px | 700 |
| Pie de pieza de producto | 20 / 25 px | 400 |

Los tamaños corresponden al lienzo exportado, no a una interfaz implementada. Cuerpo de anuncio: 32/40 px. Titulares: máximo tres líneas; unos 28 caracteres por línea en horizontal y 20 en cuadrado. Alineación izquierda. Interletraje natural. No simular pesos ni comprimir caracteres.

## Firma, retícula e imagen

Se conserva el icono suministrado. La firma añade «Estante» en Noto Sans Bold y el lema en Regular. No separar las partes del dibujo, inclinarlo, recolorearlo, estirarlo ni recrearlo con el motivo decorativo. En claro, usar una placa ink porque los elementos blancos perderían visibilidad.

Área libre: al menos un cuarto del ancho del icono, medido desde sus píxeles visibles. En las composiciones pequeñas el icono ocupa 104–108 px de caja y la separación del nombre es 20 px; el lienzo original incluye espacio transparente interno. Mínimo de uso propuesto: caja del icono de 96 px de ancho y firma completa de 500 px. Por debajo, usar el nombre tipográfico en comunicaciones. La optimización del icono de escritorio a 16–48 px requeriría un trabajo específico: el original presenta irregularidades y residuos en su transparencia. Aquí no se sustituye el icono de la app.

Unidad espacial de 8 px; pasos 8, 16, 24, 32, 48, 64, 72 y 96. Márgenes base 64 px, portada 72 px. Retícula de referencia: 12 columnas con calles de 24 px; motivos y composiciones pueden ocupar varias columnas. Radios: tarjetas 16 px, chips 14 px, motivo 12 px. Evitar contenedores innecesarios.

Motivo: cuatro lomos de altura variable apoyados en una línea horizontal. Es geometría explícita y editable, no un icono alternativo. Usarlo una vez por composición y mantener espacio para el titular. Componentes de referencia: firma, etiqueta editorial, tarjeta de origen y marco de captura. Son capas editables en el nativo; no se han creado instancias vinculadas ni estilos globales de FigCraft.

Imágenes: capturas reales y completas, proporción conservada, sin recolorear la interfaz ni inventar funciones. Las carátulas pertenecen a los juegos mostrados y no son activos propios de Estante. No extraerlas para construir anuncios independientes. La captura se usa para mostrar el producto; no se presupone licencia publicitaria de esos materiales. Las composiciones tipográficas permiten comunicar la marca sin depender de esas carátulas.

Errores concretos: blanco pequeño sobre el azul original; azul original como texto sobre papel; logo blanco sobre fondo claro; sustituir el icono por los lomos decorativos; reutilizar una captura como si mostrara un tema nuevo ya implementado; presentar Steam, Faugus o Heroic como patrocinadores.

## Archivos producidos

| Pieza | Dimensiones | Exportaciones |
| --- | --- | --- |
| Panel de identidad y comparación A/B | 1600 × 1200 | `exports/01-identidad.png`, `.svg` |
| Portada horizontal | 1600 × 900 | `exports/02-portada.png`, `.svg` |
| Anuncio cuadrado | 1080 × 1080 | `exports/03-anuncio.png`, `.svg` |
| Presentación con captura real | 1600 × 1320 | `exports/04-producto.png`, `.svg` |
| Firma horizontal con placa oscura | 1000 × 280 | `exports/05-firma.png`, `.svg` |

Dimensiones de composición propuestas, sin garantía de recorte para una plataforma concreta; no se ha encargado un canal ni se ha publicado nada. PNG RGB/RGBA para uso digital en sRGB; sin perfil ICC incrustado. Los SVG contienen curvas para la tipografía y el icono raster embebido: son portables, pero **el texto se edita en el nativo**, no como texto SVG.

Fuente nativa: `sources/estante-identity.figcraft`, con cinco frames, texto, formas y medios embebidos. FigCraft CLI 0.11.2, ejecutada desde extracción temporal local de la AppImage; no se ha usado ni inspeccionado el editor gráfico. No fueron necesarios PhotoCraft ni FilmCraft. Para la versión localizada ejecutar con `--language es`. Script reproducible: `../sources/build_brand.py`; necesita FigCraft y las fuentes instaladas, lee colores de `brand-tokens.json`. No incluye ejecutables de la suite.

Para reutilizar: abrir el nativo en FigCraft, duplicar el frame, sustituir titular y descripción en sus capas, mantener los límites de línea y exportar el frame. Esta captura es un registro histórico de la versión Qt: usa Lista con las opciones visuales por defecto, paleta Qt Fusion (`window #EFEFEF`, `accent #308CC6`) y modo `pastel`. El tema de qt6ct se desactivó solo para la captura. El render se obtuvo de la app Qt real, no de una recreación. El grabador quedó archivado en `estante-qt-legacy/tools/record_promos.py`; usa un perfil temporal y comprueba que biblioteca y ajustes originales no cambian. El registro está en `../promo/media/es/recording.json`.

Para la captura usar otra captura real 16:9 en el área de 1408 × 792; actualizar versión y pie. Para cambiar el lema, revisar la firma completa y el ancho de línea. Si cambia la paleta, actualizar tokens y reconstruir con el script; las capas nativas no están enlazadas automáticamente al JSON.

## Procedencia y estado

| Recurso | Procedencia | Modificación / situación |
| --- | --- | --- |
| Icono | `packaging/io.github.estante.Launcher.svg` | Copia en originals; PNG extraído de la imagen embebida sin retoque. Autor/licencia no indicados en el recurso recibido. Uso interno del proyecto. |
| Captura Lista | `../originals/estante-list-default.png` | Captura nueva de la app real a 1920 × 1080; modo Lista y Tonos pastel predeterminados. Paleta estándar Fusion sin tema qt6ct. Reescalado proporcional, sin recolorear. Carátulas y marcas de terceros. |
| Fuentes | `/usr/share/fonts/noto/NotoSans-{Regular,Bold}.ttf` | Instaladas; sin modificación ni redistribución. Noto Project Authors; OFL 1.1. |
| Formas, retícula, textos y sistema | Creados para este encargo | Propuesta nueva, sin imágenes generativas. |

Identificadores SHA-256 y cobertura tipográfica: `sources/resource-checks.json`. El contenido funcional se apoya en el README local leído el 28/10/2026.

Verificación: cinco PNG abiertos e inspeccionados a resolución completa con herramienta de imagen; jerarquía, tildes, márgenes, transparencia del icono y captura completa revisados. Versiones reducidas verificadas a 400 px para portada y 360 px para anuncio: el mensaje principal conserva legibilidad; pies y etiquetas son información secundaria y no deben concentrar el mensaje. SVG validados como XML; el inspector del nativo informa de cero fuentes perdidas y dos medios embebidos. Contrastes calculados y tokens contrastados con la fuente de composición. No se afirma certificación de accesibilidad del producto completo.

Registro: 1.0 — creación de la propuesta, conservación del icono y separación entre original, nativo y exportaciones. Ninguna decisión se registra como aprobada. Los cambios están limitados a `brand/`.

1.1 — A petición del usuario, sustitución de Grid con tema Qt personal por una captura real de Lista con Tonos pastel y paleta Qt estándar. Actualizados nativo, exportaciones, procedencia y paquete. La identidad sigue propuesta.

1.2 — Corregida la captura: la máscara MultiEffect de esquinas redondeadas no mostraba la carátula con el renderizador software. Se usa el ajuste real `cover_radii.list = 0` en el perfil temporal de captura; colores predeterminados conservados. Carátula de Bloodborne comprobada visualmente en la captura y pieza final.

2.0 — Producción bilingüe: identidad y cinco piezas en `es/` y `en/`; diez temas promocionales por idioma y dos formatos, con subtítulos integrados y SRT. Ver `promo/README.es.md` y la galería `index.es.html`. La interfaz inglesa actual conserva algunas etiquetas internas en español; no se han retocado para simular una traducción inexistente.
