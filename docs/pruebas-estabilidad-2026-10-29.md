# Pruebas de estabilidad y rendimiento — 29 de octubre de 2026

Correcciones y repetición posteriores: [resultado verificado](correccion-imagenes-2026-10-29.md).

## Resultado

No se ha observado una fuga grande ni crecimiento de RAM proporcional al número de
juegos durante estos ciclos. Con 500 juegos sí hay una deriva pequeña después del
calentamiento: entre +2,1 y +5,5 MiB según el modo, de la primera a la tercera vuelta.
Tres vueltas no bastan para descartar una fuga lenta.

La prueba **no queda limpia de incidencias**: cada tamaño produjo dos avisos de
Qt al reconstruir la carátula de la vista. El proveedor recibe dimensiones nulas o
muy pequeñas y termina devolviendo una imagen vacía. La reproducción con un PNG
sintético confirma que no es necesario que el archivo esté corrupto para provocarlo.
Las comprobaciones de destrucción/restauración sí pasaron. Los scripts terminan con
código 1 deliberadamente cuando detectan estos avisos, no por un cierre inesperado.
No se ha corregido el código de la aplicación en esta tanda.

## Alcance y límites

- Código fuente del árbol de trabajo tras su reorganización; Python/PySide6 del
  entorno local, con el proveedor de miniaturas utilizado por la aplicación.
- 100 y 500 entradas sintéticas basadas en la biblioteca existente, con rutas de
  imágenes independientes. No son 500 juegos distintos instalados. Se reutilizó
  almacenamiento mediante enlaces duros de solo lectura para esta prueba; los
  perfiles, ajustes y miniaturas son temporales.
- Cuatro modos, tres vueltas, un recorrido completo por el catálogo en cada vuelta.
  Intervalo objetivo de 40 ms entre selecciones: hasta 25 cambios/s, más rápido que
  la repetición habitual de la cruceta. Los tiempos reales pueden superar ese objetivo.
- 7.200 cambios de selección; 48 aperturas/cierres de páginas de ajustes, 24 ciclos
  del salvapantallas y 24 descargas/restauraciones de la biblioteca al simular jugar.
- 120 comprobaciones de ciclo de vida: los controles de ajustes y la biblioteca
  se destruyen cuando corresponde y la selección se recupera.
- Launchers, teclados externos, actualizaciones y juegos reales desactivados.
- Ejecución `offscreen` con **GraphicsApi.Software**, sin mover el foco del escritorio.
  Estos resultados miden RAM del proceso y trabajo del bucle de eventos. **No miden
  FPS, VRAM ni fluidez del renderizador real Wayland/GPU**, y no son comparables
  directamente con los 300–400 MB observados en una sesión gráfica normal.
- Pico RSS obtenido de `VmHWM`; RSS/PSS por fase de `smaps_rollup`. El pico PSS de
  los datos brutos es muestreado, no un máximo continuo del sistema.

## Ejecuciones

| Juegos | Cambios de selección | Duración | Tiempo CPU del proceso | Pico RSS | Avisos Qt |
|---|---:|---:|---:|---:|---:|
| 100 | 1200 | 132.4 s | 62.2 s | 258.7 MiB | 2 |
| 500 | 6000 | 331.9 s | 290.2 s | 264.8 MiB | 2 |

El tiempo CPU incluye los hilos del proceso y toda la secuencia de trabajo; no es
una medida de consumo en reposo. Los picos transitorios se recuperan en buena parte
al descargar la biblioteca y devolver memoria del asignador.

## RAM tras volver a la biblioteca

Cada celda contiene RSS al finalizar las vueltas 1 → 2 → 3, en MiB.

| Modo | 100 juegos | 500 juegos | Pantalla «Jugando», 500 juegos, última vuelta |
|---|---:|---:|---:|
| Lista | 160.4 → 165.4 → 161.5 | 160.2 → 165.8 → 165.7 | 155.9 MiB |
| Grid | 159.7 → 163.1 → 162.3 | 161.5 → 164.9 → 166.6 | 158.7 MiB |
| Carrusel | 165.4 → 166.9 → 165.2 | 165.1 → 168.4 → 169.3 | 158.3 MiB |
| Sense | 164.3 → 163.8 → 165.7 | 166.1 → 166.9 → 168.2 | 158.8 MiB |

La pantalla «Jugando» descarga la escena, pero mantiene Qt y el proceso principal.
En estas pruebas no libera 300 MB: el ahorro respecto a la biblioteca reconstruida
es de aproximadamente 8–11 MiB con 500 juegos. Las reservas gráficas reales quedan
fuera de esta medición.

## Respuesta durante navegación

Peor p95 de las tres vueltas y mayor retraso observado del temporizador de eventos.
El p95 es el tiempo por debajo del que cae el 95 % de las muestras de esa vuelta.

| Modo | Despacho de selección p95, 100 | Despacho de selección p95, 500 | Retraso de eventos p95, 500 | Mayor retraso, 500 |
|---|---:|---:|---:|---:|
| Lista | 9.69 ms | 7.30 ms | 3.96 ms | 77.14 ms |
| Grid | 6.29 ms | 5.76 ms | 3.27 ms | 37.81 ms |
| Carrusel | 4.48 ms | 5.35 ms | 2.70 ms | 35.54 ms |
| Sense | 4.54 ms | 4.73 ms | 2.66 ms | 116.21 ms |

Hubo pausas puntuales de unos 77 ms en Lista y 116 ms en Sense con 500 juegos.
Esto justifica investigarlas, pero el entorno aislado y las tareas concurrentes del
sistema no permiten atribuirlas todavía a una función concreta ni convertirlas en FPS.

## Fallo de imágenes confirmado

En las vueltas 2 y 3 aparece el aviso en `qt_app/LibraryContent.qml`, en la carátula
reconstruida. Los errores de decodificación registrados fueron 4/5.120 peticiones
con 100 juegos y 6/15.003 con 500; no todos generaron un aviso visible de Qt.

Con un PNG válido de 600 × 900:

- Una petición de 240 × 360 devuelve una imagen válida.
- Peticiones de 0 × 1 o 1 × 1 devuelven una imagen nula.
- Un logo válido de 800 × 200 falla con una petición de 1 × 42, pero funciona a 360 × 80.

`QSize.scaled()` puede dejar una de las dimensiones en cero al conservar la relación
de aspecto. `qt_app/images.py` utiliza ese resultado en el escalado sin garantizar
un mínimo positivo en ambas dimensiones. La siguiente corrección debería cubrir
este borde y las peticiones emitidas antes de que termine el layout.

## Modelos Python

El sondeo separado, sin QML ni renderizado, conserva las lecturas cacheadas del
modelo prácticamente constantes. Reconstruir el modelo completo crece con el catálogo:

- 100 juegos: 20 lecturas cacheadas 0.035 ms; 20 reconstrucciones 48.032 ms; proyección JSON 17.67 KiB.
- 500 juegos: 20 lecturas cacheadas 0.037 ms; 20 reconstrucciones 240.693 ms; proyección JSON 88.76 KiB.

Esto no representa el tiempo de cargar una pantalla ni la latencia con mando: la
prueba QML anterior incluye trabajo que este microbenchmark no ejecuta.

## Siguiente trabajo recomendado

1. Corregir y cubrir con regresión las solicitudes de imagen de tamaño nulo/mínimo.
2. Repetir la secuencia y confirmar que desaparecen los avisos, manteniendo las
   comprobaciones de descarga de objetos.
3. Medir los tirones y reservas gráficas en un entorno Wayland/GPU aislado, sin
   tomar el foco del escritorio del usuario. La prueba actual no los valida.
4. Extender una prueba a 30–60 minutos para distinguir calentamiento de una deriva
   lenta de memoria. Los datos actuales no justifican otra migración de tecnología.

## Reproducción y datos

```sh
QT_QPA_PLATFORM=offscreen .venv-qt/bin/python tools/qt_stress.py --games 100 --cycles 3 --interval-ms 40 --output /tmp/stress-100.jsonl
QT_QPA_PLATFORM=offscreen .venv-qt/bin/python tools/qt_stress.py --games 500 --cycles 3 --interval-ms 40 --output /tmp/stress-500.jsonl
.venv-qt/bin/python tools/qt_optimization_probe.py --counts 100 500 --output /tmp/models.json
.venv-qt/bin/python tools/qt_image_edge_probe.py --output /tmp/image-edges.json
```

Los scripts crean perfiles temporales y no arrancan ni cierran launchers. El código
1 de `qt_stress.py` indica incidencias Qt y conserva las mediciones para analizarlas.

- [Datos de 100 juegos](benchmarks/2026-10-29/qt-stress-100.jsonl)
- [Datos de 500 juegos](benchmarks/2026-10-29/qt-stress-500.jsonl)
- [Resumen numérico](benchmarks/2026-10-29/summary.json)
- [Microbenchmark de modelos](benchmarks/2026-10-29/qt-models.json)
- [Reproducción de tamaños límite](benchmarks/2026-10-29/image-size-edge-probe.json)
- [Entorno](benchmarks/2026-10-29/environment.json)

La suite unitaria final ejecutó 433 pruebas: correctas, con una omitida por PySide6
no disponible en el Python del sistema. El sondeo de imágenes y las pruebas Qt se
ejecutaron usando el entorno `.venv-qt`.
