# Primera tanda de optimizaciones de prioridad alta

Aplicadas el 23 de octubre de 2026 sobre el árbol de trabajo existente. La auditoría original describe el estado anterior a esta tanda.

- **Caché concurrente:** las solicitudes simultáneas de la misma versión, tamaño y generación comparten una decodificación. Un fallo despierta a todos los consumidores y permite reintentar. Se comprueban identidad de textura y contabilidad exacta al expulsarla.
- **Galerías y búsquedas de los paneles:** cola de cuatro workers y hasta 64 trabajos pendientes. Cambiar de búsqueda o cerrar el panel cancela los pendientes, suelta callbacks y resultados y evita entregas antiguas. Una llamada de red que ya está ejecutándose puede continuar hasta responder o agotar su timeout; no se mata su hilo. La supervisión de partidas conserva su recorrido independiente para no ocupar esta cola.
- **Interfaz sin decodificaciones de vistas previas:** ajustes, iconos de categorías, fondos de editores y galerías usan solicitudes asíncronas. La validación de importaciones se ejecuta en un worker a tamaño pequeño y no llena la caché de texturas de pantalla. El fondo global de arranque utiliza la carga asíncrona compartida, también si la categoría está vacía.
- **Decoder de AppImage:** los JPEG grandes con una reducción importante utilizan decodificación reducida mediante Pillow, incluido en el paquete por el constructor. En ejecución desde fuente Pillow sigue siendo opcional y se usa cuando falla la ruta escalada del sistema. No se ha generado ni publicado un AppImage nuevo.
- **Actualización incremental:** si siguen coincidiendo apariencia, filtro, categorías e IDs/orden de tarjetas, una edición actualiza sus datos conservando widgets y diccionarios usados por los handlers. Solo se invalida la imagen afectada. Un cambio estructural conserva la reconstrucción completa. La carátula de presentación se reutiliza y no se vuelve a pedir si su firma no cambia.
- **Paneles cerrados:** se desconectan señales y se destruyen hijos después de la transición. Una revisión impide que la limpieza de un panel anterior destruya el nuevo. La limpieza no expulsa las miniaturas de ajustes si se ha navegado allí.

## Medición aislada del decoder

Fixture RGB uniforme de 7680×4320, salida 480×270, un proceso nuevo por alternativa, mismo sistema. Pico medido con `VmHWM` de `/proc/self/status`; `ru_maxrss` resultó inadecuado en este ensayo porque heredaba el máximo del proceso que generaba la fixture.

| Imagen | Ruta anterior | Alternativa Pillow | Decisión |
|---|---:|---:|---|
| JPEG | ~146 MiB; ~50 ms | ~55 MiB; ~15 ms | Aplicar a JPEG |
| PNG | ~146 MiB; ~38 ms | ~185 MiB; ~64 ms | Conservar GDK |

Son mediciones de un decoder con una fixture concreta; no representan la RAM ni el rendimiento global de Estante. Los JPEG pequeños conservan GDK para no pagar el coste residente de importar otro decoder sin un ahorro que lo justifique. PNG continúa necesitando una solución adicional si se quiere reducir su buffer original: la alternativa probada aumentaba el pico y no se ha aplicado.

## Verificación y límites

La suite incluye nuevas pruebas de concurrencia, errores compartidos, cancelación, límites de cola, liberación de resultados pendientes, actualización incremental en cuatro modos y limpieza de paneles. Se mantienen las pruebas existentes de selección, mandos, imágenes, salvapantallas, instalación y supervisor.

Falta medir Estante completo en el escritorio: misma secuencia de juegos, caché fría/caliente, ajustes, galerías y salvapantallas, separando RAM de memoria gráfica. No se atribuye todavía un ahorro concreto sobre los 300 MB observados.

## Caché JPEG para imágenes PNG

Las miniaturas de imágenes sin canal alfa se guardan ahora como JPEG de calidad 95. Las que tienen canal alfa permanecen en PNG para conservar transparencia, incluso si todos sus píxeles resultan opacos. No se modifican ni eliminan las imágenes originales.

La carga acepta JPEG y los PNG antiguos de la caché; estos últimos se convierten en segundo plano cuando no tienen canal alfa. Solo se elimina la copia PNG de la caché después de guardar correctamente su sustituto JPEG mediante reemplazo atómico. La cuota de disco incluye ambos formatos. Las conversiones usan el escritor ya existente, sin añadir procesos ni cargar otro decoder en el hilo de GTK.

Esto evita volver al PNG original en cargas posteriores y puede reducir el trabajo de lectura/decodificación y el tamaño en disco. No garantiza una bajada equivalente de RAM: una imagen decodificada sigue necesitando memoria según sus dimensiones y canales. El primer acceso continúa decodificando el PNG. La suite alcanza 341 pruebas e incluye reutilización de un JPEG real, conservación de alfa, fallo de conversión y cuota compartida de formatos.

## Comprobación de RAM tras la prueba de caché JPEG

La caché JPEG no produjo una diferencia visible en la prueba del usuario. Se ha comprobado la configuración guardada: lista, división horizontal, relleno por color dominante y blur cero. Los dos fondos sí son visibles en ese modo; no se atribuye su RAM a una segunda imagen oculta.

Se ha eliminado la conversión de la textura completa a pixbuf al calcular el color dominante. La muestra, de hasta 64 píxeles por eje, se prepara a partir del pixbuf que el decoder ya tiene y su memoria se incluye en la contabilidad. Además, las apariencias con fondo único dejan de cargar y retener el secundario; las vistas divididas conservan ambos.

A petición del usuario se ha dejado una solicitud local de limpieza de caché para el próximo arranque completo, antes de cargar imágenes. Se borran solo miniaturas generadas y temporales del escritor; no los originales ni la biblioteca. Después se registran cinco muestras de RSS/PSS, caché de texturas y buffers de escritura en la consola y en `/tmp/estante-memory-UID.jsonl`. La solicitud se consume una sola vez. El ahorro global sigue pendiente de esa medición. La suite alcanza 345 pruebas.

## Primera lectura real tras vaciar caché

El usuario confirmó que se borraron 256 archivos. Las primeras muestras fueron 244–276 MiB RSS, 154–185 MiB PSS y 8–11 MiB de caché de texturas, sin decodificaciones ni buffers de escritura pendientes. Comunicó después 308 MB en el monitor. Las muestras no son simultáneas con esa última cifra; no se deduce de ellas una fuga ni se atribuye todo el consumo al renderer.

Se encontró que la cápsula de lista aplicaba un blur fijo de 18 aunque el ajuste guardado fuese cero. Ahora respeta el cero y evita esos snapshots adicionales. La muestra de color del fondo conserva directamente el pixbuf pequeño, eliminando también su conversión desde textura en la ruta habitual.

Para distinguir memoria reservada de recursos todavía retenidos se puede ejecutar `ESTANTE_MEMORY_DIAGNOSTICS=1 ./run.sh`. Las cinco muestras incluyen el renderer, el estado anterior y `after_trim` después de la recogida y devolución de páginas nativas libres. Esa limpieza por selección solo ocurre en el modo de diagnóstico explícito. No es una supuesta solución permanente ni prueba por sí sola dónde está todo el consumo.

## Depuración gráfica con repetición del D-pad

Se ejecutó Estante en el escritorio con un perfil temporal, una copia de biblioteca/ajustes y caché separada. El ensayo repite 50 movimientos a la derecha cada 130 ms en lista, abre/cierra ajustes y recorre cuadrícula, Sense, carrusel y lista. Se registran RSS/PSS, caché, trabajos pendientes, referencias débiles de ajustes y recuentos de widgets. `tools/memory_stress.py` permite reproducirlo sin guardar cambios en la biblioteca original; `--cache-dir` permite reutilizar una caché exclusiva del ensayo y `--skip-idle-reclaim` sirve para la comparación.

En tres ciclos, la referencia con caché fría pasó de 306,7 MiB RSS a un máximo **muestreado** de 340,2 y terminó en 328,7. Con los grupos de ajustes desplegados se observaron 352,3 MiB. No son máximos continuos ni cifras directamente comparables con otro monitor: son muestras de esa instancia gráfica. Al cerrar ajustes desaparecieron sus referencias débiles y los recuentos de widgets volvieron al inicial en cada ciclo; esto descarta la acumulación de esas vistas en la secuencia ensayada, pero no demuestra que toda la memoria nativa se haya liberado.

Se probaron y descartaron dos alternativas: reducir el tiempo de caché de GTK y retrasar los fondos durante la repetición. Ninguna redujo de forma convincente el consumo final; no se mantienen esos cambios ni variables de depuración en el producto. Limitar las arenas de glibc a dos tampoco aportó un ahorro claro y no se ha aplicado al arranque.

La instrumentación de glibc encontró hasta unos 45 MiB libres dentro de sus arenas tras navegar. Ahora se solicita la recogida y devolución de páginas nativas libres después de 1,5 segundos desde la última carga de fondo completada. La revisión de selección invalida limpiezas antiguas; no se recoge durante cada paso del mando. Se aplica a los cuatro modos. El selector de archivos de los ajustes globales se construye solo al pulsar «Desde mi equipo…».

La comparación con caché fría mostró una mejora parcial en las muestras tras navegar (tercer ciclo: 340,2 frente a 334,7 MiB), pero **no una reducción convincente del consumo final** (328,7 frente a 334,9 MiB entre procesos). No se presenta este cambio como solución completa ni se atribuye todo el crecimiento a imágenes o GTK. La suite pasa 349 pruebas, incluidas la espera de inactividad y la invalidación de limpiezas obsoletas.

### Comparación con caché caliente

Se preparó una caché temporal compartida entre procesos y se repitió la misma secuencia. La referencia desactiva únicamente la nueva limpieza por inactividad; conserva las demás correcciones.

| Muestra RSS | Sin limpieza por inactividad | Con limpieza por inactividad |
|---|---:|---:|
| Inicio | 236,0 MiB | 232,3 MiB |
| Tras la segunda repetición del D-pad | 304,8 MiB | 249,2 MiB |
| Final, después de cerrar ajustes y recorrer apariencias | 246,2 MiB | 249,9 MiB |

La mejora observada corresponde a recuperar antes el exceso tras navegar; el consumo final después de otras limpiezas ya era parecido. No se afirma una reducción del mínimo de la aplicación.

La primera pasada con todos los grupos de ajustes desplegados volvió a dejar unos 321 MiB al terminar. Una repetición posterior con el renderer normal, mismos datos/caché y ajustes desplegados terminó en **247,3 MiB RSS / 156,7 MiB PSS**. Los mapas muestran bibliotecas del compilador gráfico de NVIDIA y LLVM. La diferencia entre primeros renderizados y repeticiones es compatible con un coste de compilación/caché del driver, pero los mapas y estas muestras no atribuyen por sí solos cada MiB a ese mecanismo. No se mantienen modificaciones de degradados ni variables experimentales de GTK. Los picos en frío siguen siendo una limitación, separada de la recuperación de páginas libres durante la navegación.

## Ensayo con 100 juegos sintéticos

El diagnóstico acepta `--games 100`. Crea 100 identidades distintas a partir de la biblioteca existente y copia carátulas, imágenes cuadradas, logos y ambos fondos a rutas independientes dentro del perfil temporal. Se conservan formatos, dimensiones y contenido; no son 100 diseños diferentes. Esto evita que repetir las rutas originales comparta las mismas entradas de caché y subestime el consumo. Se eliminan las categorías de la muestra para mostrar los 100 en la categoría general. Los lanzamientos sintéticos apuntan a `true`, sin ejecutar los juegos originales.

Prueba manual, con teclado/mando y cierre normal de la ventana:

```sh
python3 tools/memory_stress.py --games 100 --manual
```

El perfil y su caché se eliminan al cerrar. La biblioteca real no se modifica. Las mediciones del ensayo se guardan por defecto en `/tmp/estante-memory-stress.jsonl`.

Prueba automática con dos recorridos de 100 movimientos, ajustes desplegados y los cuatro modos:

```sh
python3 tools/memory_stress.py --games 100 --cycles 2 --expand-settings --output /tmp/estante-memory-100.jsonl
```

Primera ejecución, caché fría: inicio **293,7 MiB RSS / 197,3 MiB PSS**; final **350,0 MiB RSS / 253,0 MiB PSS**. Al terminar quedaban 10,33 MiB de caché de imágenes, sin decodificaciones ni escrituras pendientes, y ninguna vista de ajustes retenida. Cuadrícula construyó 12 elementos por página; los otros modos mantuvieron los 100 elementos de la categoría. Estos datos son de la secuencia completa y no permiten atribuir la diferencia a un modo concreto ni exclusivamente a PNG. La suite alcanza 351 pruebas, incluidas identidad/rutas únicas y aislamiento de las copias de imágenes.

## Ventanas de presentación y separación del carrusel

La prueba de 100 juegos mostró dos mecanismos distintos: las imágenes ya tenían una ventana de retención, pero lista, Sense y carrusel todavía construían un widget por juego; además, la separación angular del carrusel dependía del número total de juegos y comprimía los vecinos al aumentar el catálogo.

Ahora el modelo filtrado de la categoría conserva los metadatos y la navegación completa, mientras la presentación mantiene un conjunto acotado de widgets:

- Lista y carrusel: hasta cinco widgets únicos alrededor de la selección, incluyendo margen para navegar. Las imágenes conservan su ventana de selección y vecinos.
- Sense: una tira virtual mantiene la extensión de desplazamiento del catálogo completo y materializa la zona visible con un pequeño margen. Conserva también el widget seleccionado cuando queda fuera de pantalla, sin retener su carátula fuera del área visible. El desplazamiento con ratón actualiza la ventana; se reserva el espacio adicional de la carátula ampliada.
- Cuadrícula: conserva la paginación de 12 elementos y la carga de imágenes según el área visible.

Los widgets que salen de la ventana liberan sus imágenes y señales. Los que permanecen conservan su identidad y foco. Las flechas del mando, los saltos por letra, la búsqueda y las categorías usan el catálogo completo, no solo los widgets presentes. El modelo adicional se descarga también al suspender la biblioteca para jugar o usar el salvapantallas.

El carrusel utiliza una separación acotada independiente del tamaño de catálogos grandes y conserva índices globales para animar y envolver la selección. Se comprobó gráficamente la separación con la entrada 038 y un catálogo de 100.

### Pruebas y límites

357 pruebas unitarias pasan. Se añadieron comprobaciones de ventanas de cinco juegos para catálogos de hasta 1000 entradas, separación constante, extensión virtual, reserva de anchura del zoom y carga de carátulas recién creadas antes de su primera asignación de tamaño. Se mantiene la comprobación de filtrado por categorías y se comprueba la descarga del nuevo modelo al suspender.

La prueba gráfica específica recorrió los 100 juegos de lista, Sense y carrusel, cambió por cuadrícula y ajustes, y desplazó Sense con ratón hasta otra zona del catálogo. Observó cinco widgets en lista/carrusel, 12 en cuadrícula y aproximadamente veinte en la zona visible de Sense a 2560 píxeles de ancho. No hubo errores de asignación GTK tras corregir la reserva del zoom. Se generaron capturas en `/tmp/estante-virtual-carousel.png`, `/tmp/estante-virtual-ps5.png` y `/tmp/estante-virtual-list.png`.

La comprobación gráfica general `tests/check_ui.py` no se declara superada: contiene una aserción de cambio inmediato de un fondo asíncrono y mocks antiguos de `background` para galerías que ahora usan `panel_background`. La prueba específica de virtualización usa el flujo real de imágenes, sin esos mocks.

La corrección limita widgets, trabajo de layout y densidad visual; no demuestra que todo el exceso de RSS proviniera de los widgets. La prueba breve sin capturas siguió terminando alrededor de 338 MiB RSS con caché fría. La prueba más larga con capturas fuera de pantalla llegó a unos 396 MiB y no es una comparación equivalente con la referencia anterior. No se promete una reducción grande de RAM ni se atribuye todo ese consumo a PNG.

## Reducción de RAM tras la prueba manual de 100 juegos

El usuario comunicó unos 400 MB en lista y 380 MB en las otras vistas. Se repitió una referencia con el código virtualizado y la biblioteca actual: 100 entradas sintéticas con imágenes independientes, caché fría, recorrido completo, ajustes y cambio por los cuatro modos. La referencia terminó en **339,1 MiB RSS / 230,6 MiB PSS**. No es una muestra simultánea del monitor del usuario.

Se aplicaron tres cambios:

1. `native_memory.py` configura al arrancar los umbrales de glibc de mapeo y devolución de bloques grandes en 128 KiB. Evita que el ajuste dinámico eleve estos umbrales tras las decodificaciones y que posteriores buffers grandes fragmenten el heap. Se usa `mallopt` antes de iniciar los trabajadores de GTK. Tolera plataformas sin esa API y respeta los umbrales explícitos del entorno y `GLIBC_TUNABLES`. `ESTANTE_NATIVE_ALLOCATOR=0` permite aislar su efecto en pruebas. El módulo se incluye en la instalación y, por esa vía, en futuros AppImages; no se ha reconstruido ningún AppImage.
2. Sense y carrusel dejan de cargar cada carátula a 2,5×. Los vecinos se cargan según su tamaño lógico y la densidad de pantalla; la selección usa su ampliación configurada, también cuando Sense necesita 320/104×. Al cambiar de selección se cambia la resolución del mismo widget, conservando la imagen anterior hasta recibir la nueva. Lista mantiene la resolución de logos según el zoom y la densidad ya configurados.
3. Los seis fondos incluidos de ajustes se decodifican únicamente al desplegar «Origen del fondo». Se conserva la resolución anterior de las previsualizaciones. Abrir ajustes con ese grupo cerrado no solicita esas seis imágenes.

El comportamiento de los umbrales, su ajuste dinámico y la devolución independiente de bloques grandes se documenta en el [manual de GNU libc](https://sourceware.org/glibc/manual/latest/html_node/Malloc-Tunable-Parameters.html).

### Medición de la versión aplicada

Se ejecutó el código normal, sin variables experimentales del asignador, con 100 juegos y dos ciclos completos. Resultados del segundo ciclo:

| Muestra | RSS | PSS |
|---|---:|---:|
| Después de cerrar ajustes | 315,3 MiB | 206,7 MiB |
| Cuadrícula | 313,4 MiB | 204,8 MiB |
| Sense | 311,6 MiB | 203,0 MiB |
| Carrusel | 311,5 MiB | 202,9 MiB |
| Lista y final tras recoger | 314,9 MiB | 206,3 MiB |

La reducción del final respecto a la referencia actual fue **24,2 MiB RSS / 24,3 MiB PSS**. La referencia tenía un ciclo y el resultado aplicado dos: la segunda pasada no volvió a acumular el exceso, pero no se trata de una garantía universal sobre los 400 MB del monitor. Otra ejecución con todos los grupos de ajustes desplegados terminó en 317,1 MiB RSS / 208,3 MiB PSS, sin vistas de ajustes retenidas ni trabajos pendientes.

Se descartó sustituir el decoder por acceso directo a Glycin: con un PNG real de fondo, ambos caminos dieron aproximadamente 41 MiB RSS y 79–80 ms en procesos aislados. No se añadió esa dependencia ni se convirtieron originales.

362 pruebas unitarias pasan. Se cubren disponibilidad y rechazo de `mallopt`, respeto de opciones del usuario, resolución de vecinos y foco con HiDPI, y actualización de resolución sin reemplazar widgets. Se verificó que todos los módulos declarados por el instalador existen. La limitación de la comprobación gráfica general descrita en la sección anterior permanece; las pruebas de memoria ejecutan el flujo gráfico real de 100 juegos.

Comprobación adicional de navegación en lista, caché caliente, cuatro segundos y 240 intervalos por variante: mediana y percentil 95 de 16,67 ms en ambas. La CPU medida fue 35,41 % de un núcleo con la política nativa desactivada y 22,81 % activada; el máximo RSS del proceso fue 345,5 y 309,0 MiB respectivamente. Es una comprobación corta, no una garantía de FPS ni de ahorro de CPU en todas las cargas. No mostró un empeoramiento de la cadencia de fotogramas medida.

## 24 de octubre: backend reutilizable para Linux y el prototipo Qt

Se aplican dos puntos de prioridad media sin alterar el renderizado GTK ni
introducir trabajo específico de Windows:

- **Scraping por lotes (punto 12, aplicación final):** `apply_scrape_results`
  construye un índice por ID una sola vez y fusiona los resultados contra el
  estado actual. Conserva la protección de las ediciones manuales y no recupera
  juegos eliminados durante el scraping. `Library.put_many` aplica cambios con
  un solo guardado atómico, conserva los overrides de Steam/Faugus y restaura
  el modelo anterior si falla el guardado. Los mensajes retenidos se limitan a
  los cinco que muestra la interfaz, aunque se contabilizan todos los errores.
  La descarga y recopilación de resultados sigue siendo la existente: todavía
  no hay entrega progresiva por lotes durante el scraping y el guardado final
  sigue ejecutándose en el callback de interfaz.
- **Transferencias de arte por bloques (punto 13):** importación local y descarga
  leen bloques de 256 KiB hacia un temporal privado en la carpeta de destino.
  La importación calcula SHA-256 progresivamente; las descargas mantienen su
  identidad de caché basada en URL. Solo se publica con `os.replace` al terminar;
  una excepción elimina el temporal y conserva cualquier archivo anterior.
  Se mantiene expresamente el comportamiento sin límite de tamaño.

Verificación: importar un archivo de 64 MiB registró **0,75 MiB de pico de
asignaciones Python con tracemalloc** durante la transferencia; no mide el RSS
ni la posterior decodificación de imagen. Pruebas de 100 resultados verifican
una llamada a `games` y un guardado, sin sobrescribir una carátula editada a mano
ni restaurar un juego eliminado. También se prueban transferencias interrumpidas,
fallo de reemplazo, hash original y persistencia de overrides/cambios combinados.
No se atribuye a estos cambios una reducción de RAM en reposo de la biblioteca.
