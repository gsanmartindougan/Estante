# Estante

Estante organiza una biblioteca de juegos de Steam, Faugus, Heroic y accesos
locales. La aplicación principal está hecha con Rust y Slint; Qt ya no forma
parte de este proyecto.

## Funciones

- Vistas **Lista** y **Grid**, manejables con teclado o mando.
- Importación, búsqueda, categorías y edición de juegos.
- Fondos, covers y logos por juego, con ajustes de presentación.
- Historial de sesiones, protector de pantalla y barra con hora, fecha y batería
  cuando el dispositivo la expone.

Los formatos de biblioteca y ajustes existentes siguen en
`$XDG_DATA_HOME/estante` (normalmente `~/.local/share/estante`).

## Ejecutar e instalar

Desde el código fuente:

```sh
./run.sh
```

Para instalar el binario nativo en `~/.local`:

```sh
./install.sh
```

El AppImage x86_64 está en [GitHub Releases](https://github.com/gsanmartindougan/Estante/releases).
Faugus se instala por separado para iniciar sus juegos.

## Compilar y empaquetar

```sh
cargo build --offline --release --manifest-path rust/Cargo.toml
python3 packaging/build-release.py
python3 packaging/build-appimage.py --appdir-only
```

El empaquetado completo del AppImage necesita además appimage-builder. Python se
usa en los instaladores y empaquetadores, y en herramientas opcionales para
generar materiales de marca. La aplicación instalada y su ejecución diaria no
dependen de Python.

## Proyecto Qt legacy

El frontend Qt se ha separado en el proyecto hermano `estante-qt-legacy`.
Conserva sus fuentes, dependencias, instalador y documentación; no se incluye en
el binario ni en el archivo fuente de Estante principal.
