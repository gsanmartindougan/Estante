# Explorador local — v1 aprobada e implementada

Alcance: sustituir el listado mínimo de EditorArtwork.qml dentro del mismo panel de edición. No abre ventanas adicionales. Aprobada por el usuario con «Adelante». Implementación en LocalImageBrowser.qml, integrada en EditorArtwork.qml.

Editable: explorador-v1.figcraft. Frames: catálogo, escritorio 1280×800 y compacto 960×700. Imágenes de ejemplo procedentes de assets/backgrounds; textos/dimensiones son ilustrativos. La composición conserva ConsoleTheme: los colores definitivos siguen la paleta/acento del usuario. brand/brand-tokens.json está en estado proposed y no reemplaza la paleta del producto.

## Inventario y comportamiento

- Cabecera: título contextual y volver al editor; conserva el tipo de imagen que se estaba eligiendo.
- Ruta: segmentos navegables y subir; empieza en Imágenes del usuario si existe, si no en Inicio. No muestra . y .. como archivos.
- Accesos: Inicio, Imágenes, Descargas según disponibilidad; foco visible y nombres accesibles.
- Cuadrícula: carpetas primero, miniaturas ajustadas sin recorte, nombre debajo; dos columnas en compacto, tres en escritorio, más según anchura. Scroll vertical, selección conservada al volver a una carpeta. Foco y selección distinguibles.
- Vista previa: imagen completa del elemento seleccionado, nombre, dimensiones y tamaño reales. Transparencia con damero; errores con explicación, sin imagen rota.
- Acción Usar imagen visible y atajo X; deshabilitada en carpetas, durante importación y para archivos inválidos. No importar al mover el foco. Guardar conserva los atajos existentes del editor.
- Mando: cruceta recorre cuadrícula por filas; A abre carpeta o selecciona archivo; B sube carpeta, y desde la raíz de navegación vuelve al editor; X confirma archivo. Transiciones entre accesos, ruta, cuadrícula y botón sin trampas de foco. Ratón y teclado también disponibles.
- Carga: miniaturas asíncronas al tamaño visible, sin cargar originales completos de toda la carpeta; cancelar trabajo fuera de vista y descargar el explorador al salir. Una sola vista previa de tamaño acotado. Sin animaciones decorativas; foco inmediato y compatible con movimiento reducido.
- Estados pendientes de implementar: carpeta vacía, permiso denegado, archivo borrado, imagen inválida y carga. Mantener ruta y Volver operativos; mensaje en el área de contenido y Usar imagen deshabilitado.

Los frames son maquetas estáticas editables. Las interacciones anteriores están especificadas, no ejecutadas en un prototipo ni verificadas en producto. Previews exportadas y revisadas; archivo reabierto mediante info de FigCraft CLI 0.12.1, sin abrir ventanas ni cambiar foco.

## Implementación y verificación

El panel crece hasta 1280 px al navegar archivos y vuelve a su anchura habitual al salir. Los accesos usan QStandardPaths; las dimensiones y tamaño se consultan con Manager.localImageInfo sin decodificar el original completo. Las miniaturas se decodifican de forma asíncrona, con sourceSize acotado, cache desactivada y fuentes vacías al salir del área visible o entrar en el pool. El Loader destruye el explorador al cerrarlo. La importación sigue usando el validador y el flujo existentes del editor.

Prueba: `.venv-qt/bin/python tests/check_qt_file_browser.py`, fuera de pantalla, 70 imágenes más carpeta vacía, archivo inválido y archivo no compatible. Comprueba rutas, A/B/X, confirmación explícita, metadatos, desplazamiento, carga acotada, importación y destrucción al salir. Capturas revisadas a 1280×800 y 1920×1080. Pasan también check_qt_editor_panel.py y check_qt_optimization_ui.py; suite general: 433 pruebas, una omitida. La prueba simula las acciones del mando; queda pendiente la comprobación manual con un dispositivo físico y Wayland.
