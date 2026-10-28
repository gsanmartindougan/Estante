# Migración Qt — 24 de octubre de 2026

La entrada principal pasa a Qt Quick/PySide6 en Linux. Se conservan el backend,
el formato de biblioteca, las exclusiones de importación y el supervisor de
partidas. La alternativa GTK se ejecuta con `run-gtk.sh`; no hay migración de datos
que deshacer. No ejecutar escritores GTK y Qt simultáneamente.

## Cobertura

Cuatro apariencias virtualizadas; filtros/categorías/iconos; alta y edición local;
ficha y actividad; importadores Steam/Faugus; imágenes locales, URL y proveedores;
descarga masiva; ajustes; teclado virtual y navegación de formularios con mando;
bandeja; salvapantallas; loader con transición; lanzamiento y supervisión Linux;
instalación y AppDir Qt. Se reutilizan los módulos existentes sin importar GTK.
La ficha conserva borradores al fallar validación y detecta cambios concurrentes.

El carrusel limita los delegados a cinco y las listas/cuadrículas reutilizan los
visibles, sin decodificar toda la colección. Cambiar al salvapantallas o bandeja
retira el modelo visual y las imágenes de la biblioteca. Las búsquedas antiguas
no vuelven a insertar resultados en un panel cerrado. Los trabajos de fondo tienen
cola limitada y no bloquean la salida de la aplicación.

La revisión detectó un problema de entorno del AppDir: lanzar un juego eliminaba
PATH y otras variables del host no modificadas por Qt. Ahora solo se restauran las
variables con marcador explícito del empaquetador. Tiene prueba de regresión.

## Evidencia

- 388 pruebas unitarias generales, incluidos preservación de datos y entorno de lanzamiento.
- Integración Qt de edición con acciones de mando y teclado virtual, errores,
  guardado y cancelación sobre datos temporales.
- Integración de sesión real con script temporal y prevención de doble lanzamiento.
- Integración del loader, transición y registro único de la sesión.
- Integración de gestión con proveedores simulados: galería, errores, iconos SVG,
  créditos y comprobación sin nueva actualización.
- Integración de 100 juegos, cuatro modos, modo mínimo, siete paneles, ajustes,
  categorías vacías, imágenes, alta local y salvapantallas; sin avisos del motor QML.
- AppDir: codecs PNG/JPEG/WebP, SVG y SSL; prueba gráfica con 100 juegos sin GTK.

Prueba sostenida en esta máquina, OpenGL, 2560×1440, 100 identidades y archivos de
imágenes independientes: dos ciclos por los cuatro modos, 100 selecciones por
modo y apertura/cierre de ajustes. RSS inicial 284,9 MiB; final 308,7 MiB, PSS final
231,6 MiB. Las medidas al terminar cada modo estuvieron entre 304,5 y 325,7 MiB
RSS. No es una medida del máximo instantáneo ni de VRAM. No demuestra una reducción
frente a GTK sin repetir idéntica carga y configuración; sí acota el crecimiento
en este recorrido. Herramienta reproducible: `tools/qt_stress.py`.

## Límites de la validación

Las acciones de mando se inyectan por el mismo despachador de la interfaz; no se
ha pulsado un mando físico. No se han lanzado los juegos reales del usuario ni
probado la transferencia Qt a systemd con una partida Steam/Faugus. Las APIs
remotas se simulan en la integración y requieren credenciales válidas para uso real.
El estilo no busca igualdad exacta de píxeles con GTK. La composición de fondos se ha contrastado con el widget GTK original: encaje
Completo/Arriba/Abajo, degradado unilateral, regiones independientes y relleno
por color dominante o desenfoque. La prueba gráfica de 12 casos tiene una
diferencia media inferior a 4/255 por canal; no afirma identidad de píxeles. Hay mensajes del protocolo
de entrada de texto de Qt Wayland durante cambios de foco, sin fallo de prueba.
El AppDir se valida localmente; queda pendiente la matriz de distribuciones y una
partida real antes de publicar una versión. No se publica ni instala globalmente
ningún artefacto en esta sesión. Windows se abordará posteriormente.
