# Decisiones técnicas y de producto

Cada decisión registra su contexto, las alternativas consideradas y su justificación.

## D-001: datos publicados en `data/publicados/`, versionados con DVC y un remoto en DagsHub

**Fecha:** 2026-11-15

**Contexto:** el enunciado prohíbe que los datos y las credenciales formen parte del repositorio o de las imágenes, y pide que el README indique la carpeta donde se colocan los archivos publicados. El equipo docente clonará el tag de entrega, colocará ahí los archivos y levantará el producto sin las credenciales del estudiante. En el Laboratorio 1, un remoto de DVC en una carpeta local no se consideró un remoto válido.

**Decisión:**

- Todos los archivos publicados (`historico_ventas.csv`, `tiendas.csv`, `familias.csv`, `feriados.csv`, `costos.csv`, `catalogo_errores.md` y `ejemplos/`) viven en `data/publicados/`, con los nombres originales.
- Git ignora `data/`. Solo se versiona el puntero `data/publicados.dvc`.
- El remoto predeterminado de DVC es un repositorio **privado** de DagsHub. La URL está en `.dvc/config`. El usuario y el token están en `.dvc/config.local`, que Git ignora.

**Alternativas:**

| Alternativa | A favor | En contra |
|---|---|---|
| DagsHub privado (elegida) | Remoto externo, gratuito y hecho para DVC; no redistribuye los datos del curso | Requiere cuenta y token para `dvc push` y `dvc pull` |
| DagsHub público | Cualquiera puede hacer `dvc pull` sin credenciales | Redistribuye públicamente los datos del curso |
| Google Drive | Sin costo | Google bloqueó la app OAuth que trae DVC: hay que crear un proyecto de Google Cloud y una cuenta de servicio |
| S3, Azure o GCS | Es el estándar en la industria | Requiere una cuenta con tarjeta o créditos; es excesivo para el alcance |
| Carpeta local dentro del proyecto | Sin cuenta ni credenciales | No es un remoto: no hay copia fuera de la máquina (penalizado en el Laboratorio 1) |

**Justificación:** el remoto externo da una copia versionada fuera de la máquina. El producto no lo necesita para operar, porque el equipo docente coloca sus propios archivos, así que el token nunca forma parte del repositorio ni de la evaluación.

**Riesgo aceptado:** el equipo docente no puede descargar los datos desde el remoto sin una invitación al repositorio de DagsHub. No lo necesita para evaluar.

## D-002: qué se versiona dónde

**Fecha:** 2026-11-15

**Contexto:** a diferencia del Laboratorio 1, el enunciado no menciona DVC. Pide el registro de experimentos, modelos y su linaje en MLflow, con el modelo vigente identificado por un alias, y el registro de la operación en un PostgreSQL propio. El reentrenamiento corre dentro de Airflow durante la evaluación, sin credenciales del estudiante.

**Decisión:** cada cosa se versiona en un solo lugar.

| Qué | Dónde | Cómo |
|---|---|---|
| Datos de entrada (`data/publicados/`) | DVC + DagsHub | `dvc add` y `dvc push` en desarrollo |
| Modelos y experimentos | MLflow (Model Registry) | Una versión por modelo registrado; el vigente se identifica con un alias |
| Linaje de cada modelo | MLflow (run) | Hash de cada archivo publicado, rango de fechas, conteo y hash de las observaciones de la BD usadas, commit del código y parámetros (`mlflow.log_input`), más el dataset de entrenamiento en parquet como artefacto |
| Operación | PostgreSQL del producto | Solicitudes, correcciones, predicciones con la versión del modelo y observaciones |

El producto (API y DAGs) nunca ejecuta DVC.

**Alternativas:**

| Alternativa | En contra |
|---|---|
| Versionar también los modelos con DVC | Habría dos fuentes de verdad para el modelo vigente; el enunciado pide MLflow |
| `dvc push` desde el DAG de reentrenamiento | Necesitaría el token de DagsHub dentro del producto, y fallaría en la evaluación |
| Quitar DVC | Pierde el registro externo de la versión de los datos de entrada |
| Solo metadatos de linaje, sin snapshot | Para reproducir un modelo habría que reconstruir el dataset desde la BD, que sigue cambiando |

**Justificación:** el snapshot del dataset (~1–2 MB por run) permite reproducir exactamente cada modelo a partir de su run, sin depender del estado actual de la base de datos. Así cada modelo puede reproducirse a partir de su versión de código y de datos.
