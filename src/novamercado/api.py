"""API del servicio según el Anexo del enunciado (ver D-005).

Los endpoints solo orquestan: la limpieza, el registro y el modelo viven en sus
módulos. Se arranca con:

    uvicorn --factory novamercado.api:app_desde_entorno --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
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
from novamercado.persistencia import (
    Endpoint,
    EstadoSinAtender,
    RegistroPostgres,
    crear_esquema,
    crear_motor,
)

log = logging.getLogger(__name__)

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


def _cargar_referencia(carpeta: Path) -> Referencia:
    catalogos = cargar_catalogos(carpeta)
    return Referencia(catalogos, maximos_historicos(cargar_historico(catalogos, carpeta)))


def app_desde_entorno() -> FastAPI:
    """Arma la app con los datos publicados y la base del producto; falla al arrancar si faltan."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    referencia = _cargar_referencia(carpeta_datos())
    motor = crear_motor()
    crear_esquema(motor)
    registro = RegistroPostgres(motor)
    return crear_app(
        Dependencias(
            referencia=referencia,
            registro=registro,
            # El PR del modelo conecta aquí el modelo vigente del Model Registry de MLflow.
            predictor=lambda: None,
            chequeos={"base de datos": registro.verificar},
        )
    )
