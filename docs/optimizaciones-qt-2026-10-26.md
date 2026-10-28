# Tanda de optimizaciones Qt — 26 de octubre de 2026

Cambios aplicados sobre la versión Qt actual, conservando la distribución, los
fondos, el mando y la edición. Todas las pruebas se ejecutaron con
`QT_QPA_PLATFORM=offscreen`: no se abrieron ventanas en Mango ni se cambió de tag.

## Cambios

1. **Modelo de carátulas ligero y reutilizable.** Los cuatro modos reciben solo
   ID, título y rutas de carátula vertical, cuadrada y logo. La descripción,
   actividad, historial y demás metadatos completos siguen disponibles en
   `controller.game` para el juego seleccionado. La proyección se invalida al
   filtrar, cambiar categoría, recargar la biblioteca o suspender la vista. El
   cambio de selección y de apariencia reutiliza las filas existentes; QML
   comparte un único acceso al modelo de la vista.
2. **Índices de selección y letras.** Al filtrar se prepara el índice por ID y
   las primeras posiciones de cada inicial. Seleccionar un juego o mover la
   barra alfabética deja de recorrer y normalizar de nuevo toda la biblioteca.
   Se conservan las vueltas en los extremos y la identidad seleccionada.
3. **Resolución estable durante la animación de Sense.** El widget conserva su
   animación de tamaño, pero solicita la imagen a la resolución final. Se
   evitan decodificaciones y miniaturas para los tamaños intermedios.
4. **Liberación de imágenes ocultas.** El editor cerrado y sus páginas que no
   muestran previsualizaciones vacían las fuentes de imagen. También se vacían
   los rellenos ocultos de los fondos completos y la carátula de detalle en
   modos que no la muestran. Al volver a mostrarlos se cargan otra vez mediante
   el proveedor existente, con sus miniaturas en disco. No se modifican originales.

## Medición controlada del modelo y la navegación

`tools/qt_optimization_probe.py` crea bibliotecas temporales con 100 y 1.000 juegos,
una descripción de longitud fija, estudio y géneros. La medida de CPU es la
mediana de tres repeticiones. No abre una vista ni mide FPS. La columna JSON
aproxima el tamaño de los datos del modelo, **no el RSS de la aplicación**.

| Prueba | Antes | Después |
| --- | ---: | ---: |
| 100 juegos: 20 construcciones del modelo | 89,398 ms | 46,985 ms |
| 1.000 juegos: 20 construcciones del modelo | 909,677 ms | 469,752 ms |
| 1.000 juegos: 20 lecturas con caché caliente | 909,677 ms | 0,034 ms |
| 1.000 juegos: datos JSON del modelo | 1.106,34 KiB | 177,63 KiB |
| 1.000 juegos: 500 pasos + consultas de selección/letras, solo backend | 804,863 ms | 0,459 ms |

Antes no había caché: las lecturas reconstruían el modelo completo. La medición
posterior distingue construcciones forzadas de lecturas calientes. El coste de
transferir QVariant a QML, el renderizado y la carga de imágenes no están incluidos
en esos tiempos. La caché retiene una única proyección ligera; el pico de
asignaciones de lecturas calientes no representa toda la memoria retenida.

Resultados sin resumir:

- `benchmarks/qt-models-2026-10-26-before.json`
- `benchmarks/qt-models-2026-10-26-after.json`

## Solicitudes reales desde QML

`tests/check_qt_optimization_ui.py` usa el árbol QML real con un proveedor de imágenes
instrumentado. Las imágenes del proveedor son sintéticas y las ventanas son
offscreen. Un cambio de selección en Sense solicitó imágenes de carátulas **20
veces antes y 2 después**. En la misma prueba el editor cerrado tenía **4 fuentes
de imagen no vacías antes y 0 después**. También se comprueba que abrir el editor
las carga, cambiar a la ficha manual las libera y cerrar el panel no las conserva.

El proveedor de instrumentación permite contar peticiones y comprobar las
resoluciones solicitadas. **No mide la memoria de texturas de un renderizador GPU
real ni demuestra una reducción concreta de los MB del monitor del sistema.**

## Verificación

- 398 pruebas unitarias.
- Integración Qt de los cuatro modos, filtros, categorías, ajustes y salvapantallas.
- Proyección ligera e invalidación con 100 juegos; conservación de la ficha completa.
- Galería, edición, guardado y navegación con mando simulada.
- Miniaturas JPEG/PNG, transparencia, invalidación y originales intactos.
- Transición de inicio del juego.

Para repetir las medidas del modelo:

```sh
.venv-qt/bin/python tools/qt_optimization_probe.py --output /tmp/estante-qt-models.json
.venv-qt/bin/python tests/check_qt_optimization_ui.py
.venv-qt/bin/python tests/check_qt_model_projection.py
```

Estas tres herramientas fuerzan el modo offscreen. No cambian datos de la biblioteca
real ni lanzan el teclado nativo.

## Pantalla de jugando (27 de octubre)

La ventana principal carga `LibraryContent.qml` mediante un Loader. Tras los 25 segundos
iniciales y la confirmación del proceso, descarga ese contenido y carga `PlayingScreen.qml`:
una sola carátula a 240 × 360, título y estado. No mantiene la biblioteca oculta detrás.
Al terminar o fallar la sesión se reconstruye la biblioteca con la selección y el modo del
controlador. «Cerrar y restaurar» conserva la transferencia al supervisor y cierra el proceso;
la pantalla ligera sirve cuando Estante permanece abierto durante la partida.

`check_qt_playing_memory.py` verifica con 100 juegos la destrucción de la escena en los cuatro
modos, el paso de 252–407 elementos visuales a 6 y la restauración de la selección. Una ejecución
offscreen dio 139,1 → 132,8 MiB RSS en grid y valores en torno a 134 MiB en el resto. Esto prueba
la descarga de objetos pero **no demuestra un ahorro de 300 MB**: el proceso de Qt continúa
vivo y la prueba offscreen no reproduce las reservas del renderizador de una sesión Wayland.
No se han abierto ventanas ni juegos en el escritorio para medir este cambio.

## Paginación de Grid (27 de octubre)

Grid muestra 10 juegos por página por defecto. Ajustes → Grid → Paginación permite
cambiar `grid_page_size` entre 1 y 100. El modelo del GridView recibe solo el tramo
de la página actual y no mantiene un pool de delegados de páginas anteriores.
La selección conserva su índice global; los botones ‹/› y LB/RB (L1/R1 o L/R)
cambian de página, y la cruceta cruza automáticamente al tramo correspondiente.
El indicador se recalcula al buscar o cambiar de categoría, incluida una biblioteca vacía.

`tests/check_qt_grid_pagination.py` verifica con 100 juegos el valor por defecto,
el guardado de 7 juegos por página, la última página de 2 juegos, los cambios con
mando y ratón y la ausencia de carátulas de otras páginas. Pruebas offscreen,
sin abrir ventanas en el escritorio.
