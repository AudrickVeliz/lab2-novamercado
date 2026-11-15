"""API del servicio según el Anexo del enunciado (ver D-005).

Los endpoints solo orquestan: la limpieza, el registro y el modelo viven en sus
módulos. Se arranca con:

    uvicorn --factory novamercado.api:app_desde_entorno --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from novamercado.catalogos import cargar_catalogos, cargar_historico, carpeta_datos
from novamercado.contrato import (
    PrediccionFamilia,
    RespuestaObservacion,
    RespuestaPrediccion,
    SolicitudObservacion,
    SolicitudPrediccion,
)
from novamercado.limpieza import (
    Referencia,
    Resultado,
    SolicitudRechazada,
    limpiar_observacion,
    limpiar_prediccion,
    maximos_historicos,
)
from novamercado.modelo import ModeloEntrenado
from novamercado.persistencia import (
    Endpoint,
    EstadoSinAtender,
    RegistroPostgres,
    crear_esquema,
    crear_motor,
    leer_observaciones,
)
from novamercado.prediccion import ModeloVigente, PredictorVentas
from novamercado.registro_modelos import cargar_version, verificar_servidor, version_vigente

log = logging.getLogger(__name__)

VARIABLE_COPIA = "NOVAMERCADO_COPIA_MODELO"
# Copia local del modelo vigente, para arrancar aunque MLflow no responda (D-009).
COPIA_PREDETERMINADA = "/var/lib/novamercado/modelo/vigente.joblib"

SIN_MODELO = "El modelo todavía no está disponible"
SIN_REGISTRO = "No se pudo registrar la solicitud; intente de nuevo"


class Predictor(Protocol):
    nombre: str
    alias: str
    version: str

    def predecir(self, solicitud: SolicitudPrediccion) -> list[PrediccionFamilia]: ...


class Registro(Protocol):
    def rechazo(self, endpoint: Endpoint, cuerpo: Any, motivo: str, estado: EstadoSinAtender = ...) -> int: ...

    def prediccion(
        self,
        cuerpo: Any,
        resultado: Resultado[SolicitudPrediccion],
        respuesta: RespuestaPrediccion,
        modelo_nombre: str,
    ) -> int: ...

    def observacion(self, cuerpo: Any, resultado: Resultado[SolicitudObservacion]) -> int: ...


@dataclass(frozen=True)
class Dependencias:
    referencia: Referencia
    registro: Registro
    # Se consulta en cada solicitud: el modelo vigente puede cambiar sin reiniciar la API.
    predictor: Callable[[], Predictor | None]
    # Nombre de la dependencia -> función que lanza una excepción si no está disponible.
    chequeos: Mapping[str, Callable[[], None]] = field(default_factory=dict)


def crear_app(dependencias: Dependencias) -> FastAPI:
    app = FastAPI(title="Servicio de pronóstico de NovaMercado")

    @app.post("/v1/prediccion")
    async def prediccion(request: Request) -> JSONResponse:
        cuerpo = await _leer_cuerpo(request)
        return await run_in_threadpool(_atender_prediccion, dependencias, cuerpo)

    @app.post("/v1/observaciones")
    async def observaciones(request: Request) -> JSONResponse:
        cuerpo = await _leer_cuerpo(request)
        return await run_in_threadpool(_atender_observacion, dependencias, cuerpo)

    @app.get("/modelo")
    def modelo() -> JSONResponse:
        predictor = dependencias.predictor()
        if predictor is None:
            return _error(503, SIN_MODELO)
        return JSONResponse({"nombre": predictor.nombre, "alias": predictor.alias, "version": predictor.version})

    @app.get("/health")
    def health() -> JSONResponse:
        fallas = _fallas(dependencias.chequeos)
        if dependencias.predictor() is None:
            motivo = "; ".join(["No hay un modelo cargado", *fallas])
            return JSONResponse({"estado": "degradado", "motivo": motivo}, status_code=503)
        if fallas:
            return JSONResponse({"estado": "degradado", "motivo": "; ".join(fallas)})
        return JSONResponse({"estado": "ok"})

    return app


def _atender_prediccion(dependencias: Dependencias, cuerpo: Any) -> JSONResponse:
    try:
        resultado = limpiar_prediccion(cuerpo, dependencias.referencia)
    except SolicitudRechazada as rechazo:
        return _sin_atender(dependencias, "prediccion", cuerpo, 422, rechazo.detalle, "rechazada")

    # Una sola consulta: la versión informada es la del modelo que predijo.
    predictor = dependencias.predictor()
    if predictor is None:
        return _sin_atender(dependencias, "prediccion", cuerpo, 503, SIN_MODELO, "no_atendida")
    try:
        predicciones = predictor.predecir(resultado.solicitud)
    except Exception:
        log.exception("El modelo %s v%s falló al predecir", predictor.nombre, predictor.version)
        return _sin_atender(dependencias, "prediccion", cuerpo, 503, "El modelo no pudo generar el pronóstico", "no_atendida")

    respuesta = RespuestaPrediccion(
        tienda_id=resultado.solicitud.tienda_id,
        fecha=resultado.solicitud.fecha,
        version_modelo=predictor.version,
        predicciones=predicciones,
        calidad=resultado.calidad,
    )
    try:
        dependencias.registro.prediccion(cuerpo, resultado, respuesta, predictor.nombre)
    except SQLAlchemyError:
        log.exception("No se pudo registrar la predicción")
        return _error(503, SIN_REGISTRO)
    return JSONResponse(respuesta.model_dump(mode="json"))


def _atender_observacion(dependencias: Dependencias, cuerpo: Any) -> JSONResponse:
    try:
        resultado = limpiar_observacion(cuerpo, dependencias.referencia)
    except SolicitudRechazada as rechazo:
        return _sin_atender(dependencias, "observaciones", cuerpo, 422, rechazo.detalle, "rechazada")
    try:
        guardados = dependencias.registro.observacion(cuerpo, resultado)
    except SQLAlchemyError:
        log.exception("No se pudo registrar la observación")
        return _error(503, SIN_REGISTRO)
    respuesta = RespuestaObservacion(registros_guardados=guardados, calidad=resultado.calidad)
    return JSONResponse(respuesta.model_dump(mode="json"))


def _sin_atender(
    dependencias: Dependencias, endpoint: Endpoint, cuerpo: Any, codigo: int, motivo: str, estado: EstadoSinAtender
) -> JSONResponse:
    try:
        dependencias.registro.rechazo(endpoint, cuerpo, motivo, estado)
    except SQLAlchemyError:
        log.exception("No se pudo registrar la solicitud no atendida")
        return _error(503, SIN_REGISTRO)
    return _error(codigo, motivo)


def _error(codigo: int, detalle: str) -> JSONResponse:
    return JSONResponse({"detail": detalle}, status_code=codigo)


def _rechazar_constante(nombre: str) -> None:
    raise ValueError(f"{nombre} no es un número JSON válido")


async def _leer_cuerpo(request: Request) -> Any:
    """El JSON de la solicitud; si no es JSON válido, el texto tal como llegó (la limpieza lo rechaza)."""
    texto = (await request.body()).decode("utf-8", errors="replace")
    try:
        # NaN e Infinity no son JSON válido ni se pueden guardar en JSONB.
        return json.loads(texto, parse_constant=_rechazar_constante)
    except ValueError:
        return texto


def _fallas(chequeos: Mapping[str, Callable[[], None]]) -> list[str]:
    fallas = []
    for nombre, chequeo in chequeos.items():
        try:
            chequeo()
        except Exception as error:
            primera_linea = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
            fallas.append(f"{nombre} no disponible: {primera_linea}")
    return fallas


def app_desde_entorno() -> FastAPI:
    """Arma la app con los datos publicados, la base del producto y MLflow; falla al arrancar si faltan."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Por defecto el cliente de MLflow reintenta 7 veces con espera creciente: con MLflow caído,
    # la recarga quedaría bloqueada varios minutos. Mejor fallar rápido y probar en 30 s.
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    carpeta = carpeta_datos()
    catalogos = cargar_catalogos(carpeta)
    historico = cargar_historico(catalogos, carpeta)
    motor = crear_motor()
    crear_esquema(motor)
    registro = RegistroPostgres(motor)
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "")

    def crear_predictor(modelo: ModeloEntrenado, version: str) -> PredictorVentas:
        return PredictorVentas(
            modelo, version, catalogos, historico,
            lambda tienda, desde, antes_de: leer_observaciones(motor, tienda, desde, antes_de),
        )

    vigente = ModeloVigente(
        version_vigente, cargar_version, crear_predictor, Path(os.environ.get(VARIABLE_COPIA, COPIA_PREDETERMINADA))
    )
    vigente.iniciar()
    threading.Thread(target=vigente.vigilar, args=(threading.Event(),), daemon=True, name="modelo-vigente").start()
    return crear_app(
        Dependencias(
            referencia=Referencia(catalogos, maximos_historicos(historico)),
            registro=registro,
            predictor=vigente,
            chequeos={"base de datos": registro.verificar, "MLflow": lambda: verificar_servidor(tracking_uri)},
        )
    )
