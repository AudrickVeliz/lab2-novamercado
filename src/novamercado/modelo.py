"""Modelos de pronóstico: el baseline y el gradient boosting (ver D-006).

Ambos reciben las variables de `novamercado.caracteristicas` y devuelven la venta
esperada. `ModeloEntrenado` agrega los factores de la cantidad sugerida: es lo
que se registra en MLflow y lo que usa la API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from novamercado.caracteristicas import VARIABLES
from novamercado.negocio import cantidad_sugerida


@dataclass(frozen=True)
class Hiperparametros:
    learning_rate: float = 0.05
    max_iter: int = 500
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 40
    l2_regularization: float = 1.0


class Baseline:
    """Media de las ventas de los últimos cuatro días con el mismo día de la semana."""

    tipo = "baseline"

    def entrenar(self, variables: pd.DataFrame, ventas: pd.Series) -> Baseline:
        return self

    def predecir(self, variables: pd.DataFrame) -> np.ndarray:
        # Sin cuatro semanas de historia (una tienda recién abierta), la mejor referencia disponible.
        esperada = variables["media_mismo_dia_4"].fillna(variables["media_28"]).fillna(variables["ultima_venta"])
        return esperada.fillna(0).to_numpy(dtype=float)


class GradientBoosting:
    """Un único modelo para todas las tiendas y familias, con pérdida de Poisson para ventas en unidades."""

    tipo = "gradient_boosting"

    def __init__(self, hiperparametros: Hiperparametros = Hiperparametros()):
        self.hiperparametros = hiperparametros
        # Sin early_stopping: su validación interna es aleatoria y mezclaría fechas futuras.
        self.estimador = HistGradientBoostingRegressor(
            loss="poisson",
            categorical_features="from_dtype",
            early_stopping=False,
            random_state=0,
            **asdict(hiperparametros),
        )

    def entrenar(self, variables: pd.DataFrame, ventas: pd.Series) -> GradientBoosting:
        # Una variable sin ningún dato (venta_hace_364 con menos de un año de historia) no se
        # puede discretizar: se trata como constante, igual al entrenar que al predecir.
        self.sin_datos = [c for c in VARIABLES if variables[c].isna().all()]
        self.estimador.fit(self._preparar(variables), ventas)
        return self

    def predecir(self, variables: pd.DataFrame) -> np.ndarray:
        return np.clip(self.estimador.predict(self._preparar(variables)), 0, None)

    def _preparar(self, variables: pd.DataFrame) -> pd.DataFrame:
        return variables[VARIABLES].assign(**{c: 0.0 for c in self.sin_datos})


Estimador = Baseline | GradientBoosting


@dataclass
class ModeloEntrenado:
    estimador: Estimador
    factores: dict[str, float]
    # Fechas de los tramos y métricas del entrenamiento que lo produjo.
    linaje: dict[str, str] = field(default_factory=dict)

    @property
    def tipo(self) -> str:
        return self.estimador.tipo

    def predecir(self, variables: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """(venta esperada, cantidad sugerida) por fila."""
        esperada = self.estimador.predecir(variables)
        familias = variables["familia_id"].astype(str).to_numpy()
        return esperada, cantidad_sugerida(esperada, familias, self.factores)
