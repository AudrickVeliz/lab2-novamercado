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
