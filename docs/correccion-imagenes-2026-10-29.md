# Correcciones verificadas — 29 de octubre de 2026

Se corrigieron dos problemas reproducibles:

- El escalado de imágenes podía redondear una dimensión a cero durante el primer layout. Se garantiza un mínimo de un píxel en cada eje, también al escalar logos. No se modifican los originales.
- Dos controles del editor consultaban las imágenes aunque estuviera cerrado. Ahora solo las consultan en su página visible. La regresión pasa de 40 consultas por 10 movimientos a cero, y confirma que las imágenes están disponibles al abrirlo.

## Verificación

La regresión de imágenes comprueba PNG, JPEG y WebP, dimensiones pequeñas o nulas, carátulas verticales, imágenes anchas y logos, con lecturas repetidas de caché: 78 solicitudes válidas.

Se repitió la misma prueba de estrés del [informe inicial](pruebas-estabilidad-2026-10-29.md), con cuatro modos y tres vueltas por catálogo:

| Juegos | Movimientos | Comprobaciones de ciclo de vida | Decodificaciones fallidas, antes → después | Avisos Qt, antes → después | Pico RSS después |
|---|---:|---:|---:|---:|---:|
| 100 | 1.200 | 60 | 4 → 0 | 2 → 0 | 260,0 MiB |
| 500 | 6.000 | 60 | 6 → 0 | 2 → 0 | 263,6 MiB |

Incluye 48 aperturas/cierres de ajustes, 24 ciclos del salvapantallas y 24 descargas/restauraciones al simular jugar. Ambas ejecuciones finalizaron sin avisos ni imágenes vacías. Las comprobaciones del panel de edición y de cargas invisibles también pasaron.

Datos: [100 juegos](benchmarks/2026-10-29/fixed/qt-stress-100.jsonl), [500 juegos](benchmarks/2026-10-29/fixed/qt-stress-500.jsonl), [reproducción de dimensiones pequeñas](benchmarks/2026-10-29/fixed/image-size-edge-probe.json).

## Pendiente

Persisten pausas puntuales del bucle de eventos. No se ha demostrado una causa única ni una mejora general de latencia; no se consideran resueltas. Tampoco hay un ahorro de RAM significativo demostrado por estos cambios.

Las pruebas se ejecutaron fuera de pantalla con renderizado por software, sin cambiar el foco del escritorio. No miden FPS, VRAM ni el comportamiento de Wayland/GPU en una sesión gráfica real. Tres vueltas tampoco descartan una fuga lenta.
