# Imagen del producto: la API y el entrenamiento inicial (ver D-010).
# Los datos y las credenciales no forman parte de la imagen: llegan por volumen y variables.
FROM docker.io/library/python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG RESTRICCIONES=https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt

WORKDIR /opt/novamercado
COPY pyproject.toml ./
COPY src ./src
# Las restricciones de Airflow fijan también las dependencias transitivas (D-005).
RUN pip install --constraint "$RESTRICCIONES" .

# Usuario sin privilegios. La carpeta de la copia del modelo se crea con su dueño
# para que el volumen con nombre herede esos permisos al montarse por primera vez.
RUN useradd --create-home --uid 1000 novamercado \
    && mkdir -p /var/lib/novamercado/modelo \
    && chown -R novamercado /var/lib/novamercado
USER novamercado

EXPOSE 8000
CMD ["uvicorn", "--factory", "novamercado.api:app_desde_entorno", "--host", "0.0.0.0", "--port", "8000"]
