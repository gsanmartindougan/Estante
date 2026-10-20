# Estante 0.2.0

## Español

Estante 0.2.0 amplía las opciones de importación y personalización, e incorpora el modo Lista.

### Novedades

- **Modo Lista:** rueda de logos con el juego seleccionado destacado, carátula y datos del juego. Puede colocarse a la izquierda, derecha, arriba o abajo, con tamaño de logos y carátula configurable.
- **Importación manual de Steam y Faugus** desde Ajustes. Detecta Steam nativo y Flatpak, incluidas bibliotecas en otros discos. Organiza los juegos en las categorías Steam y Faugus y omite las entradas de Steam de Faugus para evitar duplicados.
- **Scraping por lotes:** completa datos faltantes o reemplaza los existentes. Permite seleccionar carátulas 2:3, 1:1, logos, fondos principales y secundarios de SteamGridDB, además de información de Wikidata.
- **Dos fondos por juego**, con divisiones horizontal, vertical o diagonal y transiciones difuminadas. Los fondos pueden intercambiarse desde el editor.
- **Fondo global o por juego**, con seis fondos incluidos y uno seleccionado por defecto en las instalaciones nuevas.
- **Categorías ampliadas:** asignación de juegos desde Ajustes, orden configurable y categoría principal al iniciar; Todos es la opción predeterminada.
- **Quitar juegos de Estante** sin desinstalarlos. Steam y Faugus respetan las exclusiones al escanear y permiten restaurar los juegos quitados.
- **Ajustes reorganizados** en dos columnas y secciones desplegables, con Guardar siempre visible y atajos de teclado y mando.
- **Mejor navegación con mando:** selección del tipo Sony/Xbox/Nintendo, movimiento entre controles según su posición y desplazamiento por actividad e información.
- **Cambio rápido de apariencia:** Ctrl+Tab / Ctrl+Shift+Tab o LB+RB / L1+R1.

### Correcciones

- Conserva la selección y la posición de la biblioteca al guardar una edición.
- Corrige el escalado de logos y su separación respecto al recuadro del juego seleccionado.
- Añade pausas y reintentos ante limitaciones de Wikidata, respetando `Retry-After`.
- Las imágenes locales y descargadas ya no tienen un límite de tamaño impuesto por Estante.
- La biblioteca vacía ofrece escanear juegos o añadir un juego local.

### Instalación y actualización

- Descarga **Estante-0.2.0-x86_64.AppImage**. Recomendamos **Gear Lever** para integrarlo en el escritorio.
- También se incluye **Estante-0.2.0-linux.tar.gz**, con el instalador nativo y las instrucciones del README.
- Consulta **SHA256SUMS** para verificar los archivos descargados.
- Las bibliotecas existentes de Faugus se conservan al pasar a la importación manual. Los juegos nuevos requieren un escaneo desde Ajustes.

### Validación

- **151 pruebas automatizadas superadas**.
- El proceso de construcción comprueba las dependencias del AppImage, la carga de fondos e imágenes y la composición de fondos divididos.
- La compatibilidad gráfica en otras distribuciones, Wayland y X11 necesita más pruebas. Las comprobaciones automatizadas no sustituyen esa validación.

---

## English

Estante 0.2.0 expands importing and customization and introduces the List layout.

### What's new

- **List layout:** a logo wheel highlights the selected game alongside its cover and details. Place it on the left, right, top or bottom and adjust logo and cover sizes.
- **Manual Steam and Faugus imports** from Settings. Supports native and Flatpak Steam, including libraries on other drives. Imports use Steam and Faugus categories; Faugus entries launched through Steam are skipped to avoid duplicates.
- **Batch scraping:** complete missing data or replace existing data. Select portrait 2:3 covers, square 1:1 covers, logos, primary and secondary backgrounds from SteamGridDB, plus information from Wikidata.
- **Two backgrounds per game**, with horizontal, vertical or diagonal splits and blended seams. Swap the backgrounds from the editor.
- **Global or per-game backgrounds**, with six bundled backgrounds and a default selection for fresh installations.
- **Expanded categories:** assign games in Settings, customize their order and choose a startup category. All remains the default.
- **Remove games from Estante** without uninstalling them. Steam and Faugus scans respect exclusions, and removed imports can be restored.
- **Reorganized settings:** two columns, collapsible sections, an always-visible Save button and keyboard/controller shortcuts.
- **Improved controller navigation:** Sony/Xbox/Nintendo button hints, directional navigation based on control positions and scrolling through activity and game information.
- **Quick layout switching:** Ctrl+Tab / Ctrl+Shift+Tab or LB+RB / L1+R1.

### Fixes

- Preserve library selection and position when saving edits.
- Correct logo scaling and spacing around the selected game's capsule.
- Pace Wikidata requests and retry rate-limited responses while respecting `Retry-After`.
- Remove Estante's size limit for local and downloaded images.
- Offer scanning and local game creation when the library is empty.

### Installation and updates

- Download **Estante-0.2.0-x86_64.AppImage**. We recommend **Gear Lever** for desktop integration.
- **Estante-0.2.0-linux.tar.gz** includes the native installer and README instructions.
- Use **SHA256SUMS** to verify downloaded files.
- Existing Faugus libraries are preserved when switching to manual imports. Import new games by scanning from Settings.

### Validation

- **151 automated tests passed**.
- The build checks AppImage dependencies, bundled backgrounds, image decoding and split background rendering.
- Graphical compatibility across other distributions, Wayland and X11 needs further testing. Automated checks do not replace that validation.
