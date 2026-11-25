# Estructura del proyecto

Estante principal usa Rust y Slint. El frontend Qt/Python legacy vive en el
proyecto independiente `../estante-qt-legacy` y no forma parte del empaquetado
principal.

- `rust/`: aplicación, interfaz Slint, modelo, integraciones y pruebas Rust.
- `assets/backgrounds/`: fondos incluidos en la instalación.
- `packaging/`: instalador y herramientas Python para crear instaladores,
  archivos fuente y AppImages. Python no se distribuye ni se ejecuta como
  dependencia de la aplicación.
- `brand/`: identidad visual y materiales de difusión.
- `docs/`: documentación activa de la versión Slint. Las guías, pruebas y
  resultados de la versión Qt anterior se archivaron en `../estante-qt-legacy/docs/history/`.

## Entradas principales

`./run.sh` ejecuta Estante desde el checkout. `./install.sh` instala la
aplicación Slint. `python3 packaging/build-appimage.py` crea el AppImage
principal; no existe selector Qt en este repositorio.

## Compilación

```sh
cargo build --offline --release --manifest-path rust/Cargo.toml
python3 packaging/build-release.py
```

Los datos de usuario siguen en `$XDG_DATA_HOME/estante` para conservar
bibliotecas y ajustes existentes.
