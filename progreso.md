# Progreso: Grid en Slint

## Objetivo

Dejar la nueva versión Slint con solo los modos List y Grid, portar todos los ajustes y el comportamiento de Grid existentes en Qt, mantener Qt legacy sin cambios y compilar release.

## Tareas

- [x] GRID-01 · Retirar Carousel y Sense de los controles/rutas de Slint y normalizar valores antiguos a List.
- [x] GRID-02 · Añadir a Ajustes los controles Grid: tamaño de carátulas y juegos por página.
- [x] GRID-03 · Añadir todos los ajustes visuales propios de Grid: presentación mínima, fondo (oscurecimiento/desenfoque/posición/división), formato y radio de carátula, detalles del lanzador y anillo de selección.
- [x] GRID-04 · Conectar valores actuales, guardado automático y renderizado de Grid a esos ajustes; verificar que Qt no tenga cambios.
- [x] GRID-05 · Compilar la versión release con `cargo build --offline --release --manifest-path rust/Cargo.toml`.

## Verificación

No se ejecutaron pruebas automatizadas ni se abrió la aplicación. La compilación release terminó correctamente; queda la validación visual interactiva para el usuario.

## Referencia de cobertura Grid

Checklist de solo lectura del esquema Qt: `grid_page_size` (10, 1–100); `grid_zoom` (100, 50–200); `minimal_views.grid` (false); `background_dim.grid` (50, 0–100); `background_blur.grid` (0, 0–40); `cover_formats.grid` (portrait: portrait/square); `hero_positions.grid` (full: full/top/lower); `background_splits.grid` (single: single/horizontal/vertical/diagonal); `cover_radii.grid` (12, 0–40); `show_launcher_details.grid` (true); `selection_rings.grid.focus_ring_enabled` (true); `focus_ring_color` (#ffffff); `focus_ring_width` (3, 0–12); `focus_ring_radius` (18, 0–50). Los ajustes globales de origen y relleno del fondo también deben seguir aplicándose a Grid.

## Objetivo activo: Slint principal, Qt legacy

**Decisión confirmada:** Slint es la versión principal de Estante y ofrece List y
Grid. Qt permanece disponible como frontend legacy mediante selección explícita;
Carousel y Sense no forman parte de Slint. Los datos de usuario y los formatos de
configuración se conservan.

### Tareas

- [x] SLINT-01 · Establecer Slint como entrada y destino de instalación predeterminados. Prioridad: P1. Responsable: Codex. Criterio: `./run.sh`, `./install.sh` y el AppImage sin selector eligen Slint; `run-qt.sh` y `--frontend qt` conservan el acceso legacy. Evidencia: `run.sh`, `install.sh`, `packaging/install.py` y `packaging/build-appimage.py`.
- [x] SLINT-02 · Alinear documentación de usuario y mapa de carpetas con la arquitectura actual. Prioridad: P1. Responsable: Codex + `slint_arch_review`. Criterio: README español/inglés y mapa clasifican Slint como principal, Qt como legacy y Carousel/Sense como Qt; `rust/README.md` documenta Slint como principal. Evidencia: `README.md`, `README.en.md`, `qt_app/README.md`, `rust/README.md` y `docs/estructura-del-proyecto.md`.
- [x] SLINT-03 · Compilar release Slint y comprobar la sintaxis de los scripts de entrada. Prioridad: P1. Responsable: Codex. Depende de SLINT-01 y SLINT-02. Criterio: compilación release correcta y `sh -n` correcto para los scripts. Evidencia: build release y comprobaciones de comandos.

### Verificación

`cargo build --offline --release --manifest-path rust/Cargo.toml`, `sh -n run.sh run-qt.sh install.sh`, `./install.sh --help`, `python3 packaging/build-appimage.py --help` y `git diff --check` terminaron correctamente. No se ejecutó la interfaz ni pruebas automatizadas.

## Objetivo activo: merge y release 0.5.0

- [x] REL-01 · Consolidar los cambios Slint de `codex/port-a-slint` en un commit.
- [x] REL-02 · Compilar Slint y generar el archivo fuente, AppImage y SHA256SUMS.
- [x] REL-03 · Fusionar la rama en `main` y subirla a GitHub.
- [x] REL-04 · Publicar la release `v0.5.0` con los tres artefactos.

### Verificación

`cargo build --offline --locked --release --manifest-path rust/Cargo.toml` terminó
correctamente; el AppImage pasó `--self-test` antes y después de empaquetarlo; los
SHA256 verificaron. El commit `82d864d` se fusionó por fast-forward en `main`, y
GitHub confirma los tres assets de `v0.5.0`: https://github.com/gsanmartindougan/Estante/releases/tag/v0.5.0.

## Objetivo: separar Qt legacy y limpiar Python de Estante principal

- [x] Mover el frontend Qt, módulos Python, dependencias, instalador, pruebas y herramientas a `../estante-qt-legacy`.
- [x] Trasladar el entorno Qt local y los paquetes/AppDirs Qt anteriores al proyecto legacy para conservar su ejecución sin mezclarlos con Slint.
- [x] Mover documentación, benchmarks y capturas específicas de la interfaz Qt a `estante-qt-legacy/docs/history/`.
- [x] Mantener en Estante principal solo sus scripts Python de instalación/empaquetado, herramientas opcionales de marca y comprobaciones de empaquetado.
- [x] Compilar Slint en release y comprobar que el archivo fuente no incluye módulos Python ni Qt.

La aplicación principal no usa Python en ejecución. Los scripts Python restantes son utilidades de desarrollo, instalación, empaquetado y generación de materiales de marca.
