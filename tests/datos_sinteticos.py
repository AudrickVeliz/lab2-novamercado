"""Archivos publicados sintéticos: los usan las pruebas y el CI que levanta el compose en Docker.

Los datos reales no están en el repositorio. Uso:

    python tests/datos_sinteticos.py data/publicados
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

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


def escribir(carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in CATALOGOS.items():
        (carpeta / nombre).write_text(contenido, encoding="utf-8")
    generar_historico().to_csv(carpeta / "historico_ventas.csv", index=False, date_format="%Y-%m-%d")
    return carpeta


if __name__ == "__main__":
    print(f"Archivos sintéticos en {escribir(Path(sys.argv[1]))}")
