# Inventario de pantallas y apariencias de Estante Qt

Documento de referencia para rediseñar la interfaz con Gui. Describe la interfaz Qt implementada, sus variantes y estados; no propone todavía un diseño nuevo. El alcance es la aplicación Qt (`qt_app/`), no la versión GTK abandonada ni la implementación Rust.

## Mapa de pantallas

| Pantalla o estado | Cómo se abre | Qué contiene |
| --- | --- | --- |
| Biblioteca | Inicio normal | Fondo del juego seleccionado, una de cuatro apariencias y una barra única inferior con acciones, filtros, búsqueda, estado de lanzadores y utilidades. |
| Ajustes | Botón Ajustes / menú del mando | Panel modal con navegación lateral, contenido desplazable, estado de operaciones y botón Cerrar. |
| Añadir juego local | Botón Añadir juego | Formulario para registrar un ejecutable `.sh` o `.AppImage`. |
| Editor de juego | Acción Editar sobre un juego | Panel acoplado al borde derecho con ficha, imágenes, categorías, ejecución y actividad. |
| Teclado de Estante | Solicitud de texto si se usa el teclado integrado | Teclado virtual para mando, con ayuda de controles según el mando seleccionado. |
| Lanzamiento | Al iniciar un juego | Transición de la carátula seleccionada a una vista de carga con fondo y estado. |
| Jugando | Mientras el proceso del juego sigue activo | Vista simple con carátula, título y mensaje de restauración. |
| Salvapantallas | Tras el tiempo de inactividad configurado | Fondo a pantalla completa, con oscurecimiento configurable. |
| Bandeja del sistema | Al enviar Estante a la bandeja | Menú de sistema con «Abrir Estante» y «Salir». |

No hay una pantalla separada para cada operación de escaneo o actualización: se ejecutan desde Ajustes y muestran progreso o resultado allí mismo.

## Lenguaje visual común

- La ventana usa la paleta de Qt y el color de acento del sistema. «Tonos pastel» deriva superficies suaves del acento Qt; «Tema Qt» usa directamente colores de la paleta. El tinte rojizo, si aparece, puede venir de la personalización del sistema y no de un color fijo de Estante.
- El fondo de biblioteca puede usar el banner del juego (y un segundo fondo opcional), con división y posición configurables, desenfoque, oscurecimiento y relleno por desenfoque o color dominante. También puede elegirse un fondo global.
- El sistema de controles no es totalmente uniforme hoy: los botones de gestión son tipo píldora; los de edición y las acciones de la barra son rectángulos redondeados con borde. Campos, tarjetas y diálogos también tienen radios distintos. Hover, pulsación y foco cambian el relleno o el borde; el foco de mando debe seguir siendo visible a distancia. Gui puede unificar estos tratamientos durante el rediseño.
- Los botones principales llevan un icono vectorial del botón físico del mando junto a su texto. La forma del icono cambia entre Sony, Xbox y Nintendo según Ajustes.
- Las carátulas y tarjetas tienen radio configurable. La selección usa un anillo configurable (color, grosor y radio), un matiz de acento y una pequeña marca inferior.
- Los ajustes se presentan como tarjetas plegables en dos columnas. Campos, listas y resultados se desplazan dentro del panel, no en una pantalla independiente.

## Biblioteca: composición compartida

### Fondo y área de contenido

El juego seleccionado proporciona el arte de fondo cuando el origen es «Juego». Hay una capa de sombra en degradado para conservar contraste con texto e imágenes. Según la apariencia, la interfaz coloca la tira de juegos y un panel de información; la opción «presentación mínima» oculta ese panel. Cuando existe logo de juego, puede ocupar el encabezado; si no, se muestra el título.

El panel de información del juego puede mostrar nombre, metadatos, actividad, lanzador y arte asociado. «Datos del lanzador» y el modo mínimo se ajustan por apariencia.

### Barra única inferior

Una sola banda compacta, centrada en el borde inferior, contiene todos los controles. En anchuras reducidas permite desplazamiento horizontal y revela el control que recibe el foco.

1. **Acciones a la izquierda:** Jugar, Editar, Volver y Ajustes. Cada acción está en su propia caja, con icono vectorial del botón de mando y etiqueta. Jugar y Editar se desactivan si no hay juego seleccionado o la tarea no está disponible. Volver limpia la búsqueda si hay texto; si no, devuelve el foco a la biblioteca.
2. **Filtros alrededor de la búsqueda:** la tira de letras va antes del campo; el campo de búsqueda queda centrado en la barra; el selector de categoría va después. La tira de letras enseña la letra actual y sus vecinas; en ventanas estrechas se oculta. El selector de categoría muestra solo la categoría actual, con su icono y nombre; las demás quedan ocultas y se recorren con el mando.
3. **Estado y utilidades a la derecha:** indicadores compactos de Steam, Faugus y Heroic preceden a Añadir juego, Enviar a la bandeja y Salir. Cada indicador usa el icono de la aplicación y un punto de estado: verde abierto, amarillo comprobando/abriendo/cerrando, rojo error y neutro cerrado. El texto accesible y el tooltip explican nombre y estado.

La barra integra búsqueda, letras, categoría, acciones y aplicaciones en una banda; no hay una segunda franja de acciones.

## Las cuatro apariencias de biblioteca

La apariencia se elige en Ajustes globales y cada una tiene ajustes propios. Los nombres visibles son **Grid**, **Carousel**, **Sense** y **Lista**; internamente Sense usa la clave `ps5`.

### Grid

- Cuadrícula paginada de carátulas. El tamaño por página es configurable; se muestra navegación anterior/siguiente y el indicador de página.
- Las carátulas admiten formato vertical o cuadrado y tamaño configurable.
- El juego seleccionado puede mostrar logo o título y un panel de detalles a la derecha.
- Ajustes propios: juegos por página, tamaño, formato y radio de carátula, anillo de selección, fondo y presentación mínima.

### Carousel

- Carrusel horizontal centrado, con hasta cinco carátulas en pantalla. La carátula enfocada crece; las vecinas se reducen.
- El carrusel puede situarse arriba o abajo. El panel con información acompaña la composición si la vista no es mínima.
- Ajustes propios: posición, ampliación, formato de carátula, posición y división del fondo, desenfoque, oscurecimiento, datos del lanzador y anillo.

### Sense

- Tira horizontal de carátulas con el juego seleccionado ampliado y los demás más pequeños. El cambio de foco puede animarse o ser inmediato.
- Usa formato cuadrado por defecto. Puede presentar el panel informativo cerca de la selección.
- Ajustes propios: tamaño de selección, animación, formato y radio de carátula, presentación mínima, fondo, datos del lanzador y anillo.

### Lista

- Tira circular/infinita de elementos centrada en el seleccionado; la trayectoria curva da una lectura de rueda. Los vecinos quedan alrededor y el foco amplía la selección.
- Da prioridad al logo del juego cuando existe; si falta, usa arte cuadrado o carátula.
- Puede orientarse abajo, arriba, izquierda o derecha. Las orientaciones laterales convierten la tira en vertical y reservan el resto del área para la ficha.
- Ajustes propios: posición, tamaño de logos, ampliación del seleccionado, tamaño de carátula, formato/radio, fondo, datos del lanzador y anillo.

### Ajustes visuales comunes a cada apariencia

- **Imagen de fondo:** oscurecimiento y desenfoque.
- **Posición del hero:** completo, arriba o abajo.
- **División de fondos:** único, horizontal, vertical o diagonal.
- **Carátulas:** formato vertical/cuadrado y redondeado.
- **Selección:** borde activado, color, grosor y radio.
- **Presentación:** modo mínimo y datos del lanzador.

## Ajustes

El panel de Ajustes se abre como diálogo modal amplio, centrado, con superficie redondeada. Tiene una columna lateral desplazable, divisor vertical, zona principal y pie con actividad/progreso, acción para cancelar tareas activas y Cerrar. La navegación de mando conserva foco visible y desplaza la sección o el control enfocado hasta hacerlos visibles.

La barra lateral añade botones para abrir o cerrar Steam, Faugus y Heroic cuando se conoce su estado; si el estado es desconocido, muestra texto de estado en lugar del botón.

### Globales

Tarjetas disponibles:

- **Idioma:** idioma del sistema, español o inglés; se aplica al reabrir Estante.
- **Tipo de mando:** Sony, Xbox o Nintendo; controla los glifos y ayudas.
- **Teclado:** automático, teclado del sistema, COSMIC, KDE/Maliit/Plasma, teclado de Estante o desactivado; incluye alternativa integrada y prueba del teclado del sistema.
- **Inicio:** pantalla completa, abrir lanzadores al inicio, comprobación de actualizaciones y cierre de lanzadores al salir.
- **Mientras juegas:** mantener Estante abierto, ocultarlo/restaurarlo, mostrar salvapantallas o enviarlo a bandeja.
- **Salvapantallas:** activación, inactividad, intervalo de diapositivas, oscurecimiento, origen y fondo.
- **Actividad:** mostrar u ocultar historial de sesiones.
- **Aspecto de la biblioteca:** Grid, Carousel, Sense o Lista; tonos pastel o Tema Qt.
- **Origen del fondo:** juego o imagen global.
- **Relleno del fondo:** desenfoque o color dominante.
- **Actualizaciones:** comprobar y, en AppImage, instalar actualización.

Los grupos se expanden al activarlos; algunos tienen controles compactos en dos columnas.

### Escaneo y scraping

- Acciones para importar juegos de Faugus, Heroic, RecompLauncher y Steam; también restaurar juegos excluidos.
- Scraping con selección independiente de carátula vertical, cuadrada, logo, fondo principal, segundo fondo y ficha; permite reemplazar datos existentes.
- Servicios e identificadores en tarjetas plegables: clave de SteamGridDB e ID/secret de IGDB.
- Los resultados, errores y progreso aparecen en el mismo panel; el pie ofrece guardar servicios y cancelar una tarea activa.

### Categorías

- Crear categoría; elegir categoría principal de inicio, incluida «Todos».
- Seleccionar icono por categoría desde archivo/ruta local o mediante búsqueda en Bootstrap Icons, Iconify y Simple Icons.
- El explorador local muestra archivos de imagen y permite elegirlos. Se puede quitar el icono.
- Renombrar, eliminar con confirmación, subir/bajar el orden y buscar juegos asignados a cada categoría.
- Cada juego se incorpora o quita con una casilla. Hay botón para guardar cambios.

### Apariencias individuales

La navegación lateral ofrece cuatro páginas: Grid, Carousel, Sense y Lista. Sus tarjetas agrupan posición, paginación o logos, fondo, hero, división, información, presentación, carátulas y anillo según el modo. Estos ajustes se guardan por apariencia y no tienen por qué cambiar las demás.

## Añadir juego local

Formulario en el panel de gestión para crear una entrada manual o editar su ejecución. Incluye nombre, ruta `.sh`/`.AppImage`, explorador de archivos, argumentos y directorio de trabajo opcional. Se puede guardar la ejecución o quitar el juego de Estante con confirmación. Las opciones de ejecución de Steam, Faugus, Heroic y RecompLauncher se administran en sus propias aplicaciones.

## Editor de juego

Panel modal acoplado a la derecha y a toda altura; en la vista de portada ocupa aproximadamente media ventana y puede ampliarse para el explorador local. Tiene cabecera con volver/cerrar y páginas internas:

### Ficha e imágenes

- Vista inicial con banner y carátula actual.
- Accesos para editar carátula vertical, cuadrada, logo, fondo y fondo secundario; previsualización de los dos fondos, intercambio o retirada del segundo.
- Buscar ficha online o editar metadatos manualmente.
- Categorías del juego y acción para quitarlo de la biblioteca.
- Accesos a Ejecución y Actividad.

### Edición manual de ficha

Campos para título, estudios, editoras, géneros, plataformas, fecha de lanzamiento, descripción y sinopsis. La categoría se gestiona en su página dedicada.

### Elegir arte o buscar ficha

Selector del campo de destino (cinco tipos de imagen), ruta local o URL, selector de archivo, importar/quitar/intercambiar, proveedor y consulta. Fuentes: SteamGridDB, capturas de Steam, IGDB y Wikidata. Los resultados aparecen en una lista seleccionable con vista previa cuando son imágenes.

### Explorador local de imágenes

Vista incrustada con navegación por carpetas, selección de imagen, miniatura, ruta y acciones para elegir o volver. Los archivos no compatibles o sin miniatura muestran «Sin vista previa».

### Ejecución y Actividad

Ejecución muestra la configuración local editable cuando aplica. Actividad muestra estado resumido y sesiones anteriores con fecha, duración y código de salida.

## Teclado virtual

Si se elige el teclado de Estante como método de entrada, aparece como superposición para escribir con mando. La ayuda inferior describe cruceta, confirmar, guardar y bumpers para borrar/espacio; los glifos se adaptan al mando configurado. Otros modos solicitan o invocan el teclado del sistema, según la configuración y el entorno.

## Lanzamiento, juego y salvapantallas

- **Lanzamiento:** cubre la biblioteca, muestra el fondo del juego con sombra/desenfoque y anima la carátula desde su posición hacia el centro; indicador de carga y mensaje de estado debajo.
- **Jugando:** superficie de fondo, carátula centrada, etiqueta «Jugando», título y texto indicando que la biblioteca se restaurará al terminar.
- **Salvapantallas:** superposición a pantalla completa con imagen seleccionada y nivel de oscurecimiento. El origen puede ser arte de los juegos o el fondo de la aplicación.
- **Bandeja:** al escoger ese comportamiento, Estante conserva un icono de aplicación con menú contextual para volver a abrir o salir.

## Estados transversales que Gui debe contemplar

- Sin juego seleccionado: Jugar y Editar no están disponibles; los filtros, Ajustes, estados de lanzadores, Añadir y Salir siguen perteneciendo a la barra.
- Búsqueda/categoría/letra activa: cambia el conjunto visible sin cambiar la estructura de la biblioteca.
- Operación activa: indicador de carga, mensaje de resultado y opción de cancelar donde corresponda; los controles incompatibles se deshabilitan.
- Lanzador cerrado, abierto, comprobando, abriendo/cerrando, error o timeout: estado visible con color y tooltip accesible.
- Imagen ausente o inválida: se usa una alternativa disponible cuando la vista la contempla; en exploradores se indica que no hay vista previa.
- Ventana estrecha: los controles de la barra se desplazan horizontalmente, la tira de letras se oculta bajo 1200 px y el campo de búsqueda mantiene su centrado dentro de la banda desplazable.

## Archivos de referencia

- `qt_app/Library.qml`, `qt_app/LibraryContent.qml`, `qt_app/LibraryView.qml`: ventana, composición de biblioteca y apariencias.
- `qt_app/ConsoleTheme.qml`, `qt_app/CoverTile.qml`, `qt_app/ContextStrip.qml`, `qt_app/GlassButton.qml`, `qt_app/MaterialSurface.qml`: sistema visual y controles comunes.
- `qt_app/Management.qml`, `qt_app/SettingsPane.qml`, `qt_app/CategoriesPane.qml`, `qt_app/settings_schema.py`: ajustes, categorías y campos.
- `qt_app/GameEditor.qml`, `qt_app/EditorArtwork.qml`, `qt_app/LocalImageBrowser.qml`: edición de juego e imágenes.
- `qt_app/PlayingScreen.qml`, `qt_app/LaunchOverlay.qml`, `qt_app/VirtualKeyboard.qml`: estados de juego y entrada.
