# Integración de Heroic en Linux

- Importación manual desde Escaneo y scraping; sin lectura de credenciales.
- Raíces: `$XDG_CONFIG_HOME/heroic` y
  `~/.var/app/com.heroicgameslauncher.hgl/config/heroic`.
- Epic: `legendaryConfig/legendary/installed.json`, con la ubicación heredada
  `../legendary/installed.json` como alternativa.
- GOG: `gog_store/installed.json`, array `installed`.
- Amazon: `nile_config/nile/installed.json`, array con `id` y `path`.
- Locales: `sideload_apps/library.json`, array `games`; solo ejecutables presentes.
- Se omiten DLC y directorios ausentes; una configuración JSON corrupta produce
  un error sin sustituir el snapshot anterior de Estante.
- IDs estables `heroic:<runner>:<app_name>` evitan duplicados entre instalaciones.
- El escaneo actualiza el snapshot y conserva overrides y exclusiones de Estante.
- Las imágenes locales se reutilizan; las URLs HTTPS de las cachés de biblioteca
  se descargan en segundo plano con el importador de imágenes existente y un
  guardado por lote. No se requiere una clave de SteamGridDB.
- Lanzamiento: `heroic --no-gui 'heroic://launch?appName=...&runner=...&gui=false'`
  o equivalente Flatpak. No se invoca Wine ni se construyen comandos de shell.
- Supervisión: entorno `HEROIC_APP_NAME` + `HEROIC_APP_RUNNER`, no la duración del
  proceso de la GUI ni su foco. El mismo criterio sirve al supervisor de restauración.
- El instalador incluye `heroic_import.py` y los nuevos componentes Qt.

Formatos contrastados con el código oficial de Heroic, revisión
`509a34feea8541b73c928e289f2cf262d432db4a`:
[tipos de instalación Epic](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/509a34feea8541b73c928e289f2cf262d432db4a/src/common/types/legendary.ts),
[GOG](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/509a34feea8541b73c928e289f2cf262d432db4a/src/backend/storeManagers/gog/electronStores.ts),
[Amazon](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/509a34feea8541b73c928e289f2cf262d432db4a/src/common/types/nile.ts),
[protocolo de lanzamiento](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/509a34feea8541b73c928e289f2cf262d432db4a/src/backend/protocol.ts),
[entorno del juego](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/509a34feea8541b73c928e289f2cf262d432db4a/src/backend/launcher.ts).

Verificación: `tests/test_heroic_import.py` y `tests/check_qt_heroic.py`, perfiles
sintéticos temporales y modo offscreen. No se han lanzado Heroic ni juegos reales,
ni se han alterado sus configuraciones en el equipo del usuario. No había una
biblioteca de Heroic inicializada disponible para probar una partida real.

## Inicio y salida

En Globales → Inicio hay opciones independientes `start_heroic_on_start` y
`close_heroic_on_exit`, desactivadas por defecto. El arranque usa `heroic --no-gui`
o Flatpak; el monitor reconoce tanto el ejecutable Heroic como la distribución
Electron con `heroic-games-launcher/app.asar`, excluyendo los subprocesos Electron.
El indicador se oculta al estar abierto, como Steam y Faugus.

Heroic no publica un comando Quit en su protocolo de lanzamiento. El cierre envía
SIGTERM exclusivamente al proceso principal identificado y revalidado mediante
pidfd; nunca a un grupo de procesos ni con SIGKILL. Si hay procesos de un juego con
`HEROIC_APP_NAME`, se conserva Heroic y se registra el motivo. No se cierra durante
la transferencia al supervisor de una partida. Estas rutas se prueban con procesos,
señales y manifiestos simulados, sin cerrar las aplicaciones del usuario.

La barra lateral de Ajustes, debajo de Lista, muestra Abrir para aplicaciones
cerradas y Cerrar para aplicaciones abiertas. Al comprobar, abrir o cerrar muestra
el estado sin ofrecer otra acción hasta confirmarlo. Los botones funcionan con
mando y no cambian las preferencias automáticas. Las peticiones usan los mismos
mecanismos de inicio y salida en segundo plano y se bloquean durante una partida.
