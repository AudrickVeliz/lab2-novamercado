"""Modelo vigente en la API: predicción con historia reciente y recarga sin reinicio (ver D-009).

`ModeloVigente` consulta el alias cada 30 segundos. Si la versión cambió, carga
la nueva y recién entonces la reemplaza; si MLflow no responde, sigue con la que
tiene. Cada modelo cargado se copia a disco para poder arrancar sin MLflow.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import joblib
import pandas as pd

from novamercado import caracteristicas
from novamercado.catalogos import Catalogos
from novamercado.contrato import PrediccionFamilia, SolicitudPrediccion
from novamercado.modelo import ModeloEntrenado
from novamercado.registro_modelos import ALIAS, NOMBRE_MODELO

log = logging.getLogger(__name__)

INTERVALO_SEGUNDOS = 30

# (tienda_id, desde, antes_de) -> ventas registradas en ese rango.
LectorObservaciones = Callable[[int, pd.Timestamp, pd.Timestamp], pd.DataFrame]


class PredictorVentas:
    nombre = NOMBRE_MODELO
    alias = ALIAS

    def __init__(
        self,
        modelo: ModeloEntrenado,
        version: str,
        catalogos: Catalogos,
        historico: pd.DataFrame,
        leer_observaciones: LectorObservaciones,
    ):
        self.modelo = modelo
        self.version = version
        self.catalogos = catalogos
        self.historico = historico
        self.leer_observaciones = leer_observaciones

    def predecir(self, solicitud: SolicitudPrediccion) -> list[PrediccionFamilia]:
        fecha = pd.Timestamp(solicitud.fecha)
        desde = fecha - pd.Timedelta(days=caracteristicas.DIAS_DE_HISTORIA + 28)
        historico = self.historico
        historico = historico[
            (historico["tienda_id"] == solicitud.tienda_id) & (historico["fecha"] >= desde) & (historico["fecha"] < fecha)
        ]
        # Solo días anteriores: la observación del día pronosticado nunca entra.
        recientes = self.leer_observaciones(solicitud.tienda_id, desde, fecha)
        ventas = pd.concat([historico[caracteristicas.CLAVE + ["ventas"]], recientes])
        ventas = ventas.drop_duplicates(caracteristicas.CLAVE, keep="last")

        objetivos = pd.DataFrame(
            {
                "fecha": fecha,
                "tienda_id": solicitud.tienda_id,
                "familia_id": [f.familia_id for f in solicitud.familias],
                "en_promocion": [f.en_promocion for f in solicitud.familias],
            }
        )
        esperada, sugerida = self.modelo.predecir(caracteristicas.construir(ventas, objetivos, self.catalogos))
        return [
            PrediccionFamilia(familia_id=f, venta_esperada=round(float(e), 1), cantidad_sugerida=int(s))
            for f, e, s in zip(objetivos["familia_id"], esperada, sugerida)
        ]


class ModeloVigente:
    """Guarda el predictor vigente; la API lo consulta en cada solicitud."""

    def __init__(
        self,
        consultar_version: Callable[[], str | None],
        descargar: Callable[[str], ModeloEntrenado],
        crear_predictor: Callable[[ModeloEntrenado, str], PredictorVentas],
        copia: Path | None = None,
    ):
        self._consultar_version = consultar_version
        self._descargar = descargar
        self._crear_predictor = crear_predictor
        self._copia = copia
        self._actual: PredictorVentas | None = None

    def __call__(self) -> PredictorVentas | None:
        return self._actual

    def actualizar(self) -> None:
        """Carga la versión del alias si cambió. Lanza la excepción si MLflow no responde."""
        version = self._consultar_version()
        if version is None or (self._actual is not None and self._actual.version == version):
            return
        modelo = self._descargar(version)
        self._guardar_copia(modelo, version)
        # Se reemplaza recién con el modelo nuevo ya cargado: nunca queda la API sin modelo.
        self._actual = self._crear_predictor(modelo, version)
        log.info("Modelo vigente: %s v%s", NOMBRE_MODELO, version)

    def iniciar(self) -> None:
        """Primera carga: desde MLflow o, si no responde, desde la copia local."""
        try:
            self.actualizar()
        except Exception:
            log.exception("MLflow no respondió al arrancar; se intenta la copia local")
        if self._actual is None:
            self._cargar_copia()

    def vigilar(self, detener: threading.Event, intervalo: float = INTERVALO_SEGUNDOS) -> None:
        while not detener.wait(intervalo):
            try:
                self.actualizar()
            except Exception as error:
                log.warning("No se pudo consultar el modelo vigente; se mantiene el actual: %s", error)

    def _guardar_copia(self, modelo: ModeloEntrenado, version: str) -> None:
        if self._copia is None:
            return
        self._copia.parent.mkdir(parents=True, exist_ok=True)
        # Modelo y versión en un solo archivo que se reemplaza de una vez: nunca quedan desalineados.
        temporal = self._copia.with_suffix(".tmp")
        joblib.dump({"version": version, "modelo": modelo}, temporal)
        temporal.replace(self._copia)

    def _cargar_copia(self) -> None:
        if self._copia is None or not self._copia.is_file():
            return
        guardado = joblib.load(self._copia)
        self._actual = self._crear_predictor(guardado["modelo"], guardado["version"])
        log.warning("Se usa la copia local del modelo v%s", guardado["version"])
