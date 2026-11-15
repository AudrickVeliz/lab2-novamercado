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

## D-003: política ante cada tipo de problema en los datos

**Fecha:** 2026-11-15

**Contexto:** los sistemas de las tiendas no son uniformes. El servicio no debe detenerse por datos defectuosos, pero tampoco inventar datos, y debe informar en cada respuesta qué hizo y por qué. Llegarán problemas que no están en el catálogo, así que las reglas deben ser generales.

**Regla general:**

| Política | Cuándo | Efecto |
|---|---|---|
| **Reparar** | Hay una sola interpretación posible | Se corrige; `calidad.estado = corregido` |
| **Advertir** | Se puede responder asumiendo algo | Se responde y se dice qué se asumió; `calidad.estado = advertencia` |
| **Rechazar** | No se puede responder sin inventar (no se sabe qué tienda, qué fecha, o hay datos en conflicto) | 422 con `detail` |

La limpieza vive en `novamercado.limpieza` y no usa el reloj del sistema. Los modelos de Pydantic de `novamercado.contrato` validan después la solicitud ya limpia, de forma estricta. Los nombres de campos y de familias se comparan en una forma normalizada (sin tildes, sin mayúsculas, solo letras y dígitos), y los números y las fechas se interpretan con las mismas reglas en todo el contrato.

**Solicitudes de predicción:**

| Código | Problema | Política | Detalle |
|---|---|---|---|
| E01 | Tienda como texto o con prefijo | Reparar | Se extrae un único número (`"T05"`, `"tienda 5"`, `5.0` → 5). Si hay varios números (`"5-7"`) o decimales reales, o si la tienda no existe: **rechazar** |
| E02 | Familia escrita de otra forma | Reparar | Se compara normalizada contra `familia_id` y contra el nombre de `familias.csv` (`"Frutas y Verduras"` → `frutas_verduras`). No hay coincidencia aproximada: `"lacteo"` no es inequívoco |
| E02 | Familia no reconocida | Advertir | Se omite; el resto se pronostica. Si era una familia real mal escrita, E05 la completa |
| E03 | Promoción como texto o decimal entero | Reparar | `"3"`, `2.0`, `"3,0"` → 3 |
| E03 | Promoción negativa, con decimales reales, ilegible o ausente | Advertir | Se asume 0: la promoción del día solo llega en la solicitud y no hay otro dato |
| E04 | Fecha ISO con hora, año primero con `/`, o día/mes inequívoco | Reparar | `"2025-11-17T00:00:00"`, `"17/11/2025"`, `"11/17/2025"` (17 no puede ser mes) |
| E04 | Fecha ambigua (día y mes ≤ 12 y distintos) | Advertir | Se asume día primero, la convención en Guatemala |
| E04 | Fecha irreconocible o inexistente | Rechazar | `"2025-02-30"`, `"mañana"`, año de dos dígitos |
| — | Fecha anterior a la apertura de la tienda | Rechazar | La tienda no operaba |
| — | Fecha posterior al último día de `feriados.csv` | Advertir | Se pronostica sin conocer los feriados |
| E05 | Faltan familias | Advertir | Se completan las 12 con `en_promocion = 0`: la tienda necesita inventario de todas, y el supuesto queda declarado |
| E06 | Familia repetida con los mismos valores | Reparar | Se usa una vez |
| E06 | Familia repetida con promociones distintas | Advertir | Se usa la mayor: subestimar una promoción provoca faltantes, que cuestan más que los sobrantes en 8 de las 12 familias |
| E07 | Nombre de campo distinto | Reparar | Se reconoce por una lista de alias por campo (`tienda`, `id_tienda`, `store_id`, `promocion`…). Dos campos con el mismo destino y valores distintos: **rechazar**. Falta un campo obligatorio (`tienda_id`, `fecha`, `familias`): **rechazar** |
| — | Campos desconocidos | Ignorar | No afectan al pronóstico ni a `calidad`; quedan en la solicitud cruda guardada en la BD |
| — | Elemento de la lista que no es un objeto | Advertir | Se omite |
| — | Cuerpo que no es un objeto JSON, o `familias` que no es una lista | Rechazar | |

**Observaciones de ventas:**

| Código | Problema | Política | Detalle |
|---|---|---|---|
| E08 | Ventas negativas | Advertir | Ese registro **no se guarda**; los demás sí. No se sabe la venta real, y guardar 0 entrenaría el modelo con un dato inventado |
| E09 | Reenvío idéntico | — | Se responde 200 con `registros_guardados = 0` (lo resuelve la persistencia) |
| E09 | Reenvío con un valor distinto | Reparar en la BD | Se toma como corrección: cambia el valor vigente, cuenta como modificado y el anterior queda en el historial |
| E10 | Separador de miles o coma decimal | Reparar | Un separador seguido de exactamente 3 dígitos es de miles (`"1,234"` → 1234); con 1–2 dígitos es decimal (`"812,0"` → 812). Si aparecen punto y coma, el último es el decimal |
| E10 | Decimal real o número ilegible | Advertir | No se guarda (`"12,5"`): las ventas son unidades enteras |
| — | Familia repetida en la misma observación | Reparar si los valores son iguales; si no, **advertir** y no guardar esa familia | No se sabe cuál es el correcto |
| — | Faltan familias | Advertir | Se guardan las recibidas; las faltantes pueden llegar en otro envío |
| — | Valor atípico (más de 5 veces el máximo histórico de la tienda y la familia) | Advertir | Se guarda: puede ser un cambio real de demanda |
| — | Tienda, fecha, campos y familias | Igual que en la predicción | |

**Alternativas descartadas:**

| Alternativa | En contra |
|---|---|
| Rechazar ante cualquier problema | La tienda se queda sin pronóstico por un detalle; el enunciado pide que el servicio no se detenga |
| Coincidencia aproximada de familias | Puede adivinar mal en silencio (`"lacteo"` podría ser otra cosa) |
| Pronosticar solo las familias recibidas (E05) | Las familias faltantes quedan sin cantidad sugerida |
| Usar la última repetición (E06) | Supone un orden de envío que el contrato no garantiza |
| Recortar las ventas negativas a 0 (E08) | Inventa un dato que entra al reentrenamiento |
| Advertir por los campos desconocidos | Muchas respuestas pasarían a advertencia sin que se haya asumido nada |

**Riesgo aceptado:** asumir día primero en una fecha ambigua puede pronosticar el día equivocado; queda advertido en la respuesta. El factor de atípicos (5) es un umbral de criterio que se revisará con los datos de la evaluación.

## D-004: registro de la operación e idempotencia de las observaciones

**Fecha:** 2026-11-15

**Contexto:** el enunciado pide un PostgreSQL propio del producto, separado del de Airflow, que registre las solicitudes, las predicciones, las correcciones aplicadas y las observaciones de ventas reales. Recibir dos veces la misma observación no debe duplicar información, y `registros_guardados` cuenta solo los registros nuevos o modificados.

**Decisión:**

- Acceso con **SQLAlchemy 2 Core y psycopg 3**, en las versiones de las restricciones de Airflow 3.3.2, para que la API y el DAG compartan el módulo `novamercado.persistencia`.
- El esquema se crea al arrancar con `create_all`, que solo crea las tablas que faltan y no toca las existentes ni sus datos.
- Cinco tablas:

| Tabla | Una fila por | Para qué |
|---|---|---|
| `solicitudes` | Solicitud recibida, **incluidos los rechazos** | Cuerpo crudo (JSONB), estado (`ok`, `corregido`, `advertencia` o `rechazada`), motivo del rechazo y campos ignorados |
| `correcciones` | Observación de calidad | Qué se reparó o advirtió y por qué |
| `predicciones` | Familia pronosticada | Promoción usada, venta esperada, cantidad sugerida, nombre y versión del modelo |
| `observaciones` | Tienda, fecha y familia (clave primaria) | Valor vigente de las ventas reales |
| `observaciones_historial` | Corrección de un valor ya guardado | Valor anterior y nuevo, y la solicitud que lo cambió |

- **Idempotencia**, dentro de una transacción y por registro:
  - Si no existe, se inserta (`ON CONFLICT DO NOTHING`) y cuenta 1.
  - Si existe con el mismo valor, no se hace nada y cuenta 0.
  - Si existe con otro valor, se actualiza, se guarda el cambio en el historial y cuenta 1.
- Una tienda puede pedir varias veces el pronóstico de una misma fecha: cada solicitud y sus predicciones se guardan por separado.
- `recibida_en` usa el reloj del servidor solo para auditoría; ninguna regla del servicio depende de él.

**Alternativas:**

| Alternativa | En contra |
|---|---|
| SQLAlchemy ORM | Más abstracción de la que pide un registro de operación |
| SQL a mano con psycopg | Hay que mantener a mano el esquema y la conexión |
| Migraciones con Alembic | Una herramienta y un paso de arranque más para un esquema que se define una vez |
| Guardar solo las solicitudes aceptadas | Se pierde la evidencia de qué se rechazó y por qué |
| Correcciones como JSONB dentro de `solicitudes` | Cuesta más consultarlas, y el enunciado las nombra como algo a registrar |
| Sobrescribir sin historial | Se pierde qué se sabía antes de cada corrección |
| Probar con SQLite | `ON CONFLICT` y JSONB se comportan distinto que en PostgreSQL |

**Justificación:** insertar primero con `ON CONFLICT DO NOTHING` y bloquear la fila existente (`SELECT … FOR UPDATE`) antes de compararla evita que dos envíos simultáneos del mismo registro se dupliquen o se cuenten dos veces. Hay una prueba con cuatro envíos simultáneos. La inserción se detecta con `RETURNING`, porque psycopg reporta `rowcount = -1` en un `INSERT … ON CONFLICT DO NOTHING`.

**Pruebas:** corren contra un PostgreSQL 16.10 real, como servicio en el CI y en un contenedor temporal en local. Sin `NOVAMERCADO_BD_PRUEBAS_URL` se saltan.

## D-005: comportamiento de la API ante la falta de modelo, de base de datos o de datos

**Fecha:** 2026-11-15

**Contexto:** el Anexo fija los endpoints, sus campos y que un rechazo se responde con 422 y `detail`. El enunciado pide además que cada predicción y cada observación queden registradas, que `GET /health` responda 503 mientras no haya un modelo cargado, que el servicio use un modelo nuevo sin reiniciarse, y que las pruebas del contrato no dependan de MLflow.

**Decisión:**

| Situación | Respuesta | Se registra como |
|---|---|---|
| Solicitud aceptada | 200 según el Anexo | `ok`, `corregido` o `advertencia` |
| Datos que no se pueden atender (D-003), cuerpo vacío o JSON inválido (incluidos `NaN` e `Infinity`) | 422 con `detail` en texto | `rechazada` |
| Sin modelo cargado (`/v1/prediccion`, `/modelo`) | 503 con `detail` | `no_atendida` |
| El modelo falla al predecir | 503 con `detail` | `no_atendida` |
| La base del producto no permite registrar | 503 con `detail`: no se responde sin registrar | — |
| `/health` sin modelo | 503, `estado = degradado` y `motivo` | — |
| `/health` con alguna dependencia caída | 200, `estado = degradado` y `motivo` | — |
| Faltan los archivos publicados, un catálogo es inválido o falta `NOVAMERCADO_BD_URL` al arrancar | La API no arranca y el log dice qué revisar | — |

- La API recibe sus dependencias al crearse (`crear_app`): los catálogos, el registro, una función que devuelve el **modelo vigente** y los chequeos de salud. El modelo se consulta en cada solicitud, así que puede cambiar sin reiniciar la API. La versión informada es la del modelo que hizo la predicción.
- Los endpoints leen el cuerpo crudo y delegan en `novamercado.limpieza`, así el mismo 422 con `detail` en texto cubre tanto el JSON inválido como los datos defectuosos, y la solicitud cruda siempre queda guardada.
- El carácter NUL se reemplaza antes de guardar el cuerpo, porque JSONB no lo admite.
- Las observaciones no necesitan modelo: se atienden aunque no haya ninguno cargado.
- Las dependencias se instalan con las restricciones de Airflow 3.3.2 (`--constraint`), que fijan también las transitivas.

**Alternativas:**

| Alternativa | En contra |
|---|---|
| Responder con un baseline fijo mientras no hay modelo | `version_modelo` no correspondería a un modelo del Registry |
| Predecir aunque no se pueda registrar | Incumple que cada predicción quede guardada |
| Arrancar en 503 si faltan los datos | El servicio parece vivo pero no puede validar ninguna solicitud |
| Dejar que FastAPI valide el cuerpo | Su 422 trae una lista de errores en `detail` y la solicitud no quedaría registrada |

**Pruebas:** las del contrato usan un predictor falso y un registro en memoria, así que no dependen de MLflow ni de la base. Una prueba de integración repite el recorrido con el PostgreSQL real.

## D-006: información que usa el modelo al predecir

**Fecha:** 2026-11-15

**Contexto:** al pronosticar una fecha, el servicio solo dispone de las observaciones de días anteriores; la promoción del día viene en la solicitud. El análisis del histórico muestra un patrón semanal fuerte (sábado 1.23×, lunes 0.88×), un crecimiento del 10 % interanual, un diciembre 1.21× noviembre y un efecto de la promoción de entre 1.14× (panadería) y 1.39× (limpieza). También muestra efectos por tipo de fecha: feriado 0.89×, comercial 1.14×, pago 1.19× y medio día 1.96×. El periodo de evaluación puede incluir cambios en la demanda.

**Decisión:** `novamercado.caracteristicas` calcula, para cada tienda, familia y fecha:

| Grupo | Variables | Fuente |
|---|---|---|
| Identidad | `tienda_id`, `familia_id`, `tipo_tienda` (categóricas con las categorías del catálogo) | Catálogos |
| Promoción | `en_promocion` del día | Solicitud |
| Calendario | `dia_semana`, `dia_mes`, `mes`, `dias_desde_apertura` | Fecha y `tiendas.csv` |
| Tipos de fecha | `feriado`, `comercial`, `pago`, `medio_dia`, `vispera_feriado`, nacionales o de la ciudad de la tienda | `feriados.csv` |
| Historia reciente | `venta_ayer`, `ultima_venta`, `dias_sin_dato`, `media_7`, `media_28`, `venta_hace_7`, `media_mismo_dia_4`, `venta_hace_364` | Ventas de **días anteriores** |

- Ninguna variable usa la venta del día que se pronostica ni ventas posteriores; una prueba lo verifica alterando las ventas futuras.
- Si falta la observación de ayer, `ultima_venta` y `dias_sin_dato` dicen cuál fue la última conocida y hace cuánto. Las demás quedan vacías, y el modelo admite valores faltantes.
- Modelo de ML: un único `HistGradientBoostingRegressor` (scikit-learn 1.9.1) para todas las tiendas y familias, con pérdida de Poisson y sin `early_stopping`, porque su validación interna es aleatoria y mezclaría fechas futuras. Los hiperparámetros (`learning_rate=0.05`, `max_iter=500`, `max_leaf_nodes=15`, `min_samples_leaf=40`, `l2_regularization=1.0`) se eligieron comparando cinco configuraciones en un corte **anterior** a la ventana de validación, para no ajustarse a ella.
- Baseline: la media de los últimos cuatro días con el mismo día de la semana; si no hay cuatro semanas de historia, la media de 28 días o la última venta.
- Una variable sin ningún dato al entrenar (`venta_hace_364` con menos de un año de historia) se trata como constante, igual al entrenar que al predecir.

**Alternativas:**

| Alternativa | En contra |
|---|---|
| Sin historia reciente | No se adapta si cambia la demanda |
| LightGBM | Dependencia nueva, fuera de las restricciones de Airflow |
| Regresión lineal | Capta mal las interacciones (promoción × familia, feriado × tipo de tienda) |
| Un modelo por tienda y familia | 120 modelos con pocos datos cada uno y una tienda nueva sin modelo |
| Naive semanal como baseline | Peor en dic–feb (WAPE 0.303 frente a 0.278) |

**Resultado con los datos publicados** (validación del 2026-02-01 al 2026-02-28):

| Modelo | Costo | WAPE | MAE | RMSE |
|---|---|---|---|---|
| Baseline | 134 234 | 0.215 | 45.9 | 85.4 |
| HistGradientBoosting | 90 556 | 0.177 | 37.9 | 69.2 |

## D-007: cantidad sugerida a partir de los costos

**Fecha:** 2026-11-15

**Contexto:** la cantidad sugerida se evalúa con `costo = c_faltante × máx(real − sugerido, 0) + c_sobrante × máx(sugerido − real, 0)`, y los costos difieren entre familias.

**Decisión:** `cantidad_sugerida = redondeo(venta_esperada × factor_familia)`, entera y no negativa. El factor de cada familia es el cuantil `c_faltante / (c_faltante + c_sobrante)` de `real / esperada`, **ponderado por la venta esperada**, calculado en la ventana de calibración (D-008).

**Justificación:** si la sugerida es `f × esperada`, el costo total es `Σ esperada × [c_f × máx(r − f, 0) + c_s × máx(f − r, 0)]` con `r = real / esperada`, y su mínimo en `f` es exactamente ese cuantil ponderado (el resultado del newsvendor). La ponderación hace que los pronósticos cercanos a cero no distorsionen el factor. Los factores resultantes siguen los costos: licores ×1.46 (sobrar cuesta 0.1), abarrotes ×1.27, panadería ×0.85 (sobrar cuesta 2.5). En la validación, los factores bajan el costo de 121 123, sugiriendo exactamente la venta esperada, a 90 556.

**Alternativas:**

| Alternativa | En contra |
|---|---|
| Regresión por cuantiles | Doce modelos más que entrenar, registrar y cargar |
| Factor de seguridad fijo | Ignora que los costos difieren entre familias |
| Sugerir la venta esperada | 34 % más de costo en la validación |

## D-008: validación y criterio de reemplazo del modelo

**Fecha:** 2026-11-15

**Contexto:** el enunciado pide un criterio explícito y automatizado para decidir cuándo un modelo nuevo reemplaza al vigente, y que un reentrenamiento que no lo supere no afecte al vigente.

**Decisión:**

- Tres tramos consecutivos, hasta la última fecha con ventas `T`: **entrenamiento** hasta `T−56`, **calibración** de los factores de `T−55` a `T−28` y **validación** de `T−27` a `T` (28 días cada uno). Todo fuera de muestra.
- En cada entrenamiento se entrenan el baseline y el gradient boosting con los mismos tramos.
- **Primer modelo** (no hay vigente): se promueve el de menor costo en validación.
- **Reemplazo:** el gradient boosting se promueve solo si su costo en validación es menor que el del baseline **y** que el del modelo vigente medido en la **misma** ventana. El motivo queda escrito con el formato del Anexo: `Costo en validación 18 210 vs 19 940 del vigente`.
- Las filas sin promoción conocida (observaciones de días que nadie pidió pronosticar) alimentan las variables de historia, pero no el aprendizaje.

**Justificación:** si los factores se calibraran en la misma ventana en que se mide el costo, el candidato saldría optimista frente al vigente, que se calibró con días anteriores. Con tres tramos, la validación de un reentrenamiento siempre queda fuera de lo que vio el vigente: su validación terminó en su propia `T`, que es anterior. El modelo aprende con datos de hasta 8 semanas atrás, pero predice con las observaciones más recientes a través de las variables de historia.

**Alternativas:**

| Alternativa | En contra |
|---|---|
| Dos tramos (calibrar y medir en la misma ventana) | Costo optimista del candidato |
| Exigir una mejora mínima del 1 % | Un umbral más sin datos para justificarlo; se puede revisar con la evaluación |
| Promover siempre el último | No es un criterio |
| Validación de 14 días | Métrica más ruidosa |
