# Estructura del proyecto

Slint es el frontend principal. Qt permanece como frontend legacy ejecutable de
forma explícita; esta separación no mueve ni duplica los datos de usuario.

- `rust/`: aplicación principal en Rust, interfaz Slint (`rust/ui/`), modelo,
  integraciones y pruebas de Rust.
- `qt_app/`: frontend Qt Quick/PySide6 legacy, sus componentes QML y entrada
  `__main__.py`.
- `core/`, `integrations/` y `requirements/qt.txt`: soporte Python del frontend
  Qt legacy y sus integraciones.
- `packaging/`: instalador, constructores de AppImage, recursos y metadatos de
  distribución. Por defecto empaqueta Slint; `--frontend qt` selecciona el legacy.
- `assets/`: fondos y recursos de la aplicación.
- `tests/`: pruebas del frontend legacy; las pruebas de Slint viven en
  `rust/src/slint_ui_tests.rs`.
- `tools/`: grabación, diagnóstico y utilidades del proyecto.
- `docs/`: documentación técnica, evidencia histórica y muestras.
- `brand/`: materiales de identidad y difusión; no se incluyen en la instalación.

## Entradas principales

`./run.sh` abre Slint. `./install.sh` instala Slint y compila release si hace
falta. Sin selector, `python3 packaging/build-appimage.py` construye el AppImage
principal.

La ruta Qt legacy requiere una selección explícita:

```sh
./run-qt.sh
./install.sh --frontend qt
python3 packaging/build-appimage.py --frontend qt
```

`run-gtk.sh` se conserva como entrada antigua independiente. La distribución de
fuentes incluye ambos frontends; no ejecutes dos frontends simultáneamente con el
mismo directorio de datos.

## Compilación

```sh
cargo build --offline --release --manifest-path rust/Cargo.toml
python3 packaging/build-release.py
```

El supervisor Qt copia una instantánea mínima de `core/` e `integrations/` a su
carpeta temporal. Así sigue funcionando cuando se cierra el AppImage y desaparece
su punto de montaje. Esos archivos del repositorio no se usan como datos de usuario.
