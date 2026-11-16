# Servicio de pronóstico de NovaMercado

Laboratorio 2 de Product Development. Servicio de ML en producción que pronostica las ventas diarias por tienda y familia, se defiende de los datos defectuosos, registra lo que predice y lo que ocurre, y reentrena su modelo con Airflow y MLflow.

## Levantar el producto desde cero

Requisitos: Docker con Docker Compose (o Podman con `podman compose`), y unos 4 GB de memoria libre.

1. Clonar el repositorio.
2. **Colocar los archivos publicados en `data/publicados/`**, con sus nombres originales:

   ```
   data/publicados/
   ├── historico_ventas.csv
   ├── tiendas.csv
   ├── familias.csv
   ├── feriados.csv
   ├── costos.csv
   ├── catalogo_errores.md
   └── ejemplos/
   ```

3. Crear el archivo de credenciales, que no forma parte del repositorio (conviene cambiar las claves de ejemplo):

   ```
   cp .env.example .env
   ```

4. Levantar:

   ```
   docker compose up -d --build
   ```

5. Esperar a que el servicio esté listo (unos minutos después de construir las imágenes, mientras arranca Airflow):

   ```
   curl http://localhost:8000/health
   {"estado":"ok"}
   ```

Al levantarse desde cero no existe ningún modelo: el servicio `entrenamiento-inicial` entrena y registra el primero con los datos publicados, y la API lo carga sola. Al volver a levantarse conserva todo lo que tiene (bases, modelos y artefactos en volúmenes) y no repite ese trabajo.

| Servicio | Dirección |
|---|---|
| API | http://localhost:8000 (contrato del Anexo) |
| MLflow | http://localhost:5000 |
| Airflow | http://localhost:8080 (usuario y clave: `AIRFLOW_USUARIO` y `AIRFLOW_CLAVE` del `.env`) |

Reentrenar y seguir la ejecución:

```
curl -X POST http://localhost:8000/admin/reentrenar
{"id":"manual__2026-11-16T00:00:00+00:00"}

curl http://localhost:8000/admin/reentrenar/manual__2026-11-16T00:00:00%2B00:00
{"estado":"exitoso","promovido":false,"version":"1","motivo":"No supera al vigente. ..."}
```

Si el modelo nuevo se promueve, la API lo usa en menos de 30 segundos, sin reiniciarse.

Detener sin borrar nada: `docker compose down`. Borrar también los datos guardados: `docker compose down -v`.

## Desarrollo

```
conda create -n lab2 python=3.12
conda activate lab2
pip install -e ".[dev]" --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
pytest
```

Las pruebas no necesitan MLflow ni Airflow. Las de persistencia usan un PostgreSQL si se define `NOVAMERCADO_BD_PRUEBAS_URL`; si no, se saltan.

Las decisiones técnicas y de producto, con sus alternativas, están en [DECISIONES.md](DECISIONES.md).
