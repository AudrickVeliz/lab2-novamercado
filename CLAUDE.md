# Servicio de Pronóstico de NovaMercado

Laboratorio 2 de Product Development (Universidad Galileo). Servicio de ML en producción que recibe solicitudes de pronóstico diario de ventas por tienda y familia, responde aunque los datos lleguen en mal estado, registra lo que predice y lo que realmente ocurre, y reentrena su modelo de forma automática.

Lo principal no es el modelo, sino operar el servicio: defender el contrato, registrar la operación y reentrenar sin intervención manual. La evaluación simula la operación diaria de las tiendas durante un periodo no publicado.

## Reglas del producto

1. **El contrato del Anexo es la ley.** Las respuestas pueden agregar campos, pero nunca omitir ni renombrar los del contrato. El servicio escucha en el puerto 8000.
2. **Reparar, advertir o rechazar, siempre de forma explícita.** Cada tipo de problema en los datos tiene una política documentada y se aplica igual siempre. Las reglas son generales: llegarán problemas que no están en el catálogo. El servicio no se detiene, pero tampoco inventa datos.
3. **Sin reloj del sistema.** Las fechas son simuladas: la validez de una fecha nunca depende de la fecha actual de la máquina.
4. **Sin fuga de información.** Al pronosticar una fecha solo se usan observaciones de días anteriores. Las promociones del día vienen en la solicitud.
5. **Todo queda registrado.** Solicitudes, correcciones, predicciones (con la versión del modelo) y observaciones se guardan en el PostgreSQL del producto. Registrar una observación es idempotente.
6. **El modelo vigente no se toca sin criterio.** Un reentrenamiento que falla o no supera el criterio de reemplazo no afecta al modelo vigente. El vigente se identifica con un alias en el Model Registry de MLflow.
7. **El servicio sobrevive a sus dependencias.** Si MLflow cae, la API sigue respondiendo con el modelo cargado y `/health` lo refleja.
8. **La lógica vive en módulos con pruebas.** Ni los endpoints ni los DAGs contienen lógica de limpieza, modelado o decisión.
9. **Los costos de negocio vienen de `costos.csv`.** La cantidad sugerida y la métrica de negocio se derivan de esos costos, sin valores fijos en el código.
10. **Sin intervención manual.** Desde cero, el producto carga los datos, entrena y registra el primer modelo por sí solo; al volver a levantarse conserva lo que tiene.

## Flujo de Git

- `main` está protegida: todo cambio entra por Pull Request con las pruebas en verde. Audrick revisa cada PR y aprueba el merge.
- Ramas con prefijo y descripción corta: `feat/`, `fix/`, `chore/`, `docs/`, `test/`.
- Commits pequeños y de un solo propósito, en español, con el formato `tipo: descripción` (`feat: validar el contrato de predicción`).
- Cada PR cubre un solo tema y explica qué cambia y cómo se verificó.
- La entrega se identifica con el tag `entrega-lab2`.

## Datos

- Los archivos publicados por el equipo docente van en `data/publicados/`. Ningún dato se genera fuera de la carpeta del proyecto.
- Ningún dato, modelo ni credencial va en Git ni en las imágenes.
- Cada cosa se versiona en un solo lugar (ver D-002):
  - **Datos de entrada** (`data/publicados/`): DVC, con un remoto privado en DagsHub. Solo se usa en desarrollo.
  - **Modelos, experimentos y linaje**: MLflow. Cada run registra con qué datos y con qué código se entrenó, e incluye un snapshot del dataset de entrenamiento.
  - **Operación** (solicitudes, correcciones, predicciones con su versión de modelo, observaciones): el PostgreSQL del producto.
- El producto nunca ejecuta DVC ni depende de DagsHub: el equipo docente coloca sus propios archivos y levanta sin credenciales personales.
- Las credenciales se pasan por variables de entorno; `.env.example` documenta las necesarias. El token de DagsHub solo vive en `.dvc/config.local`.

## Entorno

- Python 3.12 en el entorno de Conda `lab2`. Dependencias con versiones exactas.
- Todo el producto (API, PostgreSQL propio, MLflow como servicio `mlflow`, Airflow con su propio PostgreSQL) se levanta con `docker compose up`.
- Localmente se ejecuta sobre Podman en modo rootless, pero el compose debe funcionar sin cambios en Docker, que es lo que usará el equipo docente.
- Imágenes con versiones fijas.
- Todo el texto se guarda con finales de línea LF.

## Documentación

- Cada decisión técnica o de producto se registra en `DECISIONES.md` con sus alternativas y su justificación, en particular: la política ante cada tipo de problema en los datos, la información que usa el modelo al predecir, la elección de la cantidad sugerida y el criterio de reemplazo del modelo.
- `README.md` debe permitir levantar el producto desde cero, e indicar la carpeta donde se colocan los archivos publicados.

## Fidelidad al enunciado

- El enunciado (`Laboratorio_2_PD_26_c.pdf`, fuera de Git) es la fuente de verdad. Si una mejora choca con él, gana el enunciado.
- Los nombres de campos, los tipos, los valores permitidos y los códigos HTTP del Anexo se copian literalmente, y las pruebas del contrato los comprueban.
- Cada PR indica qué requerimiento del enunciado cubre: el número del requerimiento o el endpoint del Anexo.

## Código

- Funciones cortas y de un solo propósito. Los nombres van en español y son los del dominio (tienda, familia, observación), iguales en el código, la base de datos y la documentación.
- Una regla vive en un solo lugar: una normalización o una política se reutiliza, no se copia.
- Sin valores mágicos: los umbrales y parámetros de política son constantes con nombre justificadas en `DECISIONES.md`, o salen de los datos publicados.
- Sin código especulativo: nada de parámetros, capas o abstracciones "por si acaso", código muerto ni imports sin uso.
- Errores explícitos: excepciones propias del dominio, con mensajes que digan qué revisar. Nunca un `except` vacío ni un error silenciado.
- Tipos en las firmas de las funciones públicas.
- No se agrega una dependencia si alcanza con la biblioteca estándar o con una que ya está.

## Comentarios y docstrings

- Un comentario explica el porqué (regla de negocio, supuesto, restricción, referencia a una decisión `D-XXX`). Nunca repite lo que el código ya dice.
- Una línea; dos solo si la segunda aporta un hecho nuevo.
- Sin separadores decorativos (`# ---`, `# ===`), mayúsculas para gritar, emojis, narración paso a paso ("Paso 1…") ni marcadores de fin de bloque.
- Sin TODOs vagos: un TODO dice qué falta y por qué, o no se escribe.
- Un docstring solo existe si dice algo que la firma no: reglas, supuestos, efectos o errores.
- Se conservan siempre los comentarios sobre reglas de negocio, decisiones, contratos, seguridad y casos límite.

## Pruebas

- Cada política, regla o criterio tiene al menos una prueba que lo nombra (`test_e08_...`).
- Las pruebas no dependen de servidores en ejecución (MLflow, Airflow, base de datos) ni de los datos publicados; las que usan los datos reales se saltan si no están.
- Una prueba que falla no se ajusta hasta entender por qué falló: puede ser el código o la prueba.

## Cómo trabajar en este proyecto

- Avanza paso a paso y consulta con Audrick cómo hacer cada paso antes de implementarlo.
- Antes de abrir un PR, revisa el diff contra estas reglas y contra el enunciado, corre pytest y reporta el resultado en el PR.
- No se instalan skills, plugins ni herramientas de agentes de terceros: las buenas prácticas se escriben aquí.
- Explica el porqué de cada decisión: Audrick debe poder comprender y justificar todo el código.
- No declares algo terminado sin haberlo ejecutado; reporta el comando y el resultado.
