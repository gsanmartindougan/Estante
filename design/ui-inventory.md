# Inventario UI · referencia visual

Documento de referencia FigCraft, no inventario del estado actual de implementación. La interfaz principal del proyecto usa Slint; los ajustes de Lista actuales se distribuyen en tarjetas independientes. FigCraft: «Ajustes List · propuesta completa» (`1a2089d34bd`); preview `previews/rust-ui/list-settings.png`.

| Pieza | Uso | Estilo y tokens | Variantes y estados | Tamaño revisado | Interacción / movimiento |
| --- | --- | --- | --- | --- | --- |
| Fondo de juego | Las cuatro vistas | Ejemplo existente `assets/backgrounds/3.png`; velo `ink` #101923 y superficie `panel` #192638 | Sala: velo `ink` 72%; Editorial: velo 36% más placa `panel` 42% | Zona superior; 1920×1080 y Grid compacto 1280×720 | Estático; capa de lectura distinta por dirección |
| Ficha seleccionada y carátula | Las cuatro vistas, arriba | Título `paper`, metadatos `muted`, mock editable | Normal, carga, fallo de carátula | 246×338 desktop; 154×214 compacto | Cambia con selección; conserva título si falta recurso |
| Foco y ficha | Todas las apariencias de biblioteca | `blue` #0B91FF | C elegida: placa inferior azul sin borde; selección y metadatos flotan sobre el arte sin paneles opacos. Las carátulas sin foco quedan lisas. | Grid, Lista, Carrusel y Sense | La placa sigue la transición de foco existente. Bloodborne usa recurso existente recortado; vecinos tipográficos ilustrativos por falta de carátulas independientes. |
| Banda de juegos | Las cuatro vistas, bajo divisor | Superficies `panel`; selección `blue` y texto `ink`; borde `border` | Lista: fila; Grid: 3×2 o 2×2 compacto; Carrusel: selección central; Sense: selección anclada izquierda | 1920×1080 y 1280×720 | Navegación y foco anotados; no probados en dispositivo |
| Footer de mando | Todas las vistas de biblioteca; acciones principales | Barra `ink`; botones circulares A verde, X azul, LB/RB pizarra, Y amarillo, B rojo; etiquetas `paper` | Cinco grupos siempre visibles | Fijo al pie | Mapeo implementado: A Detalles, X Jugar, LB/RB Categoría, Y Menú, B Salir; Enter/Espacio/Ctrl+M para teclado |
| Menú Y | Opciones secundarias en una capa | Panel `panel`, fondo oscurecido | Buscar, Categorías, Apariencia/vista, Ajustes, Añadir/editar | Overlay adaptativo | Acciones conectadas; reproducción visual no verificada por permiso de escritorio |
| Estados comunes | Muestra de interacción | Selección azul con texto y borde; estados con etiquetas | Normal, foco, carga, vacío y error | Página «Estados», desktop | El color no es el único indicador; acciones muestran foco/deshabilitado |
| Lanzar juego | Barra inferior | Usa el flujo existente de lanzamiento y seguimiento de sesión | Disponible cuando hay juego seleccionado | Barra fija | X/Espacio conectados; no se lanzó ningún juego durante la captura |
| Ajustes de apariencia · Lista | Frame «Ajustes · Lista · apariencia · propuesta» | Tarjetas independientes con borde, fondo y radio propios | Grupos funcionales con radios, controles numéricos, checks y entrada de color | 1436×1368, tamaño de la captura | Navegación de teclado y mando descrita en la referencia |

## Identidad consultada

`brand/es/brand-tokens.json`, versión 2.0.0, estado `proposed`: roles `ink`, `panel`, `blue`, `paper`, `muted` y `border`. La paleta orienta la maqueta, no fija el tema de la aplicación. Noto Sans regular/bold según guía. Títulos y mock art son ejemplos editables, no recursos de producto.

## Compatibilidad de mando

En `rust/src/controls.rs`, SDL asigna A a detalles, X a jugar, LB/RB a cambiar categoría, Y al menú y B a salir/volver según contexto. Los gatillos mantienen navegación de categoría. Menú, categoría y acciones secundarias están conectados en `rust/src/main.rs`.
