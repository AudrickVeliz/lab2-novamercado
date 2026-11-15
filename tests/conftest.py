"""Catálogos y ventas sintéticas para las pruebas: no dependen de los datos publicados."""

import numpy as np
import pandas as pd
import pytest

from novamercado.catalogos import cargar_catalogos
from novamercado.limpieza import Referencia

FAMILIAS = ["abarrotes", "frutas_verduras", "lacteos", "snacks"]

CATALOGOS = {
    "tiendas.csv": (
        "tienda_id,nombre,ciudad,departamento,tipo,fecha_apertura\n"
        "1,NovaMercado Zona 10,Guatemala,Guatemala,hipermercado,2019-01-01\n"
        "5,NovaMercado Quetzaltenango,Quetzaltenango,Quetzaltenango,hipermercado,2019-01-01\n"
        "10,NovaMercado Express Zona 16,Guatemala,Guatemala,express,2025-03-15\n"
    ),
    "familias.csv": (
        "familia_id,nombre\n"
        "abarrotes,Abarrotes\n"
        "frutas_verduras,Frutas y verduras\n"
        "lacteos,Lácteos\n"
        "snacks,Snacks y dulces\n"
    ),
    "costos.csv": (
        "familia_id,costo_faltante,costo_sobrante\n"
        "abarrotes,1.0,0.2\n"
        "frutas_verduras,1.0,2.0\n"
        "lacteos,1.0,1.2\n"
        "snacks,1.0,0.3\n"
    ),
    "feriados.csv": (
        "fecha,nombre,tipo,ambito\n"
        "2025-11-01,Día de Todos los Santos,feriado,nacional\n"
        "2026-12-25,Navidad,feriado,nacional\n"
        "2025-09-15,Feria de Xela,feriado,Quetzaltenango\n"
        "2025-07-15,Pago de bono 14,pago,nacional\n"
    ),
}


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


def generar_historico(dias=180, inicio="2025-03-01", semilla=0):
    """Ventas con patrón semanal, efecto de promoción y ruido de Poisson, por tienda y familia."""
    azar = np.random.default_rng(semilla)
    fechas = pd.date_range(inicio, periods=dias, freq="D")
    nivel = {"abarrotes": 600, "frutas_verduras": 300, "lacteos": 250, "snacks": 120}
    semana = np.array([0.88, 0.89, 0.91, 0.93, 1.08, 1.23, 1.08])
    filas = []
    for tienda, escala, apertura in ((1, 1.2, "2019-01-01"), (5, 1.0, "2019-01-01"), (10, 0.4, "2025-03-15")):
        for familia, base in nivel.items():
            for fecha in fechas[fechas >= apertura]:
                promocion = int(azar.random() < 0.2) * int(azar.integers(1, 10))
                media = base * escala * semana[fecha.dayofweek] * (1 + 0.04 * promocion)
                filas.append((fecha, tienda, familia, int(azar.poisson(media)), promocion))
    return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])


@pytest.fixture(scope="session")
def historico():
    return generar_historico()
