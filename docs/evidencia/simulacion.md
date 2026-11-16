# Simulación de operación

Generada con `python scripts/simular_operacion.py` contra el producto levantado con `docker compose up`. Ver D-012.

## Configuración

- Desde 2026-03-01, 10 semanas; cambio de demanda ×1.2 desde 2026-03-22 (semana 4).
- Ventas reales: mismo día de la semana del año anterior × 1.1 (crecimiento interanual) × cambio × ruido de Poisson; la promoción es la de ese día del año anterior.
- Cada día: observaciones del día anterior y luego una solicitud de pronóstico por tienda. 15% de las solicitudes con un problema del catálogo; 5 % de las observaciones se reenvían (E09).
- Reentrenamiento por `POST /admin/reentrenar` cada 14 días.

## Resultado

- Pronósticos evaluados: 8244 (tienda × familia × día).
- **Costo total de las sugerencias: 304 200**  frente a 473 474 de sugerir la media de los 4 mismos días anteriores (35.8% menos).
- Respuestas HTTP: {200: 1364}. Calidad de las predicciones: {'advertencia': 30, 'corregido': 54, 'ok': 603}.

### Por semana

| Semana | Desde | Versión | Ventas reales | Venta esperada | WAPE | Costo | Costo ingenuo |
|---|---|---|---|---|---|---|---|
| 1 | 2026-03-01 | 1 | 181 929 | 174 524 | 0.174 | 23 180 | 36 230 |
| 2 | 2026-03-08 | 1 | 181 803 | 171 476 | 0.191 | 23 588 | 39 182 |
| 3 | 2026-03-15 | 2 | 187 129 | 191 775 | 0.185 | 23 784 | 36 890 |
| 4 | 2026-03-22 | 2 | 216 683 | 187 512 | 0.207 | 34 250 | 50 018 |
| 5 | 2026-03-29 | 2 | 232 579 | 203 641 | 0.215 | 35 974 | 59 468 |
| 6 | 2026-04-05 | 2 | 226 298 | 204 878 | 0.191 | 30 594 | 49 513 |
| 7 | 2026-04-12 | 4 | 234 812 | 217 408 | 0.253 | 42 654 | 67 451 |
| 8 | 2026-04-19 | 4 | 220 570 | 208 553 | 0.196 | 28 156 | 47 197 |
| 9 | 2026-04-26 | 5 | 231 536 | 213 670 | 0.208 | 34 192 | 46 340 |
| 10 | 2026-05-03 | 5 | 220 824 | 207 976 | 0.181 | 27 829 | 41 184 |

### Reentrenamientos

| Día | Estado | Promovido | Versión anterior → vigente | Motivo | Duración | Hasta usarlo |
|---|---|---|---|---|---|---|
| 2026-03-14 | exitoso | True | 1 → 2 | Costo en validación 89 901 vs 91 145 del vigente | 28 s | 22 s |
| 2026-03-28 | exitoso | False | 2 → 2 | No supera al vigente. Costo en validación 103 376 vs 102 635 del vigente | 18 s | — |
| 2026-04-11 | exitoso | True | 2 → 4 | Costo en validación 122 841 vs 123 426 del vigente | 21 s | 26 s |
| 2026-04-25 | exitoso | True | 4 → 5 | Costo en validación 134 459 vs 134 556 del vigente | 18 s | 28 s |
| 2026-05-09 | exitoso | True | 5 → 6 | Costo en validación 115 754 vs 131 890 del vigente | 18 s | 28 s |
