# Prueba aislada de Qt Quick

Prototipo de biblioteca con PySide6/QML. Reutiliza `Library`, el generador de
100 juegos y el lector SDL del mando. Copia el estado y las imágenes a un perfil
temporal: no modifica la biblioteca real ni ejecuta sus juegos. No importa GTK.
El entorno Qt es opcional y no forma parte de las dependencias de Estante.

## Ejecutar

Desde la raíz del repositorio:

```sh
python3 -m venv /tmp/estante-qt-venv
/tmp/estante-qt-venv/bin/pip install -r tools/qt_probe/requirements.txt
/tmp/estante-qt-venv/bin/python tools/qt_probe/main.py --games 100
```

Flechas o D-pad/joystick para recorrer, clic para seleccionar; Escape para cerrar.
El mando usa la repetición actual de Estante (130 ms). Los botones para lanzar y
editar juegos quedan fuera de esta prueba. El número de juegos puede cambiarse.

```sh
/tmp/estante-qt-venv/bin/python tools/qt_probe/main.py --games 100 --auto --cycles 2 \
  --output /tmp/estante-qt.jsonl --screenshot /tmp/estante-qt.png
```

La prueba automática hace dos vueltas a 130 ms por selección y espera diez
segundos antes de cerrar. Guarda RSS, PSS, memoria anónima, API gráfica, tamaño
real de ventana, selecciones visitadas y tiempos entre presentaciones. Se ejecuta
en el escritorio gráfico, a pantalla completa por defecto. `--windowed`,
`--width` y `--height` permiten cambiarlo. El perfil temporal se elimina al salir.

Lee dim, blur, tamaño de carátula y fondo de la configuración del modo lista.
`--dim 0.5` y `--blur 0.25` permiten experimentar (rango 0–1). Admite fondo único
o división horizontal; no reproduce las divisiones vertical o diagonal. Los
logos se crean con ListView, reutilización de delegados y cacheBuffer cero.
Las imágenes se cargan asíncronamente, a resolución limitada, sin caché de QML.
Se preserva la configuración del asignador nativo usada por Estante.

## Límites de la comparación

Este es un experimento de renderizado, no una migración ni una copia completa
de la apariencia. Faltan tarjeta informativa, categorías, búsqueda, ajustes,
transiciones entre vistas, lanzamiento y supervisión de partidas. No puede
interpretarse su diferencia de RAM como el ahorro de una migración completa.
La prueba GTK existente también abre ajustes y cambia de apariencia, por lo
que interesa especialmente comparar su muestra `after_dpad` con las vueltas Qt.
Las muestras finales de ambos programas siguen cargas de trabajo distintas.

El porcentaje de CPU es acumulado desde el arranque, expresado sobre un núcleo.
Los intervalos entre `frameSwapped` incluyen huecos sin repintados; no son tiempo
de renderizado ni una medición fiable de FPS en reposo. No hay aún una captura
comparable de CPU/fluidez en GTK ni una medición fiable de VRAM. Comparar en
secuencia, al mismo tamaño real, con las mismas imágenes y efectos; evitar
sacar conclusiones de tiempos con ambas aplicaciones ejecutándose a la vez.

La documentación Qt recomienda `Image.sourceSize` y carga asíncrona:
https://doc.qt.io/qt-6.5/qtquick-performance.html

## Resultado preliminar del 24 de octubre de 2026

Datos de la ejecución en `results-2026-10-24.json`. Qt Quick/OpenGL, 100 juegos,
2560×1440, fondo único, dim 50 %, blur 0, carátula cuadrada de 315 px.

| Muestra | RSS MiB | PSS MiB |
|---|---:|---:|
| Qt al arrancar | 244,2 | 169,5 |
| Qt tras primera vuelta | 226,5 | 151,7 |
| Qt tras segunda vuelta | 228,5 | 153,1 |
| Qt tras 10 s de reposo | 254,6 | 179,8 |
| GTK tras primera vuelta | 293,6 | 197,6 |
| GTK al terminar dos ciclos completos | 307,2 | 211,0 |

La diferencia final observada es 52,6 MiB RSS y 31,2 MiB PSS, pero **no es una
comparación funcional equivalente** por las limitaciones anteriores. Además,
GTK no registra su tamaño real de ventana en el banco actual. No justifica aún
una migración ni demuestra un porcentaje de ahorro atribuible a Qt.

Se comprobó visualmente la ventana renderizada y se recorrieron los 100 índices
con repetición automática. El lector del mando está conectado, pero no se ha
verificado aquí una pulsación física real. Validación del modelo: wrap en ambos
sentidos, conteo de visitados y URLs de imágenes ausentes/locales. La suite
existente de Estante mantiene sus 362 pruebas aprobadas. qmllint no encuentra
errores fatales; informa accesos de contexto no cualificados en este prototipo.

Comprobación adicional con blur 0,25 y cinco juegos: final 310,1 MiB RSS /
230,9 MiB PSS. El efecto funciona y el proceso cierra correctamente; esta
prueba corta no es comparable al recorrido de 100 juegos, pero muestra que
Qt tampoco elimina el coste de las superficies de blur.
