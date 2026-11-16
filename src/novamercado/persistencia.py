"""Registro de la operación en el PostgreSQL del producto (ver D-004).

Cada solicitud queda guardada con su cuerpo crudo y su resultado, aceptada o
rechazada. Las observaciones de ventas se guardan de forma idempotente: un
reenvío idéntico no cambia nada y una corrección queda en el historial.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any, Literal

import pandas as pd
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Select,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as insert_pg
from sqlalchemy.engine import Connection

from novamercado.contrato import (
    ObservacionCalidad,
    RespuestaPrediccion,
    SolicitudObservacion,
    SolicitudPrediccion,
)
from novamercado.limpieza import Resultado

VARIABLE_URL = "NOVAMERCADO_BD_URL"

Endpoint = Literal["prediccion", "observaciones"]
# rechazada: 422 por los datos. no_atendida: 503 (sin modelo o el modelo falló).
EstadoSinAtender = Literal["rechazada", "no_atendida"]

metadata = MetaData()

solicitudes = Table(
    "solicitudes",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("endpoint", Text, nullable=False),
    # Reloj del servidor solo para auditoría; nunca decide si una fecha es válida.
    Column("recibida_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("cuerpo", JSONB, nullable=False),
    Column("estado", Text, nullable=False),
    Column("motivo_rechazo", Text),
    Column("tienda_id", Integer),
    Column("fecha", Date),
    Column("campos_ignorados", JSONB, nullable=False, server_default="[]"),
)

correcciones = Table(
    "correcciones",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("solicitud_id", BigInteger, ForeignKey("solicitudes.id"), nullable=False, index=True),
    Column("campo", Text, nullable=False),
    Column("accion", Text, nullable=False),
    Column("detalle", Text, nullable=False),
)

predicciones = Table(
    "predicciones",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("solicitud_id", BigInteger, ForeignKey("solicitudes.id"), nullable=False, index=True),
    Column("tienda_id", Integer, nullable=False),
    Column("fecha", Date, nullable=False),
    Column("familia_id", Text, nullable=False),
    Column("en_promocion", Integer, nullable=False),
    Column("venta_esperada", Float, nullable=False),
    Column("cantidad_sugerida", Integer, nullable=False),
    Column("modelo_nombre", Text, nullable=False),
    Column("version_modelo", Text, nullable=False),
    Index("ix_predicciones_tienda_fecha", "tienda_id", "fecha"),
)

observaciones = Table(
    "observaciones",
    metadata,
    Column("tienda_id", Integer, primary_key=True),
    Column("fecha", Date, primary_key=True),
    Column("familia_id", Text, primary_key=True),
    Column("ventas", Integer, nullable=False),
    Column("solicitud_id", BigInteger, ForeignKey("solicitudes.id"), nullable=False),
    Column("actualizada_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

observaciones_historial = Table(
    "observaciones_historial",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("tienda_id", Integer, nullable=False),
    Column("fecha", Date, nullable=False),
    Column("familia_id", Text, nullable=False),
    Column("ventas_anterior", Integer, nullable=False),
    Column("ventas_nueva", Integer, nullable=False),
    Column("solicitud_id", BigInteger, ForeignKey("solicitudes.id"), nullable=False),
    Column("registrada_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Resultado de cada ejecución del DAG de reentrenamiento (D-011). Mientras corre no hay fila:
# el estado en curso lo informa Airflow.
reentrenamientos = Table(
    "reentrenamientos",
    metadata,
    Column("id", Text, primary_key=True),  # dag_run_id de Airflow
    Column("estado", Text, nullable=False),  # exitoso o fallido
    Column("promovido", Boolean, nullable=False),
    Column("version", Text),  # vigente al terminar
    Column("motivo", Text, nullable=False),
    Column("terminado_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

EstadoReentrenamiento = Literal["exitoso", "fallido"]


class BaseDeDatosNoConfigurada(RuntimeError):
    """Falta la URL de conexión a la base del producto."""


def crear_motor(url: str | None = None) -> Engine:
    url = url or os.environ.get(VARIABLE_URL)
    if not url:
        raise BaseDeDatosNoConfigurada(f"Defina {VARIABLE_URL} (postgresql+psycopg://usuario:clave@host/base)")
    # pool_pre_ping descarta conexiones que murieron mientras la base estuvo caída;
    # connect_timeout evita que /health quede esperando a una base que no responde.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def crear_esquema(motor: Engine) -> None:
    """Crea las tablas que falten; no modifica las existentes ni sus datos."""
    metadata.create_all(motor)


def verificar_conexion(motor: Engine) -> None:
    with motor.connect() as conexion:
        conexion.execute(text("SELECT 1"))


def leer_observaciones(
    motor: Engine, tienda_id: int | None = None, desde: dt.date | None = None, antes_de: dt.date | None = None
) -> pd.DataFrame:
    """Ventas vigentes registradas (fecha, tienda_id, familia_id, ventas); antes_de es exclusivo."""
    consulta = select(observaciones.c.fecha, observaciones.c.tienda_id, observaciones.c.familia_id, observaciones.c.ventas)
    if tienda_id is not None:
        consulta = consulta.where(observaciones.c.tienda_id == tienda_id)
    if desde is not None:
        consulta = consulta.where(observaciones.c.fecha >= desde)
    if antes_de is not None:
        consulta = consulta.where(observaciones.c.fecha < antes_de)
    return _tabla(motor, consulta, ["fecha", "tienda_id", "familia_id", "ventas"])


def leer_promociones(motor: Engine) -> pd.DataFrame:
    """Promoción del día por tienda, fecha y familia, según la última predicción registrada."""
    ultima = (
        select(func.max(predicciones.c.id).label("id"))
        .group_by(predicciones.c.tienda_id, predicciones.c.fecha, predicciones.c.familia_id)
        .subquery()
    )
    consulta = select(
        predicciones.c.fecha, predicciones.c.tienda_id, predicciones.c.familia_id, predicciones.c.en_promocion
    ).join(ultima, predicciones.c.id == ultima.c.id)
    return _tabla(motor, consulta, ["fecha", "tienda_id", "familia_id", "en_promocion"])


def _tabla(motor: Engine, consulta: Select, columnas: list[str]) -> pd.DataFrame:
    with motor.connect() as conexion:
        tabla = pd.DataFrame(conexion.execute(consulta).all(), columns=columnas)
    tabla["fecha"] = pd.to_datetime(tabla["fecha"])
    return tabla


def registrar_reentrenamiento(
    motor: Engine, id: str, estado: EstadoReentrenamiento, promovido: bool, version: str | None, motivo: str
) -> None:
    valores = {"estado": estado, "promovido": promovido, "version": version, "motivo": motivo}
    with motor.begin() as conexion:
        conexion.execute(
            insert_pg(reentrenamientos)
            .values(id=id, **valores)
            .on_conflict_do_update(index_elements=["id"], set_={**valores, "terminado_en": func.now()})
        )


def leer_reentrenamiento(motor: Engine, id: str) -> dict[str, Any] | None:
    with motor.connect() as conexion:
        fila = conexion.execute(select(reentrenamientos).where(reentrenamientos.c.id == id)).first()
    return dict(fila._mapping) if fila else None


def registrar_rechazo(
    motor: Engine, endpoint: Endpoint, cuerpo: Any, motivo: str, estado: EstadoSinAtender = "rechazada"
) -> int:
    with motor.begin() as conexion:
        return _insertar_solicitud(conexion, endpoint, cuerpo, estado, motivo_rechazo=motivo)


def registrar_prediccion(
    motor: Engine,
    cuerpo: Any,
    resultado: Resultado[SolicitudPrediccion],
    respuesta: RespuestaPrediccion,
    modelo_nombre: str,
) -> int:
    solicitud = resultado.solicitud
    promociones = {f.familia_id: f.en_promocion for f in solicitud.familias}
    with motor.begin() as conexion:
        solicitud_id = _insertar_solicitud(
            conexion, "prediccion", cuerpo, resultado.calidad.estado,
            tienda_id=solicitud.tienda_id, fecha=solicitud.fecha, ignorados=resultado.ignorados,
        )
        _insertar_correcciones(conexion, solicitud_id, resultado.observaciones)
        conexion.execute(
            insert(predicciones),
            [
                {
                    "solicitud_id": solicitud_id,
                    "tienda_id": solicitud.tienda_id,
                    "fecha": solicitud.fecha,
                    "familia_id": p.familia_id,
                    "en_promocion": promociones[p.familia_id],
                    "venta_esperada": p.venta_esperada,
                    "cantidad_sugerida": p.cantidad_sugerida,
                    "modelo_nombre": modelo_nombre,
                    "version_modelo": respuesta.version_modelo,
                }
                for p in respuesta.predicciones
            ],
        )
    return solicitud_id


def registrar_observacion(motor: Engine, cuerpo: Any, resultado: Resultado[SolicitudObservacion]) -> int:
    """Guarda las ventas y devuelve cuántos registros son nuevos o cambiaron (E09)."""
    solicitud = resultado.solicitud
    with motor.begin() as conexion:
        solicitud_id = _insertar_solicitud(
            conexion, "observaciones", cuerpo, resultado.calidad.estado,
            tienda_id=solicitud.tienda_id, fecha=solicitud.fecha, ignorados=resultado.ignorados,
        )
        _insertar_correcciones(conexion, solicitud_id, resultado.observaciones)
        return sum(
            _guardar_venta(conexion, solicitud_id, solicitud.tienda_id, solicitud.fecha, v.familia_id, v.ventas)
            for v in solicitud.ventas
        )


def _guardar_venta(
    conexion: Connection, solicitud_id: int, tienda_id: int, fecha: dt.date, familia_id: str, ventas: int
) -> int:
    clave = {"tienda_id": tienda_id, "fecha": fecha, "familia_id": familia_id}
    # Insertar primero evita la carrera de dos envíos simultáneos del mismo registro.
    # RETURNING y no rowcount: con ON CONFLICT DO NOTHING, psycopg reporta rowcount -1.
    insertado = conexion.execute(
        insert_pg(observaciones)
        .values(**clave, ventas=ventas, solicitud_id=solicitud_id)
        .on_conflict_do_nothing()
        .returning(observaciones.c.ventas)
    ).first()
    if insertado is not None:
        return 1

    filtro = [observaciones.c[k] == v for k, v in clave.items()]
    anterior = conexion.execute(select(observaciones.c.ventas).where(*filtro).with_for_update()).scalar_one()
    if anterior == ventas:
        return 0
    conexion.execute(
        update(observaciones)
        .where(*filtro)
        .values(ventas=ventas, solicitud_id=solicitud_id, actualizada_en=func.now())
    )
    conexion.execute(
        insert(observaciones_historial).values(
            **clave, ventas_anterior=anterior, ventas_nueva=ventas, solicitud_id=solicitud_id
        )
    )
    return 1


def _insertar_solicitud(
    conexion: Connection,
    endpoint: Endpoint,
    cuerpo: Any,
    estado: str,
    *,
    motivo_rechazo: str | None = None,
    tienda_id: int | None = None,
    fecha: dt.date | None = None,
    ignorados: list[str] | None = None,
) -> int:
    return conexion.execute(
        insert(solicitudes)
        .values(
            endpoint=endpoint,
            cuerpo=_sin_nulos(cuerpo),
            estado=estado,
            motivo_rechazo=_sin_nulos(motivo_rechazo),
            tienda_id=tienda_id,
            fecha=fecha,
            campos_ignorados=_sin_nulos(ignorados or []),
        )
        .returning(solicitudes.c.id)
    ).scalar_one()


def _insertar_correcciones(conexion: Connection, solicitud_id: int, observaciones_calidad: list[ObservacionCalidad]) -> None:
    if observaciones_calidad:
        conexion.execute(
            insert(correcciones),
            [{"solicitud_id": solicitud_id, **_sin_nulos(o.model_dump())} for o in observaciones_calidad],
        )


def _sin_nulos(valor: Any) -> Any:
    """Reemplaza el carácter NUL, que PostgreSQL no admite en TEXT ni en JSONB, para poder guardar la solicitud."""
    if isinstance(valor, str):
        return valor.replace(chr(0), chr(0xFFFD))
    if isinstance(valor, list):
        return [_sin_nulos(v) for v in valor]
    if isinstance(valor, dict):
        return {_sin_nulos(k): _sin_nulos(v) for k, v in valor.items()}
    return valor


class RegistroPostgres:
    """Registro de la operación que usa la API; las pruebas del contrato lo reemplazan por uno en memoria."""

    def __init__(self, motor: Engine):
        self.motor = motor

    def verificar(self) -> None:
        verificar_conexion(self.motor)

    def rechazo(self, endpoint: Endpoint, cuerpo: Any, motivo: str, estado: EstadoSinAtender = "rechazada") -> int:
        return registrar_rechazo(self.motor, endpoint, cuerpo, motivo, estado)

    def prediccion(
        self,
        cuerpo: Any,
        resultado: Resultado[SolicitudPrediccion],
        respuesta: RespuestaPrediccion,
        modelo_nombre: str,
    ) -> int:
        return registrar_prediccion(self.motor, cuerpo, resultado, respuesta, modelo_nombre)

    def observacion(self, cuerpo: Any, resultado: Resultado[SolicitudObservacion]) -> int:
        return registrar_observacion(self.motor, cuerpo, resultado)

    def reentrenamiento(self, id: str) -> dict[str, Any] | None:
        return leer_reentrenamiento(self.motor, id)
