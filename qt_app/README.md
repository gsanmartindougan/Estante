# Estante Qt para Linux

`./run.sh` abre ahora Qt Quick/PySide6. GTK se conserva en `./run-gtk.sh`.
La biblioteca y los ajustes mantienen el esquema existente, sin conversión.

## Preparación

```sh
python3 -m venv .venv-qt
.venv-qt/bin/pip install -r requirements-qt.txt
./run.sh
./run.sh --games 100
./run.sh --windowed
```

Puede seleccionarse otro intérprete con `ESTANTE_QT_PYTHON`. El perfil `--games`
crea una biblioteca temporal independiente; `--smoke` impide modificar datos reales
y lanzar juegos. No ejecutar GTK y Qt simultáneamente sobre la misma biblioteca.
Qt tiene su propio bloqueo de instancia.

## Funciones

- Lista, cuadrícula, carrusel y Sense, con delegados limitados al área visible;
  el carrusel mantiene cinco elementos, independientemente del tamaño del catálogo.
- Imágenes asíncronas dimensionadas para pantalla, esquinas y selección configurables,
  fondos globales o del juego, divisiones, dim y blur.
- Categorías, búsqueda, iconos, importación Steam/Faugus y exclusiones.
- Alta y edición de lanzadores locales; ficha, categorías, actividad e historial.
- Imágenes locales/URL y búsqueda SteamGridDB, Steam, IGDB y Wikidata.
- Descarga masiva con progreso/cancelación, ajustes, actualizaciones del AppImage,
  bandeja y salvapantallas que descarga las imágenes de la biblioteca.
- Mando mediante SDL: navegación espacial de formularios y teclado virtual para
  introducir texto, incluidos rutas y caracteres españoles. Editar es seleccionable
  también en vista mínima. Ratón y teclado siguen disponibles.
- Ctrl+F busca, Ctrl+Tab cambia de apariencia y Ctrl+S guarda la ficha abierta.
- Loader con transición de carátula; supervisión reutilizada de procesos Linux,
  independiente del foco. El modo ocultar transfiere al supervisor systemd y cierra
  la interfaz; el supervisor reabre Qt conservando selección y filtro. Si falla la
  transferencia, Qt permanece supervisando. No cerrar una sesión aún supervisada
  por la interfaz. Bandeja y salvapantallas son comportamientos alternativos.

Los guardados releen el JSON actual, preservan campos desconocidos y detectan
conflictos en campos de la ficha. Los juegos ocultos de Faugus siguen ignorándose.
Navegar comienza sobre una copia temporal del catálogo; las acciones explícitas de
edición/importación/ajustes y el registro de partidas escriben en la biblioteca real.

## Diseño de consola

La interfaz deriva tonos pastel del acento Qt del sistema, incluido el tema de
qt6ct. `ConsoleTheme.qml` consulta `SystemPalette` y adapta las superficies al modo
claro u oscuro, conservando los colores de selección y la tipografía del sistema.
Los fondos generales conservan el color de ventana Qt y las sombras son negras;
el pastel se limita a tarjetas y controles, con tonos más oscuros en modo oscuro.
La barra compacta, la ficha y los diálogos usan superficies sólidas de estilo
Material Design, con elevación discreta, botones redondeados y estados de
interacción. `MaterialSurface.qml` centraliza las tarjetas. Los campos usan
relleno suave, esquinas redondeadas y un borde de foco; el panel de información es translúcido al 72%, con el texto opaco y sin blur.
En Ajustes globales → Aspecto de la biblioteca → Colores de la interfaz se puede
elegir entre Tonos pastel y Tema Qt (negro/blanco). La elección se guarda y se
aplica sin reiniciar.
La biblioteca conserva títulos grandes, foco visible y transiciones breves.
En Lista, los logos siguen una rueda con la selección centrada dentro de una zona
del 35% de la pantalla. Se muestran al menos cinco juegos cuando el catálogo lo
permite. El resaltado rodea únicamente al juego seleccionado. La ampliación reserva
espacio solo al juego central; los vecinos mantienen su tamaño base y la lista
horizontal aprovecha el ancho de la ventana. La tarjeta de información
lateral se ajusta al contenido, con un máximo de 880 × 420 píxeles lógicos y
desplazamiento interno para fichas largas. Con la lista a izquierda o derecha, el 65% restante
contiene una columna con la carátula, los botones y la tarjeta de información. Sin carátula, los botones ocupan la cabecera
de esa columna. Con la lista arriba o abajo, la ficha ocupa la mitad opuesta.
Grid y Carrusel ordenan la ficha como logo (o título), botones e información.
El carrusel alinea selección, logo, botones y panel de información en el mismo
eje central, y muestra la carátula solo en la fila de juegos. Los logos se
normalizan retirando sus márgenes transparentes en la caché, sin alterar los
originales, y se encajan en un área común sin deformarlos.
Los ajustes de fondos, distribución y anillos de selección siguen respetando las
preferencias guardadas. Ctrl+Tab alterna las cuatro vistas.

## Pruebas

```sh
python3 -m unittest discover -s tests
.venv-qt/bin/python tests/check_qt_console.py
.venv-qt/bin/python tests/check_qt_logos.py
.venv-qt/bin/python tests/check_qt_list_actions.py
.venv-qt/bin/python tests/check_qt_logo_heading.py
.venv-qt/bin/python tests/check_qt_button_focus.py
.venv-qt/bin/python tests/check_qt_editor.py
.venv-qt/bin/python tests/check_qt_session.py
.venv-qt/bin/python tests/check_qt_launch_ui.py
.venv-qt/bin/python tests/check_qt_management.py
.venv-qt/bin/python tests/check_qt_migration.py
./run.sh --smoke --games 100
.venv-qt/bin/python tools/qt_stress.py --help
```

Las integraciones usan bibliotecas temporales y proveedores simulados cuando hay
red. Comprueban el recorrido de señales de mando, no pulsaciones de hardware real.
El lanzamiento se verifica con scripts temporales; una partida real Steam/Faugus y
la transferencia Qt a systemd requieren validación en la sesión del usuario.

## Instalación y empaquetado

`./install.sh` selecciona Qt; `--frontend gtk` conserva la alternativa anterior.
El entorno `.venv-qt` debe permanecer disponible si se usa como intérprete instalado.
`packaging/build-appimage.py` selecciona Qt por defecto y admite `--frontend gtk`.
El AppDir incluye Python, Qt, SDL, codecs y certificados; `AppRun --self-test`
comprueba PNG/JPEG/WebP, SVG, SSL y ausencia de GTK. Compilar en este equipo no
prueba compatibilidad con todas las distribuciones: falta validar el binario en la
distribución mínima de una futura publicación.

Los vídeos del README muestran Qt 0.3.0. GTK sigue disponible como alternativa.
Windows queda fuera de esta fase.

## Imágenes y ajustes

La composición de fondos sigue GTK: Completo cubre la ventana; Arriba/Abajo
encajan proporcionalmente con un degradado unilateral. En fondos dobles cada
imagen cubre su propia región, con una franja de mezcla de hasta 128 píxeles.
Se respeta el relleno guardado por color dominante o desenfoque. Qt genera
miniaturas a resolución de pantalla en `XDG_CACHE_HOME/estante/qt-thumbnails`:
JPEG (calidad 88) para opacas y PNG para transparencias, con originales intactos.
La caché se depura cada 16 escrituras a 128 MiB/1024 archivos; no es memoria de GPU.
Comprimir el archivo en disco no reduce por sí mismo su tamaño decodificado en RAM;
la reducción de dimensiones es la que limita este último.

Cada apariencia separa presentación/tamaños, fondo, selección e información.
Las opciones se eligen con cajas y radios: A abre, D-pad mueve el foco, A confirma
y B cancela. Los sliders requieren A antes de ajustar y A/B para terminar.

Los ajustes utilizan la organización de GTK: barra lateral con Globales,
Escaneo y scraping, Categorías y las cuatro apariencias. Globales y apariencias
muestran dos columnas de tarjetas plegables independientes. Las opciones de
selección aparecen como radios dentro de la tarjeta; no abren un popup. Los
borradores se conservan al plegar o cambiar de página, y se aplican al guardar.
La prueba `tests/check_qt_gtk_settings.py` valida este recorrido con el despachador
del mando. Las ventanas de prueba se identifican como `io.github.estante.Test`
para la regla de Mango del tag 2 sin foco.

Categorías sigue también la estructura de GTK: Nueva categoría y Categoría
principal a la izquierda; tarjetas individuales con nombre, orden y juegos a la
derecha. Las listas de juegos están virtualizadas y mantienen la selección tras
guardar. Los iconos locales y las búsquedas Bootstrap/Iconify se conservan en su
grupo. `tests/check_qt_categories.py` verifica este recorrido con 100 juegos
sobre datos temporales y comprueba la preservación de metadatos y membresías.
