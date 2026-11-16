"""Catálogos y ventas sintéticas para las pruebas: no dependen de los datos publicados."""

import pytest

from datos_sinteticos import CATALOGOS, FAMILIAS, generar_historico
from novamercado.catalogos import cargar_catalogos
from novamercado.limpieza import Referencia


@pytest.fixture(scope="session")
def catalogos(tmp_path_factory):
    carpeta = tmp_path_factory.mktemp("publicados")
    for nombre, contenido in CATALOGOS.items():
        (carpeta / nombre).write_text(contenido, encoding="utf-8")
    return cargar_catalogos(carpeta)


@pytest.fixture(scope="session")
def referencia(catalogos):
    maximos = {(tienda, familia): 1000 for tienda in (1, 5, 10) for familia in FAMILIAS}
    return Referencia(catalogos, maximos)


@pytest.fixture
def prediccion():
    """Solicitud de predicción válida (copia nueva en cada prueba)."""
    return {
        "tienda_id": 5,
        "fecha": "2025-11-17",
        "familias": [
            {"familia_id": "abarrotes", "en_promocion": 0},
            {"familia_id": "frutas_verduras", "en_promocion": 0},
            {"familia_id": "lacteos", "en_promocion": 2},
            {"familia_id": "snacks", "en_promocion": 9},
        ],
    }


@pytest.fixture
def observacion():
    """Observación de ventas válida (copia nueva en cada prueba)."""
    return {
        "tienda_id": 5,
        "fecha": "2025-11-17",
        "ventas": [
            {"familia_id": "abarrotes", "ventas": 994},
            {"familia_id": "frutas_verduras", "ventas": 310},
            {"familia_id": "lacteos", "ventas": 0},
            {"familia_id": "snacks", "ventas": 120},
        ],
    }


@pytest.fixture(scope="session")
def historico():
    return generar_historico()


@pytest.fixture(scope="session")
def entrenado(historico, catalogos):
    """(tramos, baseline, gbm) entrenados una sola vez con las ventas sintéticas."""
    from novamercado.entrenamiento import entrenar, preparar_datos

    return entrenar(preparar_datos(historico), catalogos)


@pytest.fixture
def mlflow_local(tmp_path, monkeypatch):
    """MLflow sobre SQLite en una carpeta temporal: las pruebas no dependen de un servidor."""
    monkeypatch.chdir(tmp_path)  # los artefactos van a ./mlruns de la carpeta temporal
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}")
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    return tmp_path
