"""Modelos de Pydantic del contrato del servicio (Anexo del enunciado).

Las solicitudes se validan aquí después de la limpieza: estos modelos son
estrictos y describen una solicitud ya correcta. La tolerancia a los datos
defectuosos vive en `novamercado.limpieza`, no en estos modelos.

Las respuestas pueden incluir campos adicionales, pero nunca omitir ni
renombrar los del contrato.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Ninguna cantidad real de productos o de unidades de un día llega al límite de un entero de
# 32 bits, que es lo que guarda la base: un valor mayor se trata como inválido (D-003).
MAXIMO_ENTERO = 2**31 - 1

Accion = Literal["reparar", "advertir"]
EstadoCalidad = Literal["ok", "corregido", "advertencia"]


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


# Solicitudes ya limpias


class FamiliaPromocion(_Estricto):
    familia_id: str = Field(min_length=1)
    en_promocion: int = Field(ge=0, le=MAXIMO_ENTERO)


class SolicitudPrediccion(_Estricto):
    tienda_id: int = Field(ge=1)
    fecha: dt.date
    familias: tuple[FamiliaPromocion, ...] = Field(min_length=1)


class VentaFamilia(_Estricto):
    familia_id: str = Field(min_length=1)
    ventas: int = Field(ge=0, le=MAXIMO_ENTERO)


class SolicitudObservacion(_Estricto):
    tienda_id: int = Field(ge=1)
    fecha: dt.date
    # Puede quedar vacía si ningún registro se pudo guardar.
    ventas: tuple[VentaFamilia, ...]


# Calidad


class ObservacionCalidad(BaseModel):
    campo: str
    accion: Accion
    detalle: str


def estado_para(observaciones: list[ObservacionCalidad]) -> EstadoCalidad:
    """Advertencia si hay algún advertir; corregido si solo se reparó; ok si no hay nada."""
    if not observaciones:
        return "ok"
    if any(o.accion == "advertir" for o in observaciones):
        return "advertencia"
    return "corregido"


class Calidad(BaseModel):
    estado: EstadoCalidad
    observaciones: list[ObservacionCalidad]

    @classmethod
    def desde(cls, observaciones: list[ObservacionCalidad]) -> Calidad:
        return cls(estado=estado_para(observaciones), observaciones=list(observaciones))

    @model_validator(mode="after")
    def _estado_coherente(self) -> Calidad:
        esperado = estado_para(self.observaciones)
        if self.estado != esperado:
            raise ValueError(f"estado '{self.estado}' no corresponde a las observaciones (debería ser '{esperado}')")
        return self


# Respuestas


class PrediccionFamilia(BaseModel):
    familia_id: str
    venta_esperada: float = Field(ge=0)
    cantidad_sugerida: int = Field(ge=0)


class RespuestaPrediccion(BaseModel):
    tienda_id: int
    fecha: dt.date
    version_modelo: str
    predicciones: list[PrediccionFamilia]
    calidad: Calidad


class RespuestaObservacion(BaseModel):
    registros_guardados: int = Field(ge=0)
    calidad: Calidad


class Rechazo(BaseModel):
    """Cuerpo de una respuesta 4xx o 503: el motivo en texto."""

    detail: str


class RespuestaModelo(BaseModel):
    nombre: str
    alias: str
    version: str


class RespuestaSalud(BaseModel):
    estado: Literal["ok", "degradado"]
    # Solo cuando el estado es degradado: qué dependencia falla.
    motivo: str | None = None


class RespuestaDisparo(BaseModel):
    id: str


class EstadoReentrenamiento(BaseModel):
    estado: Literal["en_curso", "exitoso", "fallido"]
    # Solo cuando la ejecución terminó.
    promovido: bool | None = None
    version: str | None = None
    motivo: str | None = None
