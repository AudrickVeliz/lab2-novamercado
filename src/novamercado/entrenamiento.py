"""Entrenamiento por tramos y criterio de reemplazo del modelo vigente (ver D-008).

    ── entrenamiento ──┤ calibración (28 días) │ validación (28 días) │
                       T-55                     T-27                   T

El modelo aprende con el primer tramo, los factores de la cantidad sugerida se
calibran en el segundo y el costo se mide en el tercero. Todo fuera de muestra.

Evaluación sin MLflow:

    python -m novamercado.entrenamiento --datos data/publicados
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from novamercado import caracteristicas
from novamercado.catalogos import Catalogos, cargar_catalogos, cargar_historico
from novamercado.modelo import Baseline, Estimador, GradientBoosting, Hiperparametros, ModeloEntrenado
from novamercado.negocio import calibrar_factores, metricas

DIAS_VALIDACION = 28
DIAS_CALIBRACION = 28


class DatosInsuficientes(ValueError):
    """No alcanzan las fechas para entrenar, calibrar y validar."""


@dataclass(frozen=True)
class Tramos:
    inicio_calibracion: pd.Timestamp
    inicio_validacion: pd.Timestamp
    fin_validacion: pd.Timestamp

    @classmethod
    def hasta(cls, ultima_fecha: pd.Timestamp) -> Tramos:
        inicio_validacion = ultima_fecha - pd.Timedelta(days=DIAS_VALIDACION - 1)
        return cls(inicio_validacion - pd.Timedelta(days=DIAS_CALIBRACION), inicio_validacion, ultima_fecha)

    def como_texto(self) -> dict[str, str]:
        return {
            "inicio_calibracion": self.inicio_calibracion.date().isoformat(),
            "inicio_validacion": self.inicio_validacion.date().isoformat(),
            "fin_validacion": self.fin_validacion.date().isoformat(),
        }


@dataclass(frozen=True)
class Datos:
    """ventas: todo lo conocido (para las variables). objetivos: filas con promoción conocida (para aprender)."""

    ventas: pd.DataFrame
    objetivos: pd.DataFrame


@dataclass
class Candidato:
    modelo: ModeloEntrenado
    metricas: dict[str, float]


@dataclass(frozen=True)
class Decision:
    promover: Candidato | None
    motivo: str


def preparar_datos(
    historico: pd.DataFrame,
    observaciones: pd.DataFrame | None = None,
    promociones: pd.DataFrame | None = None,
) -> Datos:
    """Une el histórico con las observaciones registradas.

    Las observaciones no traen la promoción del día: se toma de las solicitudes de
    predicción registradas (promociones). Sin promoción conocida, la fila solo
    alimenta las variables de historia, no el aprendizaje.
    """
    clave = caracteristicas.CLAVE
    ventas = historico[clave + ["ventas"]]
    objetivos = historico[clave + ["ventas", "en_promocion"]]
    if observaciones is not None and len(observaciones):
        # Una observación registrada corrige al histórico si coinciden.
        ventas = pd.concat([ventas, observaciones[clave + ["ventas"]]]).drop_duplicates(clave, keep="last")
        if promociones is not None and len(promociones):
            nuevas = observaciones[clave + ["ventas"]].merge(promociones[clave + ["en_promocion"]], on=clave)
            objetivos = pd.concat([objetivos, nuevas]).drop_duplicates(clave, keep="last")
    return Datos(ventas.reset_index(drop=True), objetivos.sort_values(clave).reset_index(drop=True))


def entrenar(
    datos: Datos, catalogos: Catalogos, hiperparametros: Hiperparametros = Hiperparametros()
) -> tuple[Tramos, Candidato, Candidato]:
    """Entrena, calibra y valida el baseline y el gradient boosting. Devuelve (tramos, baseline, gbm)."""
    tramos = Tramos.hasta(datos.objetivos["fecha"].max())
    variables = caracteristicas.construir(datos.ventas, datos.objetivos, catalogos)
    fechas, ventas = datos.objetivos["fecha"], datos.objetivos["ventas"]
    en_entrenamiento = fechas < tramos.inicio_calibracion
    en_calibracion = (fechas >= tramos.inicio_calibracion) & (fechas < tramos.inicio_validacion)
    if not (en_entrenamiento.any() and en_calibracion.any()):
        raise DatosInsuficientes(f"Se necesitan más de {DIAS_CALIBRACION + DIAS_VALIDACION} días de ventas")

    candidatos = []
    for estimador in (Baseline(), GradientBoosting(hiperparametros)):
        estimador.entrenar(variables[en_entrenamiento], ventas[en_entrenamiento])
        modelo = ModeloEntrenado(estimador, _factores(estimador, variables, ventas, en_calibracion, catalogos))
        candidatos.append(Candidato(modelo, evaluar(modelo, variables, ventas, fechas, tramos, catalogos)))
    for candidato in candidatos:
        candidato.modelo.linaje = {**tramos.como_texto(), "filas_entrenamiento": str(int(en_entrenamiento.sum()))}
    return tramos, candidatos[0], candidatos[1]


def evaluar(
    modelo: ModeloEntrenado,
    variables: pd.DataFrame,
    ventas: pd.Series,
    fechas: pd.Series,
    tramos: Tramos,
    catalogos: Catalogos,
) -> dict[str, float]:
    """Métricas en la ventana de validación; sirve también para medir al modelo vigente."""
    filas = (fechas >= tramos.inicio_validacion) & (fechas <= tramos.fin_validacion)
    esperada, sugerida = modelo.predecir(variables[filas])
    familias = variables.loc[filas, "familia_id"].astype(str).to_numpy()
    return metricas(ventas[filas].to_numpy(dtype=float), esperada, sugerida, familias, catalogos)


def decidir(baseline: Candidato, gbm: Candidato, costo_vigente: float | None) -> Decision:
    """Criterio de reemplazo: el gradient boosting debe costar menos que el baseline y que el vigente."""
    costo_gbm, costo_base = gbm.metricas["costo"], baseline.metricas["costo"]
    contra_baseline = f"Costo en validación {_miles(costo_gbm)} vs {_miles(costo_base)} del baseline"
    if costo_vigente is None:
        if costo_gbm < costo_base:
            return Decision(gbm, f"Primer modelo. {contra_baseline}")
        return Decision(baseline, f"Primer modelo: el baseline. {contra_baseline}")
    contra_vigente = f"Costo en validación {_miles(costo_gbm)} vs {_miles(costo_vigente)} del vigente"
    if costo_gbm >= costo_base:
        return Decision(None, f"No supera al baseline. {contra_baseline}")
    if costo_gbm >= costo_vigente:
        return Decision(None, f"No supera al vigente. {contra_vigente}")
    return Decision(gbm, contra_vigente)


def _miles(valor: float) -> str:
    """18210.4 → '18 210', como en el ejemplo del Anexo."""
    return f"{valor:,.0f}".replace(",", " ")


def _factores(
    estimador: Estimador, variables: pd.DataFrame, ventas: pd.Series, filas: pd.Series, catalogos: Catalogos
) -> dict[str, float]:
    esperada = estimador.predecir(variables[filas])
    familias = variables.loc[filas, "familia_id"].astype(str).to_numpy()
    return calibrar_factores(ventas[filas].to_numpy(dtype=float), esperada, familias, catalogos)


def _principal() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--datos", default=None, help="carpeta de los archivos publicados")
    carpeta = argumentos.parse_args().datos
    catalogos = cargar_catalogos(carpeta)
    datos = preparar_datos(cargar_historico(catalogos, carpeta))
    tramos, baseline, gbm = entrenar(datos, catalogos)
    print(f"Tramos: {tramos.como_texto()}")
    for nombre, candidato in (("baseline", baseline), ("gradient_boosting", gbm)):
        resumen = ", ".join(f"{k}={v:,.3f}" for k, v in candidato.metricas.items())
        print(f"{nombre:18} {resumen}")
    print("Factores (gbm):", {k: round(v, 3) for k, v in gbm.modelo.factores.items()})
    print("Decisión sin vigente:", decidir(baseline, gbm, None).motivo)


if __name__ == "__main__":
    _principal()
