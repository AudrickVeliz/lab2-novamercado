# MLflow

Model Registry: `novamercado-ventas`, experimento `novamercado-ventas`. Interfaz: http://localhost:5000

## Versiones del modelo

| Versión | Alias | Promovida | Motivo | Creada | Run |
|---|---|---|---|---|---|
| 1 |  | true | Primer modelo. Costo en validación 90 556 vs 134 234 del baseline | 2026-11-15 20:42 | `6a97626d` |
| 2 |  | true | Costo en validación 89 901 vs 91 145 del vigente | 2026-11-15 20:44 | `d7866488` |
| 3 |  | false | No supera al vigente. Costo en validación 103 376 vs 102 635 del vigente | 2026-11-15 20:45 | `b5c1fed3` |
| 4 |  | true | Costo en validación 122 841 vs 123 426 del vigente | 2026-11-15 20:46 | `83db1aa9` |
| 5 |  | true | Costo en validación 134 459 vs 134 556 del vigente | 2026-11-15 20:48 | `4f5d2ebd` |
| 6 | vigente | true | Costo en validación 115 754 vs 131 890 del vigente | 2026-11-15 20:49 | `fd378d08` |

## Reentrenamientos (runs padre)

| Run | Validación | Observaciones de la BD | Costo baseline | Costo gradient boosting | Costo vigente | Promovido | Motivo |
|---|---|---|---|---|---|---|---|
| `c26c536d` | 2026-02-01 a 2026-02-28 | 0 | 134 234 | 90 556 | — | true | Primer modelo. Costo en validación 90 556 vs 134 234 del baseline |
| `6ad94bc2` | 2026-02-14 a 2026-03-13 | 1388 | 109 187 | 89 901 | 91 145 | true | Costo en validación 89 901 vs 91 145 del vigente |
| `eef9c534` | 2026-02-28 a 2026-03-27 | 3051 | 123 995 | 103 376 | 102 635 | false | No supera al vigente. Costo en validación 103 376 vs 102 635 del vigente |
| `c2613730` | 2026-03-14 a 2026-04-10 | 4715 | 145 444 | 122 841 | 123 426 | true | Costo en validación 122 841 vs 123 426 del vigente |
| `6f5a9dde` | 2026-03-28 a 2026-04-24 | 6385 | 160 218 | 134 459 | 134 556 | true | Costo en validación 134 459 vs 134 556 del vigente |
| `3ef7e207` | 2026-04-11 a 2026-05-08 | 8054 | 171 183 | 115 754 | 131 890 | true | Costo en validación 115 754 vs 131 890 del vigente |

## Linaje del último reentrenamiento

| Parámetro | Valor |
|---|---|
| `filas_objetivo` | 91106 |
| `fin_validacion` | 2026-05-08 |
| `huella_codigo` | 54a6eb51ca297291 |
| `huella_costos` | 0baee4424f183f03 |
| `huella_familias` | cd52ebf6613d4eab |
| `huella_feriados` | d655fc58b3c90391 |
| `huella_historico_ventas` | 573c3e358242717d |
| `huella_observaciones` | 510098d7104a3e14 |
| `huella_tiendas` | ea80d5dcd98cc9dc |
| `inicio_calibracion` | 2026-03-14 |
| `inicio_validacion` | 2026-04-11 |
| `observaciones_registradas` | 8054 |
| `promociones_registradas` | 8244 |
