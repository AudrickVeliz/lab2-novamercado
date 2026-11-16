# Verificación de los requerimientos

Cada requerimiento del enunciado, dónde está implementado y cómo se verificó. Las decisiones están en [DECISIONES.md](../DECISIONES.md) y la evidencia, en [evidencia/](evidencia/).

## Descripción del producto

| Requerimiento | Implementación | Verificación |
|---|---|---|
| Pronóstico diario por familia con venta esperada y cantidad sugerida | `POST /v1/prediccion` (`api.py`, `prediccion.py`) | `test_api.py`, [respuestas.md](evidencia/respuestas.md) |
| Defensa del contrato: reparar, advertir o rechazar, e informar qué se hizo | `limpieza.py`, `calidad` en cada respuesta (D-003) | `test_limpieza.py`, `test_robustez.py` |
| Registro de cada predicción y observación, con la versión del modelo | `persistencia.py` (D-004) | `test_persistencia.py` |
| Reentrenamiento con criterio explícito; el servicio usa el modelo nuevo sin reinicio | `registro_modelos.py`, `prediccion.ModeloVigente` (D-008, D-009) | `test_registro_modelos.py`, `test_prediccion.py`, [simulacion.md](evidencia/simulacion.md) |
| Cantidad sugerida evaluada con `costos.csv` | `negocio.py` (D-007) | `test_negocio.py`, costo en [simulacion.md](evidencia/simulacion.md) |
| No usa el reloj del sistema para validar fechas | `limpieza.py` solo compara con los catálogos | `test_no_usa_el_reloj_del_sistema` |
| Al pronosticar solo usa observaciones de días anteriores | `caracteristicas.py`, `PredictorVentas` (D-006) | `test_no_usa_la_venta_del_mismo_dia_ni_futuras`, `test_solo_pide_observaciones_anteriores_a_la_fecha` |

## 1. Servicio con FastAPI

| Requerimiento | Implementación | Verificación |
|---|---|---|
| API que cumple exactamente el contrato del Anexo, puerto 8000 | `api.py`, `contrato.py` | `test_api.py`, `test_contrato.py`, CI en Docker |
| Validación con Pydantic; la limpieza en módulos con pruebas, no en los endpoints | `contrato.py` (estricto) + `limpieza.py` | `test_limpieza.py` |
| Política explícita por tipo de problema, aplicada de forma consistente | D-003 | `test_ejemplos_publicados` (E01–E10) |
| Reglas generales para problemas fuera del catálogo | Normalización común de campos, números, fechas y familias | `test_robustez.py` (miles de solicitudes al azar: solo 200 o 422) |
| Cada respuesta indica la versión del modelo | `version_modelo` (texto) | `test_prediccion_valida_cumple_el_contrato` |
| Pruebas del contrato sin depender de MLflow | Predictor y registro falsos | `test_api.py` corre sin servidores |

## 2. Persistencia

| Requerimiento | Implementación | Verificación |
|---|---|---|
| PostgreSQL propio, en Docker y separado del de Airflow | `bd-producto` (aparte de `bd-mlflow` y `bd-airflow`) | `compose.yaml` |
| Registro de solicitudes, predicciones, correcciones y observaciones | Tablas `solicitudes`, `predicciones`, `correcciones`, `observaciones` | `test_persistencia.py` |
| Observaciones idempotentes | Upsert por tienda, fecha y familia; historial de correcciones | `test_e09_*`, incluidos los envíos simultáneos |
| Se conserva al detener y volver a levantar | Volúmenes con nombre (D-010) | CI en Docker: paso «Detener y volver a levantar» |

## 3. Modelado y MLflow

| Requerimiento | Implementación | Verificación |
|---|---|---|
| Baseline simple y un modelo de ML que lo mejore | Media de los 4 mismos días y HistGradientBoosting (D-006) | Costo 90 556 frente a 134 234 en validación |
| Métrica de negocio con `costos.csv` y métricas técnicas | `negocio.metricas`: costo, MAE, RMSE, WAPE y sesgo | `test_metricas`, runs en [mlflow.md](evidencia/mlflow.md) |
| Cantidad sugerida coherente con los costos | Cuantil `cf/(cf+cs)` ponderado (D-007) | `test_el_factor_calibrado_minimiza_el_costo` |
| Experimentos, modelos y linaje en MLflow | Run padre con huellas de datos y código, y artefactos parquet (D-009) | `test_el_run_guarda_el_linaje`, [mlflow.md](evidencia/mlflow.md) |
| Modelo vigente identificado con un alias | `novamercado-ventas@vigente` | `GET /modelo` |
| Criterio explícito y automatizado de reemplazo | Costo menor que el del baseline y que el del vigente, en la misma ventana (D-008) | `test_reemplaza_*`, `test_no_reemplaza_*` |

## 4. Reentrenamiento con Airflow

| Requerimiento | Implementación | Verificación |
|---|---|---|
| DAG que usa el histórico y las observaciones de la base | `dags/reentrenamiento.py` → `reentrenamiento.ejecutar_y_registrar` (D-011) | `test_reentrenamiento.py` |
| Se dispara por `POST /admin/reentrenar` y su estado se consulta | API REST de Airflow y tabla `reentrenamientos` | `test_api.py`, CI en Docker, [airflow.md](evidencia/airflow.md) |
| Modelo promovido en uso sin reinicio en ≤ 2 minutos | Consulta del alias cada 30 s | [simulacion.md](evidencia/simulacion.md) («Hasta usarlo») |
| Un reentrenamiento que falla o no supera el criterio no afecta al vigente | El alias se mueve al final y solo si se cumple el criterio | `test_ciclo_de_reentrenamiento`, `test_un_fallo_queda_registrado_y_no_toca_al_vigente` |

## 5. Contenedores y operación

| Requerimiento | Implementación | Verificación |
|---|---|---|
| Todo se levanta con `docker compose up` siguiendo el README; el servicio se llama `mlflow` | `compose.yaml` | CI «Compose en Docker» |
| Desde cero entrena y registra el primer modelo; al volver a levantarse no repite | Servicio `entrenamiento-inicial` | CI: «Ya hay un modelo vigente» |
| Imágenes con versiones fijas | `python:3.12.15-slim-bookworm`, `postgres:16.10`, `mlflow:v3.17.2`, `airflow:3.3.2` | `Containerfile*`, `compose.yaml` |
| Datos y credenciales fuera de las imágenes y del repositorio; `.env.example` | `.dockerignore`, `.gitignore`, `${VAR:?}` sin valores por defecto (D-010) | Sin `.env`, compose se detiene |
| La API responde aunque MLflow no esté; `/health` lo refleja en < 1 min y vuelve en < 2 min | Copia local del modelo y chequeo directo de MLflow (D-009) | Local: 0.1 s y 5.2 s; CI: paso «Interrupción temporal de MLflow» |
| Listo en ≤ 10 minutos; cada reentrenamiento en ≤ 10 minutos | — | Desde cero: 62–87 s; reentrenamiento: 15–28 s ([airflow.md](evidencia/airflow.md)) |

## 6. Documentación y decisiones

| Requerimiento | Dónde |
|---|---|
| Repositorio con estructura clara de código, configuración, DAGs, Docker y pruebas | `src/`, `dags/`, `tests/`, `scripts/`, `Containerfile*`, `compose.yaml` |
| Archivo de contexto para el agente | [CLAUDE.md](../CLAUDE.md) |
| README para levantar desde cero, con la carpeta de los archivos publicados | [README.md](../README.md) (`data/publicados/`) |
| DECISIONES con la política ante los datos, la información del modelo, la cantidad sugerida y el criterio de reemplazo | D-003, D-006, D-007, D-008 |

## Entregables

| Entregable | Dónde |
|---|---|
| Código de la API, el modelo, los DAGs, Docker y las pruebas | Este repositorio |
| Tag `entrega-lab2` | Tag de Git |
| README y DECISIONES | Raíz del repositorio |
| Evidencia: experimentos y versiones en MLflow, ejecuciones del DAG y respuestas válidas y defectuosas | [evidencia/](evidencia/) |
