# Interfaz · referencia visual

Referencia visual editable en FigCraft, revisión nativa 6. No describe el estado actual de implementación; la interfaz principal actual usa Slint. Editable: [`estante-interface.figcraft`](estante-interface.figcraft).

## Alcance y direcciones

La exploración visual organiza fondo de juego, carátula y ficha en la zona superior; juegos en franja inferior-media; y una única barra de controles al pie. El selector de modo y las acciones duplicadas del encabezado se quitaron.

- **A · Sala inmersiva**: fondo existente `assets/backgrounds/3.png` en zona superior, con velo `ink` al 72%; ficha/carátula a la izquierda y detalle al lado; banda debajo.
- **B · Balda editorial**: conserva la misma jerarquía; fondo existente bajo velo `ink` al 36% y placa `panel` al 42%; superficies y separadores planos.
- Ambas reutilizan roles de `brand/es/brand-tokens.json`; no fijan un tema de aplicación.

## Páginas y marcos

- «00 · Portada y revisión»: resumen de alcance y direcciones.
- «01 · Dirección Sala»: A Lista, Grid, Carrusel y Sense a 1920×1080; A Grid compacto a 1280×720.
- «02 · Dirección Editorial»: B Lista, Grid, Carrusel y Sense a 1920×1080; B Grid compacto a 1280×720.
- «03 · Catálogo, estados y movimiento»: catálogo, muestras de normal/foco/carga/vacío/error, guía de movimiento, confirmación visual y el frame «Foco · 3 propuestas · 1920×1080».
- La misma página incluye `Menú Y · escritorio 1920×1080` y `Menú Y · compacto 1280×720`, con Buscar, Categorías, Apariencia/vista (Lista, Grid, Carrusel, Sense), Ajustes y Añadir/editar.
- También incluye «Ajustes · Lista · apariencia · propuesta» a 1436×1368, en el tamaño de la captura de referencia. Revisión FigCraft nativa: «Ajustes List · propuesta completa» (`1a2089d34bd`); diseño aprobado, implementación agrupada revertida a las tarjetas independientes anteriores. Preview de referencia: [`list-settings.png`](previews/rust-ui/list-settings.png).

## Ajustes de apariencia · Lista

Frame «Ajustes · Lista · apariencia · propuesta», página «03 · Catálogo, estados y movimiento», 1436×1368. Reproduce el shell visible en la captura suministrada y reúne los ajustes en una sola superficie, con tres grupos y divisores. **Disposición y fondos**: List position (Left/Right/Top/Bottom), Dimming (0–100%), Blur (0–40 px), Hero position (Full/Top/Bottom), Background split (Single/Horizontal/Vertical/Diagonal), Minimal presentation. **Arte y ficha**: Carousel artwork (Logos/Portrait covers 2:3/Square covers 1:1), Selected item zoom (100–250%), Carousel cover radius (0–40 px), Launcher details, Show game information, Show details cover, Details cover format (Portrait 2:3/Square 1:1/Logo), Details cover radius (0–40 px), Details cover size (50–175%). **Foco y selección**: Selection ring, Border color, Border width (0–12 px), Border radius (0–50 px).

Las opciones actuales de Lista están implementadas en `rust/ui/list.slint`, distribuidas en tarjetas independientes.

Lista presenta fichas en fila; Grid organiza seis juegos en 3×2; Carrusel centra la selección y escala vecinos; Sense fija la selección a la izquierda. El fondo, ficha y banda permanecen. El menú se abre desde Y; las opciones se muestran como destinos agrupados en esa capa.

## Barra inferior única y mapeo visual

En todas las apariencias de biblioteca, el footer oscuro es el lugar único para acciones principales. Cada control lleva etiqueta y botón circular coloreado: **A Detalles**, **X Jugar**, **LB/RB Categoría**, **Y Menú**, **B Salir**. Se quitaron controles superiores y acciones duplicadas de ficha. El menú Y contiene búsqueda, selector de categoría, apariencias, ajustes, añadir y editar. Ctrl+M abre/cierra el menú; Espacio juega y Enter abre detalles.

El mapeo implementado conecta A con detalles, X con jugar, LB/RB con categorías, Y con el menú y B con salir desde la biblioteca; B vuelve en subpantallas. En el teclado virtual, Y confirma.

## Escritorio compacto

Frames de escritorio, no móvil/tablet. A 1920×1080 se conserva ficha a dos columnas, banda amplia y footer de 88 px. A 1280×720 se muestra Grid compacto, carátula de 154×214, cuatro juegos y footer de 76 px; los cinco grupos mantienen etiqueta legible y LB/RB separado de «Biblioteca». El menú compacto usa filas horizontales y ocupa 1280×720. Entre tamaños cambia número visible de juegos, no el orden de prioridad. No depender de hover.

## Movimiento e interacción

| Transición | Disparador | Duración y curva | Interrupción / reducido | Estado de verificación |
| --- | --- | --- | --- | --- |
| Menú Y | Y o Ctrl+M; overlay con acciones agrupadas | Inmediato | Y/Ctrl+M cierra; movimiento reducido: instantáneo | Comportamiento descrito en la referencia |
| Cambiar apariencia | Elegir Lista/Grid/Carrusel/Sense desde el menú | 180 ms, transición existente | Interrumpible; movimiento reducido instantáneo | Comportamiento descrito en la referencia |
| Cambio de juego/categoría | Flechas, cruceta, rueda; LB/RB recorren categorías | Inmediato | Repetible; foco visible | Comportamiento descrito en la referencia |
| Carga de carátula | Llega recurso | Sin entrada decorativa | Skeleton no mueve composición | Estado de muestra |
| Jugar | X o Espacio | Comportamiento de lanzamiento existente | Se mantiene la gestión de sesión actual | Código conectado; no se lanzó un juego durante la captura |

El `.figcraft` conserva las propuestas A/B como referencia visual. La captura se hizo con datos temporales para no modificar la biblioteca del usuario.

## Propuestas de foco de carátula

Frame editable «Foco · 3 propuestas · 1920×1080», en la página «03 · Catálogo, estados y movimiento». Se eligió C: una placa azul bajo la carátula enfocada, sin borde. A y B quedan como alternativas de referencia, no como estados activos. La placa se aplica en Lista, Grid, Carrusel y Sense; las carátulas sin foco quedan lisas. Fichas y textos flotan sobre el arte, sin superficies opacas que lo corten.

La carátula de Bloodborne procede de un recorte del recurso existente `brand/originals/estante-list-default.png`. Los vecinos son muestras tipográficas porque no hay carátulas independientes en el catálogo local. Preview: `design/previews/rust-ui/cover-focus-proposals.png`. Snapshot previo conservado en el historial nativo: «Antes de propuestas de foco» (`1a1d63060d6`).

## Ejemplos y límites

Títulos y datos son ilustrativos. La carátula está hecha con capas nativas editables, no es arte de juego. El fondo es el recurso existente `assets/backgrounds/3.png`, no una captura de juego; se recorta en modo cubrir y permanece incrustado en el FigCraft. Se conserva la animación/movimiento como especificación, no como comportamiento verificado en la aplicación.

El `.figcraft` canónico sigue disponible como referencia visual.
