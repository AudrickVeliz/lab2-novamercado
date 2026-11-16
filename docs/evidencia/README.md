# Evidencia de funcionamiento

Generada con el producto levantado desde cero (`docker compose up`) y los datos publicados. Ver D-012.

| Archivo | Qué muestra |
|---|---|
| [simulacion.md](simulacion.md) | 10 semanas de operación con un cambio de demanda: costo de las sugerencias, reentrenamientos por `/admin` y tiempo hasta que la API usa el modelo nuevo |
| [mlflow.md](mlflow.md) | Versiones del modelo con el alias `vigente`, reentrenamientos con sus costos y el linaje del último |
| [airflow.md](airflow.md) | Ejecuciones del DAG `reentrenamiento` |
| [respuestas.md](respuestas.md) | Respuestas de la API a los ejemplos publicados (válidos y E01–E10) y a problemas fuera del catálogo |

## Capturas

| Captura | Qué muestra |
|---|---|
| [mlflow-experimento.png](capturas/mlflow-experimento.png) | Experimento `novamercado-ventas`: un run por reentrenamiento, con su dataset de entrenamiento (linaje); el primero lo registró el arranque inicial y los demás, Airflow |
| [mlflow-modelo.png](capturas/mlflow-modelo.png) | Modelos de cada reentrenamiento, con sus métricas (costo, MAE, RMSE) y las versiones v1–v6 de `novamercado-ventas` |
| [airflow-dag.png](capturas/airflow-dag.png) | Las 5 ejecuciones del DAG `reentrenamiento`, todas exitosas, de 15 a 28 s |
| [api-docs.png](capturas/api-docs.png) | La documentación de la API (`/docs`): el contrato del Anexo (cuerpos, respuestas 200, 422 y 503 y esquemas) y una ejecución real de `POST /v1/prediccion` que responde con `version_modelo: "6"` |

Para regenerar los archivos con el producto levantado:

```
python scripts/simular_operacion.py
python scripts/exportar_evidencia.py
```
