"""Costo de negocio y cantidad sugerida a partir de costos.csv (ver D-007).

costo = c_faltante × máx(real − sugerido, 0) + c_sobrante × máx(sugerido − real, 0)

La cantidad sugerida es la venta esperada por un factor por familia. El factor
que minimiza el costo es el cuantil c_faltante / (c_faltante + c_sobrante) de
real / esperada, ponderado por la venta esperada.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from novamercado.catalogos import Catalogos

# Sin datos de calibración para una familia, la sugerida es la venta esperada.
FACTOR_NEUTRO = 1.0


def cuantil_objetivo(catalogos: Catalogos) -> pd.Series:
    costos = catalogos.costos
    return costos["costo_faltante"] / (costos["costo_faltante"] + costos["costo_sobrante"])


def calibrar_factores(
    real: np.ndarray, esperada: np.ndarray, familias: np.ndarray, catalogos: Catalogos
) -> dict[str, float]:
    cuantiles = cuantil_objetivo(catalogos)
    factores = {}
    for familia in sorted(catalogos.ids_familias):
        filas = (familias == familia) & (esperada > 0)
        if not filas.any():
            factores[familia] = FACTOR_NEUTRO
            continue
        factores[familia] = _cuantil_ponderado(real[filas] / esperada[filas], esperada[filas], cuantiles[familia])
    return factores


def cantidad_sugerida(esperada: np.ndarray, familias: np.ndarray, factores: dict[str, float]) -> np.ndarray:
    factor = np.array([factores.get(f, FACTOR_NEUTRO) for f in familias])
    return np.maximum(np.round(esperada * factor), 0).astype(int)


def costo(real: np.ndarray, sugerida: np.ndarray, familias: np.ndarray, catalogos: Catalogos) -> np.ndarray:
    costos = catalogos.costos
    faltante = pd.Series(familias).map(costos["costo_faltante"]).to_numpy()
    sobrante = pd.Series(familias).map(costos["costo_sobrante"]).to_numpy()
    return faltante * np.maximum(real - sugerida, 0) + sobrante * np.maximum(sugerida - real, 0)


def metricas(
    real: np.ndarray, esperada: np.ndarray, sugerida: np.ndarray, familias: np.ndarray, catalogos: Catalogos
) -> dict[str, float]:
    """Métricas técnicas del pronóstico y costo de negocio de la cantidad sugerida."""
    error = esperada - real
    total_real = real.sum()
    return {
        "costo": float(costo(real, sugerida, familias, catalogos).sum()),
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "wape": float(np.abs(error).sum() / total_real) if total_real else float("nan"),
        "sesgo": float(error.sum() / total_real) if total_real else float("nan"),
    }


def _cuantil_ponderado(valores: np.ndarray, pesos: np.ndarray, cuantil: float) -> float:
    orden = np.argsort(valores)
    acumulado = np.cumsum(pesos[orden])
    posicion = np.searchsorted(acumulado, cuantil * acumulado[-1])
    return float(valores[orden][min(posicion, len(valores) - 1)])
