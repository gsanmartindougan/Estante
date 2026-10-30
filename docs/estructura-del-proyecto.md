# Estructura del proyecto

- `core/`: biblioteca, ajustes compartidos, controles, sesiones, supervisor,
  gestión de memoria, traducciones y versión.
- `integrations/`: importación Steam/Heroic, metadatos, imágenes y actualizaciones.
- `qt_app/`: interfaz Qt, componentes QML, adaptadores y entrada `__main__.py`.
- `gtk_app/`: interfaz GTK anterior y sus componentes gráficos.
- `packaging/`: instalador, constructores, entradas AppImage e iconos de distribución.
- `requirements/`: dependencias Python; `qt.txt` es el entorno de la interfaz Qt.
- `assets/`: fondos y conceptos de iconos; `concepts/` conserva los dos PNG originales.
- `tests/`: pruebas unitarias y recorridos de interfaz.
- `tools/`: grabación de vídeos, diagnóstico y pruebas de rendimiento.
- `docs/`: documentación técnica, resultados de validación y vídeos de muestra.
- `brand/`: materiales de identidad y difusión; no se incluyen en la instalación.

La raíz mantiene los README, las notas de versión y los scripts públicos de entrada:

```sh
./run.sh
./run-qt.sh
./run-gtk.sh
./install.sh
```

La instalación directa está en `packaging/install.py` y las dependencias Qt en
`requirements/qt.txt`. El paquete instalable conserva estos mismos directorios.
Los datos personales siguen en la ubicación existente; la reorganización solo
cambia los archivos de código, recursos y herramientas del proyecto.

```sh
.venv-qt/bin/pip install -r requirements/qt.txt
python3 -m unittest discover -s tests
QT_QPA_PLATFORM=offscreen .venv-qt/bin/python tests/check_qt_migration.py
.venv-qt/bin/python packaging/build-appimage.py --frontend qt
python3 packaging/build-release.py
```

El supervisor copia una instantánea mínima de `core/` e `integrations/` a su carpeta
temporal. Así puede seguir funcionando cuando se cierra el AppImage y desaparece
su punto de montaje. Los archivos del repositorio no se usan como datos de usuario.
