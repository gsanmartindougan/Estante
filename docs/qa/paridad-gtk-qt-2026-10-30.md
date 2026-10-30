# Revisión GTK → Qt y cierre de mantenimiento — 30 de octubre de 2026

## Resultado y versión

Revisión del árbol local basado en `689645b`, con reorganización de módulos, correcciones de imágenes y explorador local aprobados. Las pruebas corresponden a este árbol modificado, no al binario publicado 0.3.0. El usuario confirma que el nuevo explorador funciona con su mando físico.

Los recorridos cubiertos pasan, pero no se considera cerrada la paridad: quedan tres diferencias comprobadas en los ajustes. No se han implementado correcciones en esta revisión de QA ni publicado una versión.

## Cobertura

| Área | Resultado y evidencia |
|---|---|
| Cuatro modos, búsqueda, lista circular y entrada al editor | Pasado: check_qt_migration.py, perfil de 100 juegos |
| Ajustes con barra lateral, tarjetas, radios y guardado | Pasado: check_qt_gtk_settings.py, check_qt_scan_services.py |
| Categorías, orden, principal y membresías | Pasado: check_qt_categories.py |
| Salvapantallas, selección de fondo y descarga al salir de ajustes | Pasado: check_qt_screensaver_settings.py, check_qt_settings_lifecycle.py |
| Editor único, ficha, imágenes, categorías y ejecución | Pasado: check_qt_editor_panel.py |
| Explorador local con miniaturas y mando | Pasado: check_qt_file_browser.py; además, confirmado por el usuario con mando real |
| Imágenes pequeñas, caché y trabajo del editor cerrado | Pasado: check_qt_images.py, check_qt_closed_editor_work.py, check_qt_optimization_ui.py |
| Heroic, estado de launchers y cierre manual | Pasado con dobles: check_qt_heroic.py, check_qt_launcher_status.py, check_qt_manual_launcher_close.py |
| Inicio de juego y pantalla Jugando | Pasado con simulación: check_qt_launch_ui.py, check_qt_playing_memory.py |
| Teclado integrado | Pasado: check_qt_builtin_keyboard.py |
| Backend y compatibilidad de estructura/instalación | 433 pruebas unitarias, una omitida por dependencia opcional; Qt/GTK/instalador --version correctos |

Las 17 comprobaciones Qt finalizaron con código 0, sin diagnósticos de error capturados por el ejecutor. [Resultados por prueba](evidence-2026-10-30/checks.json). Tiempo agregado: 64,5 s. No se ha repetido el estrés prolongado de la fase anterior porque no ha cambiado el proveedor desde su verificación.

## Hallazgos

### QT-PAR-001 — Selector del fondo global incompleto

- Tipo: carencia funcional de migración; prioridad P2; estado confirmado por inspección.
- Responsable: interface-design para composición/interacción; backend-design para importar y validar sin bloquear la UI.
- Ubicación: `qt_app/settings_schema.py:34`, `qt_app/settings_schema.py:126`, `qt_app/SettingControl.qml` (componente field). Referencia GTK: `gtk_app/settings_view.py`, `SettingsView.global_page`, líneas 914–1005.
- Pasos: Ajustes → Globales → Origen del fondo. Seleccionar Global.
- Observado: la imagen se elige mediante un campo de ruta o identificador bundled; no hay galería de fondos integrados, selector local ni descarga por URL en este grupo.
- Esperado: las funciones existentes de GTK permiten elegir sin conocer rutas, con previews e importación local/URL. El nuevo explorador del editor todavía no está conectado a este ajuste.
- Impacto: configuración poco utilizable con mando; escribir una URL no equivale a importarla, porque `LibraryController.artwork` resuelve archivos locales.
- Recomendación: reutilizar el selector de fondos existente de `SettingControl` y el explorador aprobado, incorporando un destino de selección de ajustes que no modifique la carátula del juego. Importar URL mediante el flujo asíncrono con validación. Mantener borrador hasta Guardar globales.
- Aceptación: elegir un fondo integrado, local y por URL; mostrar previews; navegar y confirmar con mando; cancelar conserva el valor anterior; guardar persiste y respeta otros ajustes; cerrar libera el explorador. Validar con perfiles temporales y dobles de red.

### QT-PAR-002 — Se guarda un fondo global inexistente como válido

- Tipo: fallo de validación; prioridad P2; estado reproducido.
- Responsable: backend-design.
- Ubicación: `qt_app/management.py`, `Manager.saveSettingValues`; `qt_app/settings_schema.py`, `merge_values`; referencia GTK: `gtk_app/settings_view.py:1013`.
- Pasos: seleccionar origen Global, escribir la ruta de un archivo inexistente y guardar.
- Observado: se persiste el origen Global y la ruta inexistente; mensaje «Ajustes guardados». El fondo no puede resolverse.
- Esperado: rechazar la selección, explicar el error y conservar el último ajuste válido, como hace GTK al comprobar el fondo antes de guardar.
- Evidencia: [reproducción ejecutable](probe-settings-parity.py), [resultado](evidence-2026-10-30/settings-parity.json), caso missing-global-image.
- Recomendación: validar el estado final combinado del borrador al guardar. Admitir los fondos bundled existentes y archivos compatibles; no interpretar una URL remota como una ruta válida. No sobrescribir ajustes si falla.
- Aceptación: ruta inexistente, imagen inválida y bundled desconocido producen error sin alterar disco; archivos válidos y bundled conocido se guardan; se conservan campos desconocidos.

### QT-PAR-003 — Color inválido del anillo se acepta al guardar

- Tipo: fallo de validación; prioridad P2; estado reproducido.
- Responsable: backend-design; interface-design solo para presentar el error junto al control existente.
- Ubicación: `qt_app/settings_schema.py:57`, `qt_app/settings_schema.py:87`; referencia GTK: `gtk_app/settings_view.py:1194`.
- Pasos: apariencia Grid → Anillo de selección → Color, introducir `not-a-color` y guardar.
- Observado: el valor inválido se persiste con mensaje «Ajustes guardados»; `ring_for` lo transmite sin validar al renderizador.
- Esperado: rechazarlo con explicación y mantener el color previo; GTK valida mediante Gdk.RGBA.parse antes de guardar.
- Evidencia: [resultado de reproducción](evidence-2026-10-30/settings-parity.json), caso invalid-ring-color.
- Recomendación: validar los colores con un parser compatible con los formatos ya guardados por GTK, incluidos rgb()/rgba(); no limitarse a una expresión de hexadecimales.
- Aceptación: rechazo de valores inválidos sin modificar disco; aceptación y renderizado de #hex, colores con nombre y formatos rgb()/rgba() heredados; regresión por cada modo.

## Límites y pendientes ya conocidos

- Pruebas Qt fuera de pantalla, sin cambiar de tag ni robar foco; no se mide GPU, VRAM, FPS ni integración real con Wayland.
- Launchers, red y partidas reales se simulan. La confirmación con mando del usuario cubre el explorador, no todos los flujos de esta tabla.
- Las pausas puntuales de las mediciones anteriores siguen pendientes de observación en uso real; no son un nuevo fallo demostrado ni se afirman corregidas.
- La compatibilidad del AppImage entre distribuciones sigue sin matriz de validación. No se reconstruye ni reemplaza el paquete publicado en esta revisión.
- La revisión se centra en recorridos y ajustes de migración; no constituye una auditoría exhaustiva de todas las combinaciones, accesibilidad o hardware.

## Preparación del mantenimiento

Reorganización y correcciones verificadas listas para un punto de control local. La identidad `brand/` es trabajo independiente y queda fuera del punto de control. Notas de cambios sin publicar preparadas en RELEASE_NOTES.md. Mantener la versión 0.3.0 y no crear tag/release hasta resolver QT-PAR-001/002/003, repetir sus casos y construir/verificar los nuevos paquetes.
