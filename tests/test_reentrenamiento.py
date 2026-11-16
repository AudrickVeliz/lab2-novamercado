"""Reentrenamiento con la base real y MLflow local sobre SQLite."""

import os

import pandas as pd
import pytest

from novamercado import reentrenamiento
from novamercado.catalogos import COLUMNAS
from novamercado.persistencia import crear_esquema, crear_motor, metadata
from novamercado.registro_modelos import version_vigente

from datos_sinteticos import CATALOGOS

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


@pytest.fixture
def publicados(tmp_path, historico):
    carpeta = tmp_path / "publicados"
    carpeta.mkdir()
    for nombre, contenido in CATALOGOS.items():
        (carpeta / nombre).write_text(contenido, encoding="utf-8")
    historico[COLUMNAS["historico_ventas.csv"]].to_csv(carpeta / "historico_ventas.csv", index=False, date_format="%Y-%m-%d")
    return carpeta


def test_cargar_une_el_historico_con_la_base_y_arma_el_linaje(motor, publicados, historico):
    _, datos, linaje = reentrenamiento.cargar(publicados, motor)

    assert len(datos.objetivos) == len(historico)
    assert linaje["observaciones_registradas"] == "0"
    assert {"huella_historico_ventas", "huella_costos", "huella_codigo", "huella_observaciones"} <= set(linaje)


def test_el_arranque_entrena_solo_si_no_hay_vigente(motor, publicados, mlflow_local, monkeypatch):
    monkeypatch.setenv("NOVAMERCADO_DATOS", str(publicados))
    monkeypatch.setenv("NOVAMERCADO_BD_URL", URL_PRUEBAS)

    primero = reentrenamiento.inicial(espera_maxima=0)
    assert primero is not None and primero.promovido
    assert version_vigente() == "1"

    # Al volver a levantarse conserva lo que tiene: no repite el trabajo.
    assert reentrenamiento.inicial(espera_maxima=0) is None
    assert version_vigente() == "1"


def test_el_arranque_falla_si_mlflow_no_responde(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "1")

    with pytest.raises(Exception):
        reentrenamiento.inicial(espera_maxima=0)


def test_las_observaciones_con_promocion_conocida_entran_al_aprendizaje(motor, publicados, historico):
    from novamercado.persistencia import observaciones, predicciones, solicitudes

    nueva = historico["fecha"].max() + pd.Timedelta(days=1)
    with motor.begin() as conexion:
        sid = conexion.execute(
            solicitudes.insert().values(endpoint="observaciones", cuerpo={}, estado="ok").returning(solicitudes.c.id)
        ).scalar_one()
        conexion.execute(observaciones.insert().values(tienda_id=5, fecha=nueva, familia_id="abarrotes", ventas=650, solicitud_id=sid))
        conexion.execute(predicciones.insert().values(
            solicitud_id=sid, tienda_id=5, fecha=nueva, familia_id="abarrotes", en_promocion=2,
            venta_esperada=600.0, cantidad_sugerida=640, modelo_nombre="m", version_modelo="1",
        ))

    _, datos, linaje = reentrenamiento.cargar(publicados, motor)
    assert linaje["observaciones_registradas"] == "1"
    assert datos.objetivos["fecha"].max() == nueva


def test_ejecutar_y_registrar_deja_el_resultado_exitoso(motor, publicados, mlflow_local):
    from novamercado.persistencia import leer_reentrenamiento

    resultado = reentrenamiento.ejecutar_y_registrar("manual__1", publicados, motor)

    fila = leer_reentrenamiento(motor, "manual__1")
    assert (fila["estado"], fila["promovido"], fila["version"]) == ("exitoso", resultado.promovido, resultado.version)
    assert fila["motivo"] == resultado.motivo


def test_un_fallo_queda_registrado_y_no_toca_al_vigente(motor, publicados, mlflow_local):
    from novamercado.persistencia import leer_reentrenamiento

    reentrenamiento.ejecutar_y_registrar("manual__1", publicados, motor)
    (publicados / "costos.csv").write_text("familia_id,costo_faltante\n", encoding="utf-8")

    with pytest.raises(Exception):
        reentrenamiento.ejecutar_y_registrar("manual__2", publicados, motor)

    fila = leer_reentrenamiento(motor, "manual__2")
    assert (fila["estado"], fila["promovido"], fila["version"]) == ("fallido", False, "1")
    assert "CatalogoInvalido" in fila["motivo"] and "no cambió" in fila["motivo"]
    assert version_vigente() == "1"
