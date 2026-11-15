import datetime as dt

import pytest
from pydantic import ValidationError

from novamercado.contrato import (
    Calidad,
    ObservacionCalidad,
    PrediccionFamilia,
    RespuestaObservacion,
    RespuestaPrediccion,
    SolicitudPrediccion,
)


def obs(accion):
    return ObservacionCalidad(campo="x", accion=accion, detalle="d")


@pytest.mark.parametrize(
    ("acciones", "estado"),
    [([], "ok"), (["reparar"], "corregido"), (["reparar", "advertir"], "advertencia"), (["advertir"], "advertencia")],
)
def test_estado_se_deriva_de_las_observaciones(acciones, estado):
    assert Calidad.desde([obs(a) for a in acciones]).estado == estado


@pytest.mark.parametrize(
    ("estado", "acciones"),
    [("ok", ["reparar"]), ("corregido", []), ("corregido", ["advertir"]), ("advertencia", ["reparar"])],
)
def test_calidad_rechaza_un_estado_incoherente(estado, acciones):
    with pytest.raises(ValidationError, match="no corresponde"):
        Calidad(estado=estado, observaciones=[obs(a) for a in acciones])


def test_accion_solo_admite_reparar_o_advertir():
    with pytest.raises(ValidationError):
        ObservacionCalidad(campo="x", accion="rechazar", detalle="d")


def test_respuesta_prediccion_serializa_el_contrato():
    respuesta = RespuestaPrediccion(
        tienda_id=5,
        fecha=dt.date(2025, 11, 17),
        version_modelo="3",
        predicciones=[PrediccionFamilia(familia_id="abarrotes", venta_esperada=612.4, cantidad_sugerida=640)],
        calidad=Calidad.desde([]),
    )

    assert respuesta.model_dump(mode="json") == {
        "tienda_id": 5,
        "fecha": "2025-11-17",
        "version_modelo": "3",
        "predicciones": [{"familia_id": "abarrotes", "venta_esperada": 612.4, "cantidad_sugerida": 640}],
        "calidad": {"estado": "ok", "observaciones": []},
    }


def test_cantidad_sugerida_es_entera_y_no_negativa():
    with pytest.raises(ValidationError):
        PrediccionFamilia(familia_id="a", venta_esperada=1.0, cantidad_sugerida=-1)
    with pytest.raises(ValidationError):
        PrediccionFamilia(familia_id="a", venta_esperada=1.0, cantidad_sugerida=2.5)


def test_respuesta_observacion_serializa_el_contrato():
    respuesta = RespuestaObservacion(registros_guardados=12, calidad=Calidad.desde([]))

    assert respuesta.model_dump(mode="json") == {
        "registros_guardados": 12,
        "calidad": {"estado": "ok", "observaciones": []},
    }


def test_la_solicitud_limpia_es_estricta():
    # Los modelos de solicitud describen datos ya limpios: no reparan nada por su cuenta.
    with pytest.raises(ValidationError):
        SolicitudPrediccion(tienda_id="5", fecha=dt.date(2025, 11, 17), familias=())
