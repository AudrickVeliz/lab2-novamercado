import copy
import datetime as dt
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from novamercado.contrato import Calidad, PrediccionFamilia, RespuestaPrediccion
from novamercado.limpieza import limpiar_observacion, limpiar_prediccion
from novamercado.persistencia import (
    VARIABLE_URL,
    BaseDeDatosNoConfigurada,
    correcciones,
    leer_observaciones,
    leer_promociones,
    leer_reentrenamiento,
    reentrenamientos,
    registrar_reentrenamiento,
    crear_esquema,
    crear_motor,
    metadata,
    observaciones,
    observaciones_historial,
    predicciones,
    registrar_observacion,
    registrar_prediccion,
    registrar_rechazo,
    solicitudes,
)

URL_PRUEBAS = os.environ.get("NOVAMERCADO_BD_PRUEBAS_URL")



@pytest.fixture
def motor():
    if not URL_PRUEBAS:
        pytest.skip("sin NOVAMERCADO_BD_PRUEBAS_URL")
    motor = crear_motor(URL_PRUEBAS)
    metadata.drop_all(motor)
    crear_esquema(motor)
    yield motor
    motor.dispose()


def filas(motor, tabla, *orden):
    with motor.connect() as conexion:
        return [dict(f._mapping) for f in conexion.execute(select(tabla).order_by(*orden))]


def contar(motor, tabla):
    with motor.connect() as conexion:
        return conexion.execute(select(func.count()).select_from(tabla)).scalar_one()


def vigentes(motor):
    return {f["familia_id"]: f["ventas"] for f in filas(motor, observaciones, observaciones.c.familia_id)}


def guardar(motor, cuerpo, referencia):
    return registrar_observacion(motor, cuerpo, limpiar_observacion(copy.deepcopy(cuerpo), referencia))


def test_crear_motor_sin_url_falla(monkeypatch):
    monkeypatch.delenv(VARIABLE_URL, raising=False)
    with pytest.raises(BaseDeDatosNoConfigurada, match=VARIABLE_URL):
        crear_motor()


def test_crear_esquema_no_borra_lo_existente(motor, observacion, referencia):
    guardar(motor, observacion, referencia)
    crear_esquema(motor)

    assert contar(motor, observaciones) == 4


def test_los_datos_sobreviven_a_una_reconexion(motor, observacion, referencia):
    guardar(motor, observacion, referencia)
    motor.dispose()

    assert vigentes(crear_motor(URL_PRUEBAS))["abarrotes"] == 994


def test_registra_un_rechazo_con_su_cuerpo_crudo(motor):
    cuerpo = {"tienda_id": "T99", "fecha": "2025-11-17", "familias": []}
    registrar_rechazo(motor, "prediccion", cuerpo, "La tienda 99 no existe")

    [fila] = filas(motor, solicitudes, solicitudes.c.id)
    assert fila["endpoint"] == "prediccion"
    assert fila["estado"] == "rechazada"
    assert fila["motivo_rechazo"] == "La tienda 99 no existe"
    assert fila["cuerpo"] == cuerpo
    assert fila["tienda_id"] is None


def test_registra_un_cuerpo_que_no_es_objeto(motor):
    registrar_rechazo(motor, "observaciones", "esto no es JSON", "El cuerpo debe ser un objeto JSON")

    assert filas(motor, solicitudes, solicitudes.c.id)[0]["cuerpo"] == "esto no es JSON"


def test_registra_la_prediccion_con_su_version_y_correcciones(motor, prediccion, referencia):
    prediccion["tienda_id"] = "T05"
    prediccion["cajero"] = "x"
    resultado = limpiar_prediccion(copy.deepcopy(prediccion), referencia)
    respuesta = RespuestaPrediccion(
        tienda_id=5,
        fecha=dt.date(2025, 11, 17),
        version_modelo="3",
        predicciones=[
            PrediccionFamilia(familia_id=f.familia_id, venta_esperada=10.5, cantidad_sugerida=12)
            for f in resultado.solicitud.familias
        ],
        calidad=resultado.calidad,
    )
    solicitud_id = registrar_prediccion(motor, prediccion, resultado, respuesta, "novamercado-ventas")

    [solicitud] = filas(motor, solicitudes, solicitudes.c.id)
    assert solicitud["id"] == solicitud_id
    assert solicitud["estado"] == "corregido"
    assert solicitud["cuerpo"] == prediccion
    assert solicitud["campos_ignorados"] == ["cajero"]
    assert (solicitud["tienda_id"], solicitud["fecha"]) == (5, dt.date(2025, 11, 17))

    [correccion] = filas(motor, correcciones, correcciones.c.id)
    assert (correccion["campo"], correccion["accion"]) == ("tienda_id", "reparar")

    guardadas = filas(motor, predicciones, predicciones.c.familia_id)
    assert len(guardadas) == 4
    assert {g["version_modelo"] for g in guardadas} == {"3"}
    assert {g["modelo_nombre"] for g in guardadas} == {"novamercado-ventas"}
    assert {g["familia_id"]: g["en_promocion"] for g in guardadas}["snacks"] == 9


def test_una_tienda_puede_pedir_dos_veces_la_misma_fecha(motor, prediccion, referencia):
    resultado = limpiar_prediccion(prediccion, referencia)
    respuesta = RespuestaPrediccion(
        tienda_id=5, fecha=dt.date(2025, 11, 17), version_modelo="1",
        predicciones=[PrediccionFamilia(familia_id="abarrotes", venta_esperada=1.0, cantidad_sugerida=1)],
        calidad=Calidad.desde([]),
    )
    registrar_prediccion(motor, prediccion, resultado, respuesta, "m")
    registrar_prediccion(motor, prediccion, resultado, respuesta, "m")

    assert contar(motor, solicitudes) == 2
    assert contar(motor, predicciones) == 2


def test_observacion_nueva_cuenta_cada_registro(motor, observacion, referencia):
    assert guardar(motor, observacion, referencia) == 4
    assert vigentes(motor) == {"abarrotes": 994, "frutas_verduras": 310, "lacteos": 0, "snacks": 120}


def test_e09_reenvio_identico_no_guarda_nada(motor, observacion, referencia):
    guardar(motor, observacion, referencia)

    assert guardar(motor, observacion, referencia) == 0
    assert contar(motor, observaciones) == 4
    assert contar(motor, observaciones_historial) == 0
    # El reenvío sí queda registrado como solicitud.
    assert contar(motor, solicitudes) == 2


def test_e09_reenvio_reparado_que_da_lo_mismo_no_guarda_nada(motor, observacion, referencia):
    guardar(motor, observacion, referencia)
    observacion["ventas"][0]["ventas"] = "994"
    observacion["tienda_id"] = "T05"

    assert guardar(motor, observacion, referencia) == 0


def test_e09_correccion_actualiza_y_guarda_el_historial(motor, observacion, referencia):
    primera = guardar(motor, observacion, referencia)
    observacion["ventas"][1]["ventas"] = 305

    assert (primera, guardar(motor, observacion, referencia)) == (4, 1)
    assert vigentes(motor)["frutas_verduras"] == 305
    [cambio] = filas(motor, observaciones_historial, observaciones_historial.c.id)
    assert (cambio["familia_id"], cambio["ventas_anterior"], cambio["ventas_nueva"]) == ("frutas_verduras", 310, 305)


def test_observacion_parcial_agrega_sin_tocar_lo_demas(motor, observacion, referencia):
    completa = copy.deepcopy(observacion)
    observacion["ventas"] = observacion["ventas"][:2]
    guardar(motor, observacion, referencia)

    assert guardar(motor, completa, referencia) == 2
    assert len(vigentes(motor)) == 4


def test_registros_no_guardados_por_la_limpieza_no_cuentan(motor, observacion, referencia):
    observacion["ventas"][0]["ventas"] = -4

    assert guardar(motor, observacion, referencia) == 3
    assert "abarrotes" not in vigentes(motor)
    [correccion] = filas(motor, correcciones, correcciones.c.id)
    assert correccion["accion"] == "advertir"


def test_las_observaciones_de_otra_fecha_son_registros_distintos(motor, observacion, referencia):
    guardar(motor, observacion, referencia)
    observacion["fecha"] = "2025-11-18"

    assert guardar(motor, observacion, referencia) == 4
    assert contar(motor, observaciones) == 8


def test_e09_dos_envios_simultaneos_no_duplican(motor, observacion, referencia):
    with ThreadPoolExecutor(max_workers=4) as hilos:
        guardados = list(hilos.map(lambda _: guardar(motor, observacion, referencia), range(4)))

    assert sum(guardados) == 4
    assert contar(motor, observaciones) == 4


def test_lee_las_observaciones_con_filtros(motor, observacion, referencia):
    guardar(motor, observacion, referencia)
    observacion["fecha"] = "2025-11-18"
    guardar(motor, observacion, referencia)

    todas = leer_observaciones(motor)
    assert len(todas) == 8 and list(todas.columns) == ["fecha", "tienda_id", "familia_id", "ventas"]
    antes = leer_observaciones(motor, tienda_id=5, antes_de=dt.date(2025, 11, 18))
    assert set(antes["fecha"].dt.date) == {dt.date(2025, 11, 17)}
    assert leer_observaciones(motor, tienda_id=1).empty


def test_lee_la_promocion_de_la_ultima_prediccion(motor, prediccion, referencia):
    for promocion in (2, 7):
        prediccion["familias"][0]["en_promocion"] = promocion
        resultado = limpiar_prediccion(copy.deepcopy(prediccion), referencia)
        respuesta = RespuestaPrediccion(
            tienda_id=5, fecha=dt.date(2025, 11, 17), version_modelo="1",
            predicciones=[PrediccionFamilia(familia_id=f.familia_id, venta_esperada=1.0, cantidad_sugerida=1)
                          for f in resultado.solicitud.familias],
            calidad=resultado.calidad,
        )
        registrar_prediccion(motor, prediccion, resultado, respuesta, "m")

    promociones = leer_promociones(motor)
    assert len(promociones) == 4
    assert promociones.set_index("familia_id").loc["abarrotes", "en_promocion"] == 7


def test_registra_y_actualiza_el_resultado_de_un_reentrenamiento(motor):
    assert leer_reentrenamiento(motor, "manual__1") is None

    registrar_reentrenamiento(motor, "manual__1", "fallido", False, None, "falló")
    registrar_reentrenamiento(motor, "manual__1", "exitoso", True, "4", "Costo en validación 18 210 vs 19 940 del vigente")

    fila = leer_reentrenamiento(motor, "manual__1")
    assert (fila["estado"], fila["promovido"], fila["version"]) == ("exitoso", True, "4")
    assert contar(motor, reentrenamientos) == 1


def test_guarda_el_caracter_nul_en_todo_el_texto_de_la_solicitud(motor, prediccion, referencia):
    nul = chr(0)
    prediccion["familias"].append({"familia_id": "pan" + nul, "en_promocion": 1})
    prediccion["campo" + nul] = "x"
    resultado = limpiar_prediccion(copy.deepcopy(prediccion), referencia)
    respuesta = RespuestaPrediccion(
        tienda_id=5, fecha=dt.date(2025, 11, 17), version_modelo="1",
        predicciones=[PrediccionFamilia(familia_id="abarrotes", venta_esperada=1.0, cantidad_sugerida=1)],
        calidad=resultado.calidad,
    )
    registrar_prediccion(motor, prediccion, resultado, respuesta, "m")
    registrar_rechazo(motor, "prediccion", prediccion, "motivo con" + nul)

    assert contar(motor, solicitudes) == 2
    assert all(nul not in c["detalle"] for c in filas(motor, correcciones, correcciones.c.id))
