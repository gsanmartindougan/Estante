# Auditoría de optimización de Estante

Fecha: 23 de octubre de 2026. Revisión del código actual, después de los cambios de cristal, caché, ajustes y salvapantallas.

## Alcance y evidencia

Revisados los módulos de interfaz, ajustes, imágenes, carruseles, fondos, salvapantallas, biblioteca, importación Steam/Faugus, scraping, metadatos, controles, tray, supervisión de partidas, actualizaciones, instalación y empaquetado. La revisión no modifica el comportamiento de la aplicación.

- 321 pruebas existentes pasan.
- Se ha reproducido una carrera de la caché con dos hilos y una decodificación controlada.
- Se han comprobado por lectura los recorridos y límites descritos abajo.
- No se ha podido ejecutar una medición gráfica en el escritorio real. La revisión no demuestra todavía qué componente explica los 20–40 MB adicionales observados por el usuario, ni permite prometer una cifra de ahorro.
- «Comprobado» significa que el mecanismo está en el código; no que su coste en RAM o tiempo esté cuantificado en el escritorio.

## Prioridad alta

### 1. Corregir la carga simultánea de una misma imagen

**Estado: reproducido. Esfuerzo: bajo/medio. Beneficio: exactitud de la caché y evitar decodificaciones duplicadas.**

`ImageCache._load` comprueba si existe la entrada, libera el bloqueo para decodificar y vuelve a insertar sin comprobar si otro hilo ya la insertó. El worker asíncrono y los consumidores de `images.load` pueden alcanzar este recorrido simultáneamente.

Reproducción: dos llamadas simultáneas para una imagen de 128×128 RGBA produjeron dos texturas distintas y una sola entrada. El contador marcó 131.072 bytes aunque la entrada sumaba 65.536. Después de expulsarla, quedaron cero entradas y el contador siguió marcando 65.536 bytes. Ese contador residual **no demuestra una fuga equivalente de memoria física**, pero invalida el presupuesto y las expulsiones.

**Optimización:** compartir las cargas en curso; como mínimo, comprobar de nuevo la clave bajo el bloqueo antes de insertar y contabilizar. Una clave debe tener una única entrada contabilizada.

**Prueba de aceptación:** dos consumidores concurrentes reciben el recurso compartido; el contador coincide con las entradas y termina en cero al vaciarse.

Código: [image_cache.py:231](/home/gabriel/personal/estante/image_cache.py:231).

### 2. Limitar y cancelar los trabajos de galerías y paneles

**Estado: comprobado. Esfuerzo: medio. Beneficio: picos de RAM, red, hilos y liberación al cerrar paneles.**

`Shelf.background` crea un hilo nuevo por llamada. La galería muestra hasta 18 imágenes; para SteamGridDB puede lanzar una consulta de tamaño y una descarga por imagen: hasta 36 trabajos independientes, además de las consultas de la galería. Las comprobaciones de revisión evitan ciertas actualizaciones tardías, pero no cancelan las descargas ni liberan inmediatamente sus closures. Cerrar y abrir galerías puede solapar generaciones de trabajo.

**Optimización:** cola con concurrencia limitada y cancelación por panel/generación. Descargar primero lo visible; descartar trabajos pendientes de una búsqueda anterior. La cancelación de una respuesta no necesita interrumpir a la fuerza un hilo, pero sí impedir el trabajo siguiente y soltar los callbacks.

**Prueba:** abrir/cerrar varias galerías con red lenta; número de workers y cola acotados, sin actualizaciones tardías ni crecimiento acumulado.

Código: [estante.py:1728](/home/gabriel/personal/estante/estante.py:1728), [estante.py:3259](/home/gabriel/personal/estante/estante.py:3259).

### 3. Sacar decodificaciones y validaciones del hilo de GTK

**Estado: comprobado. Esfuerzo: medio. Beneficio: fluidez al abrir ajustes, editores y galerías.**

Todavía hay `images.load` síncronos en ajustes y callbacks ejecutados por GTK: seis fondos de muestra, importación de imágenes y validación de imágenes externas, entre otros. Un fallo de caché puede leer, decodificar y preparar miniaturas antes de devolver el control a GTK. Validar mediante `images.load(path)` también solicita una imagen de hasta 1920×1080 aunque solo se quiera comprobar que el archivo es válido.

**Optimización:** usar peticiones asíncronas con cancelación y separar validación de formato/dimensiones de la creación de una textura para pantalla.

**Prueba:** caché fría y archivos grandes; apertura y navegación sin pausas de decodificación en el hilo principal.

Código: [settings_view.py:947](/home/gabriel/personal/estante/settings_view.py:947), [settings_view.py:967](/home/gabriel/personal/estante/settings_view.py:967), [estante.py:3279](/home/gabriel/personal/estante/estante.py:3279).

### 4. Evitar la decodificación completa del original en AppImage

**Estado: comprobado en esa ruta. Esfuerzo: medio/alto por compatibilidad del empaquetado. Beneficio: picos de memoria con originales grandes.**

Con `ESTANTE_APPDIR`, el decoder abre primero el archivo como `Gdk.Texture`, obtiene un pixbuf y después lo reduce. El tamaño final solicitado no limita la textura original intermedia. En la ejecución desde código fuente se intenta primero otra ruta escalada; no debe atribuirse automáticamente este problema a las mediciones actuales desde fuente.

**Optimización:** disponer de una ruta de decodificación escalada compatible con el AppImage, conservando las pruebas de PNG/JPEG y el funcionamiento sin procesos de codecs externos.

**Prueba:** original de gran resolución y miniatura pequeña; comparar el pico de RSS de fuente y AppImage, en caché fría y caliente.

Código: [image_cache.py:70](/home/gabriel/personal/estante/image_cache.py:70).

### 5. Hacer incremental la actualización de la biblioteca

**Estado: comprobado. Esfuerzo: medio. Beneficio: menos creación/destrucción de widgets y menos picos transitorios.**

`reload` reconstruye las vistas. Un cambio de metadatos o de imagen termina destruyendo y creando tarjetas de nuevo. En lista, `update_list_cover` también sustituye el widget de carátula cada vez que se ejecuta, aunque ciertas llamadas vuelvan sobre el mismo juego.

**Optimización:** actualizar solo la tarjeta y los campos afectados; reconstruir cuando cambien el filtro, la estructura o la apariencia. Reutilizar el widget de la carátula y sustituir su textura cuando corresponda.

**Prueba:** editar la sinopsis o completar una imagen no reconstruye el resto de tarjetas ni repite cargas innecesarias.

Código: [estante.py:1789](/home/gabriel/personal/estante/estante.py:1789), [estante.py:1820](/home/gabriel/personal/estante/estante.py:1820), [estante.py:1977](/home/gabriel/personal/estante/estante.py:1977).

### 6. Liberar los paneles cerrados, además de sus imágenes

**Estado: comprobado. Esfuerzo: bajo/medio. Beneficio: RAM tras usar editores y galerías.**

`close_panel` oculta el revealer y limpia imágenes, pero conserva los hijos del sidebar hasta abrir el siguiente panel. Esos hijos incluyen controles, selectores de archivos y señales. El cierre explícito de ajustes ya se ha reforzado; no debe darse por resuelto el recorrido de los paneles laterales por ese cambio.

**Optimización:** al terminar la transición, desconectar y retirar el contenido del panel cerrado. Comprobar la revisión para no destruir un panel nuevo. Invalidar su trabajo pendiente según el punto 2.

**Prueba:** abrir y cerrar un editor/galería sin abrir otro después; no quedan vivos sus widgets ni callbacks exclusivos.

Código: [estante.py:2434](/home/gabriel/personal/estante/estante.py:2434).

## Prioridad media

### 7. Virtualizar lista, carrusel y Sense para bibliotecas grandes

**Estado: comprobado. Esfuerzo: alto. Beneficio: escala con el tamaño de la categoría.**

La cuadrícula está paginada y la ventana de imágenes está limitada. Sin embargo, los otros modos crean widgets para todos los juegos de la categoría activa. Los carruseles recorren, miden y asignan todos esos widgets durante las animaciones y ordenan su profundidad al dibujar.

**Optimización:** mantener el índice de juegos separado de un conjunto pequeño de widgets reciclados. El movimiento y el alfabeto deben seguir usando el índice completo.

**Prueba:** comparar 100, 1.000 y 5.000 juegos; el número de widgets vivos debe depender de lo visible, no del total.

Código: [estante.py:1820](/home/gabriel/personal/estante/estante.py:1820), [carousel.py:153](/home/gabriel/personal/estante/carousel.py:153), [carousel.py:175](/home/gabriel/personal/estante/carousel.py:175).

**Categorías ocultas:** actualmente se filtran antes de crear las tarjetas. No he encontrado que se creen tarjetas para todas las categorías. Sí se conserva el índice completo de metadatos en `library_games`; eso es distinto de cargar todas sus imágenes.

### 8. Sustituir el callback permanente de tamaño del panel

**Estado: comprobado. Esfuerzo: bajo. Beneficio: actividad en reposo.**

El callback `resize_panel` está registrado en el reloj de fotogramas y devuelve `True` siempre, aunque el panel esté cerrado. Solo calcula una anchura dependiente del tamaño de la ventana.

**Optimización:** actualizarlo al cambiar la asignación/tamaño, o mantener el callback únicamente durante una transición que lo necesite.

**Prueba:** ventana inmóvil con panel cerrado, sin callback por fotograma para esta tarea.

Código: [estante.py:853](/home/gabriel/personal/estante/estante.py:853).

### 9. Reducir el coste de los fondos y de la cápsula de lista

**Estado: recorrido comprobado; coste gráfico pendiente de medición. Esfuerzo: medio.**

La cápsula de lista no reducida vuelve a tomar snapshots de ambos fondos dentro de otro desenfoque. Además, para obtener el color dominante se convierte la textura de fondo a pixbuf antes de reducirla a una muestra pequeña. Son operaciones adicionales sobre imágenes grandes; no puedo afirmar cuánto materializa o reutiliza el renderer de GTK sin medirlo.

**Optimización:** evitar volver a procesar el fondo completo para una cápsula local; reutilizar un resultado pequeño cuando sea posible. Calcular el color dominante desde una muestra pequeña, evitando la conversión de la textura grande cuando no sea necesaria.

**Prueba:** mismo fondo, resolución y navegación; comparar CPU, tiempos de fotograma y memoria gráfica, manteniendo el aspecto.

Código: [estante.py:1987](/home/gabriel/personal/estante/estante.py:1987), [estante.py:302](/home/gabriel/personal/estante/estante.py:302).

### 10. Ajustar resoluciones y variantes a su uso real

**Estado: comprobado. Esfuerzo: medio. Beneficio: memoria de imágenes.**

Carrusel y Sense solicitan una escala de 2,5 en `request_picture`, además del factor HiDPI. Para una imagen con suficientes píxeles originales, 2,5 en ambos ejes supone hasta 6,25 veces los píxeles del tamaño base; debe contrastarse con la ampliación realmente aplicada. Lista y cuadrícula ya tienen un tratamiento diferente. `retain_paths` elimina archivos fuera de la selección, pero conserva todas las variantes de tamaño de los archivos permitidos.

**Optimización:** derivar la resolución del tamaño visible, zoom y escala reales; conservar solo variantes útiles y evitar decodificar de nuevo si una ya existente sirve. Mantener un presupuesto conjunto para texturas y trabajo temporal, sin sumar como independientes buffers que compartan almacenamiento.

**Prueba:** calidad suficiente al ampliar; variantes y bytes estables tras recorrer y cambiar de apariencia. Comprimir más un PNG en disco no reduce los píxeles de su textura decodificada.

Código: [estante.py:1757](/home/gabriel/personal/estante/estante.py:1757), [image_cache.py:158](/home/gabriel/personal/estante/image_cache.py:158).

### 11. Aligerar la escritura de miniaturas, también en el salvapantallas

**Estado: comprobado. Esfuerzo: medio. Beneficio: RAM temporal, CPU y disco con caché fría.**

La cola del escritor admite hasta 32 MiB de pixbufs. Cada guardado recorre y ordena los PNG de la carpeta para aplicar la cuota. El salvapantallas tiene caché de texturas de tamaño cero, pero usa el mismo mecanismo de miniaturas y puede tener su propia cola de escritura. «Caché de texturas cero» no significa «sin buffers temporales».

**Optimización:** adaptar el presupuesto del escritor al uso; eliminar trabajos obsoletos antes de codificar; aplicar mantenimiento de disco de forma agrupada, no tras cada archivo. Medir si guardar miniaturas grandes de las diapositivas compensa su coste.

**Prueba:** pase de diapositivas y navegación con caché fría; colas acotadas, bytes pendientes y actividad de escritura vuelven a reposo.

Código: [image_cache.py:291](/home/gabriel/personal/estante/image_cache.py:291), [image_cache.py:345](/home/gabriel/personal/estante/image_cache.py:345), [screensaver.py:87](/home/gabriel/personal/estante/screensaver.py:87).

### 12. Guardar el scraping por lotes y evitar búsquedas repetidas

**Estado: comprobado. Esfuerzo: medio. Beneficio: finalización de scraping y escala de la biblioteca.**

Por cada resultado se llama a `library.games()`, que copia y ordena la biblioteca, y a `put`, que guarda el JSON entero. El bucle de aplicación de resultados se ejecuta en el hilo de GTK. Con muchas modificaciones se repiten ordenaciones y escrituras de toda la biblioteca. Se acumulan además todos los resultados hasta finalizar el trabajo.

**Optimización:** índice por ID, aplicación por lotes y un guardado atómico por lote; conservar la protección que da prioridad a las ediciones manuales. Entregar progresivamente los resultados si la biblioteca es grande.

**Prueba:** N juegos modificados no producen N reordenaciones y N escrituras completas en el hilo principal.

Código: [settings_view.py:321](/home/gabriel/personal/estante/settings_view.py:321), [library.py:123](/home/gabriel/personal/estante/library.py:123), [library.py:138](/home/gabriel/personal/estante/library.py:138), [library.py:62](/home/gabriel/personal/estante/library.py:62).

### 13. Descargar e importar imágenes sin cargar el archivo entero en RAM

**Estado: comprobado. Esfuerzo: bajo/medio. Beneficio: picos de memoria durante importación y red.**

Las descargas de arte usan `response.read()` completo; la importación local usa `read_bytes()` para calcular el hash y copiar. En concurrencia se multiplican esos buffers. El actualizador de AppImage ya utiliza descarga por bloques y sirve de referencia interna.

**Optimización:** copiar por bloques a un temporal, calcular el hash progresivamente y publicar mediante reemplazo atómico. Establecer un límite razonable y configurable internamente para entradas de arte.

**Prueba:** archivo grande sin un buffer del tamaño total por descarga; un fallo no deja un archivo definitivo incompleto.

Código: [library.py:423](/home/gabriel/personal/estante/library.py:423), [library.py:453](/home/gabriel/personal/estante/library.py:453), [updates.py:89](/home/gabriel/personal/estante/updates.py:89).

## Ajustes secundarios, después de medir

### 14. Reducir trabajo periódico de controles y supervisión

**Estado: comprobado; prioridad condicionada al coste real. Esfuerzo: medio.**

El mando se sondea cada 16 ms, incluso cuando se permite lectura en segundo plano. La supervisión recorre `/proc` y lee entornos para identificar los procesos del juego; al arrancar un juego no Steam puede hacer dos recorridos por intervalo. El supervisor separado ya reduce esa frecuencia a un segundo durante la partida.

**Optimización:** frecuencias adaptativas sin perder la capacidad de despertar el salvapantallas; recordar PIDs e identidad de proceso y mantener un escaneo de recuperación para hijos nuevos, wrappers y PID reutilizados. No sustituir la detección por pérdida de foco.

Código: [estante.py:937](/home/gabriel/personal/estante/estante.py:937), [controls.py:166](/home/gabriel/personal/estante/controls.py:166), [game_session.py:14](/home/gabriel/personal/estante/game_session.py:14), [game_session.py:54](/home/gabriel/personal/estante/game_session.py:54).

### 15. Unificar el ciclo de vida de vistas y tareas

**Estado: necesidad de mantenimiento visible en varios recorridos. Esfuerzo: medio.**

Ajustes, sidebar, imágenes, salvapantallas y cambios de apariencia cancelan recursos con recorridos propios. Las limpiezas recientes son útiles, pero `gc.collect`/`malloc_trim` no sustituyen liberar referencias vivas ni buffers del renderer.

**Optimización:** definir qué posee cada vista y una salida explícita que cancele sus tareas, timers y callbacks, suelte imágenes y destruya contenido desechable. Conservar los borradores de ajustes cuando el salvapantallas solo los oculta: destruirlos ahí sería una regresión.

**Prueba:** 20 ciclos de ajustes, galerías, salvapantallas y cambio de aspecto sin crecimiento sostenido de objetos, jobs o memoria privada tras estabilizarse.

Código: [estante.py:3038](/home/gabriel/personal/estante/estante.py:3038), [screensaver.py:256](/home/gabriel/personal/estante/screensaver.py:256), [screensaver.py:335](/home/gabriel/personal/estante/screensaver.py:335), [image_cache.py:31](/home/gabriel/personal/estante/image_cache.py:31).

## Medición necesaria antes de atribuir los 300 MB

El profiler existente mide navegación, tiempos y pico de RSS, pero hace falta ampliar el escenario de aceptación:

1. Mismo monitor, escala, apariencia, selección, fondos, biblioteca y renderer; separar fuente de AppImage.
2. Caché fría y caliente por separado.
3. Tomar RSS, PSS, memoria privada/anónima, bytes de texturas, variantes, colas, hilos y latencias. La memoria gráfica debe medirse aparte: RSS y VRAM no son intercambiables.
4. Recorrer una secuencia fija, volver al mismo juego y esperar a que terminen carga y escritura.
5. Repetir entradas/salidas de ajustes y salvapantallas. Comprobar meseta y recuperación, no exigir que toda memoria compartida o reutilizable desaparezca.
6. Comparar una sola optimización cada vez y conservar calidad de imagen, foco, mandos, borradores y restauración de selección.

No se debe fijar un objetivo universal de 260 MB: depende de los recursos visibles y del entorno. Sí se puede exigir que el mismo recorrido no acumule recursos sin límite y que el consumo por componente tenga una explicación.

## Migración a C o C++

**Mi recomendación: no reescribir la aplicación completa ahora.** Primero corregir los puntos anteriores y medir el reparto entre Python, GTK, texturas, renderer y buffers temporales.

GTK ya está implementado en C y Python accede a esas bibliotecas mediante PyGObject. Migrar la lógica podría reducir parte del coste del intérprete, objetos y llamadas de Python, pero no eliminaría automáticamente texturas grandes, desenfoques, exceso de widgets, trabajo duplicado, descargas o referencias conservadas. Una textura RGBA de las mismas dimensiones necesita sus mismos píxeles independientemente del lenguaje de la lógica.

Tampoco es válido prometer una bajada concreta de los 300 MB con esta auditoría. Los bytes físicos deben medirse; el fallo reproducido del contador de caché ilustra por qué no basta con mirar una cifra interna.

**Si después de medir se justifica código nativo**, empezaría por un componente aislado que aparezca realmente como cuello de botella, o un prototipo mínimo de una apariencia con los mismos recursos. Compararía RAM, CPU, tiempo de fotograma y coste de mantenimiento con el Python optimizado. No portaría de entrada importación, scraping, traducciones, ajustes, mandos y supervisor.

**Si hubiera que elegir entre C y C++ para una migración amplia, preferiría C++** por el manejo de recursos mediante RAII y por poder encapsular lifetimes de trabajos, señales y vistas. Es una elección de mantenimiento, no una garantía de menor RAM. C ofrece acceso directo a la API de GTK, pero exige más disciplina manual para los recursos y aumentaría el riesgo de errores durante una reescritura de una aplicación que sigue cambiando.

Fuentes primarias: [GTK: bindings e implementación en C](https://www.gtk.org/docs/language-bindings/index), [GTK y PyGObject](https://www.gtk.org/docs/language-bindings/python), [C++ Core Guidelines: recursos y RAII](https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines#Rr-raii).

## Orden propuesto

1. Contabilidad y deduplicación de caché; límites/cancelación de trabajos; salida real de paneles.
2. Decodificación asíncrona y tamaños correctos; ruta AppImage; perfil repetible de memoria.
3. Actualizaciones incrementales, quitar el tick permanente y agrupar scraping/escrituras.
4. Medir y optimizar renderizado, miniaturas y recorridos periódicos.
5. Virtualización si las pruebas con bibliotecas grandes la requieren.
6. Valorar un prototipo nativo únicamente con los resultados anteriores.
