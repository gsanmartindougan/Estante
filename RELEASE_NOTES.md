# Estante 0.3.0 — Qt en Linux

La interfaz principal de Estante migra de GTK 4 a **Qt Quick / PySide6**. Linux sigue
siendo la plataforma principal y GTK permanece disponible con `run-gtk.sh`.

## Cambios principales

- Cuatro apariencias en Qt: Grid, Carousel, Sense y Lista, con colores del tema del
  sistema, fondos configurables y navegación por mando, teclado y ratón.
- Grid paginado: 10 juegos por página por defecto, cantidad configurable y cambio
  con L3/R3, LB/RB o los botones en pantalla.
- Ajustes organizados por apariencia y edición de juegos en un único panel.
- Teclado integrado para mando como alternativa a los teclados del sistema.
- Importación de Heroic (Epic, GOG, Amazon y juegos locales), además de Steam,
  Faugus, scripts y AppImages; instalaciones nativas y Flatpak.
- Opciones de inicio/cierre de launchers e indicadores de estado; botones manuales
  Abrir/Cerrar en la barra lateral de ajustes.
- Pantalla «Iniciando» durante un mínimo de 25 segundos y pantalla ligera
  «Jugando» cuando Estante permanece abierto. Se descarga la biblioteca mientras
  se juega y se restaura al terminar.
- Modelos de imágenes acotados, miniaturas locales y descarga de las páginas de
  ajustes al cerrarlas. No se garantiza una reducción fija de RAM.
- Nuevos vídeos y miniaturas de la interfaz Qt en el README.

## Descargas

- **Estante-0.3.0-x86_64.AppImage**: Python, Qt y SDL incluidos; no requiere instalar
  PySide6. Hazlo ejecutable o intégralo con Gear Lever.
- **Estante-0.3.0-linux.tar.gz**: código e instalador. Consulta el README para crear
  un entorno Python persistente con `requirements-qt.txt`.
- **SHA256SUMS**: sumas de comprobación de los dos paquetes.

La biblioteca y los ajustes existentes se conservan. No ejecutes GTK y Qt a la vez
sobre los mismos datos.

## Validación y límites

Pruebas unitarias y recorridos Qt con perfiles temporales; autocomprobación del
AppImage y arranque con una biblioteca sintética de 100 juegos. Los flujos de
launchers se verificaron con procesos simulados, sin cerrar aplicaciones del usuario.
El AppImage se ha validado en la máquina de construcción; no se ha completado una
matriz de compatibilidad entre distribuciones y GPU. Windows no forma parte de
esta versión. La disponibilidad de un teclado externo depende del compositor;
el teclado integrado permite escribir con mando sin esa integración.

---

## English

Estante's default Linux frontend moves to **Qt Quick / PySide6**. This release
includes all four layouts, configurable grid pagination (10 games per page),
gamepad-friendly settings and a single game editor, built-in keyboard fallback,
Heroic imports alongside Steam/Faugus, launcher controls, and a lightweight playing
screen that unloads the library. GTK remains available through `run-gtk.sh`.

Download the self-contained x86_64 AppImage or the source installer archive and
verify them with `SHA256SUMS`. Existing library data is preserved; do not run both
frontends on the same data simultaneously. The AppImage was checked on the build
machine; cross-distribution/GPU validation is not complete. Windows is not included.
