"""Registro en MLflow sin servidor: SQLite en una carpeta temporal."""

import mlflow
import pandas as pd
import pytest
from mlflow.tracking import MlflowClient

from novamercado import caracteristicas
from novamercado.entrenamiento import DatosInsuficientes, preparar_datos
from novamercado.registro_modelos import (
    ALIAS,
    EXPERIMENTO,
    NOMBRE_MODELO,
    cargar_version,
    huella,
    reentrenar,
    version_vigente,
)

LINAJE = {"huella_historico_ventas": "abc123", "huella_codigo": "def456"}


def test_sin_modelos_no_hay_vigente(mlflow_local):
    assert version_vigente() is None


def test_ciclo_de_reentrenamiento(mlflow_local, historico, catalogos):
    datos = preparar_datos(historico)
    cliente = MlflowClient()

    # Primer modelo: se promueve el mejor (el gradient boosting con ventas sintéticas).
    primero = reentrenar(datos, catalogos, LINAJE)
    assert (primero.promovido, primero.version) == (True, "1")
    assert primero.motivo.startswith("Primer modelo.")
    assert version_vigente() == "1"
    assert cliente.get_model_version(NOMBRE_MODELO, "1").tags["promovido"] == "true"

    # Mismos datos: el candidato cuesta lo mismo que el vigente y no lo reemplaza.
    segundo = reentrenar(datos, catalogos, LINAJE)
    assert (segundo.promovido, segundo.version) == (False, "1")
    assert segundo.motivo.startswith("No supera al vigente")
    assert version_vigente() == "1"
    assert cliente.get_model_version(NOMBRE_MODELO, "2").tags["promovido"] == "false"

    # Un reentrenamiento que falla no toca al vigente.
    corto = historico[historico["fecha"] < historico["fecha"].min() + pd.Timedelta(days=40)]
    with pytest.raises(DatosInsuficientes):
        reentrenar(preparar_datos(corto), catalogos, LINAJE)
    assert version_vigente() == "1"


def test_el_run_guarda_el_linaje(mlflow_local, historico, catalogos):
    resultado = reentrenar(preparar_datos(historico), catalogos, LINAJE)
    cliente = MlflowClient()
    padre = cliente.get_run(resultado.run_id)

    assert padre.data.params["huella_codigo"] == "def456"
    assert padre.data.params["inicio_validacion"] and padre.data.params["fin_validacion"]
    assert padre.data.tags["motivo"] == resultado.motivo
    assert {a.path for a in cliente.list_artifacts(resultado.run_id, "datos")} == {
        "datos/objetivos.parquet",
        "datos/ventas.parquet",
    }
    assert [i.dataset.name for i in padre.inputs.dataset_inputs] == ["objetivos"]

    experimento = cliente.get_experiment_by_name(EXPERIMENTO)
    hijos = cliente.search_runs(
        [experimento.experiment_id], filter_string=f"tags.mlflow.parentRunId = '{resultado.run_id}'"
    )
    assert {h.data.params["tipo"] for h in hijos} == {"baseline", "gradient_boosting"}
    for hijo in hijos:
        assert {"costo", "mae", "rmse", "wape", "sesgo"} <= set(hijo.data.metrics)
        assert "factor_lacteos" in hijo.data.params


def test_el_modelo_registrado_predice_igual_que_el_entrenado(mlflow_local, historico, catalogos, entrenado):
    reentrenar(preparar_datos(historico), catalogos, LINAJE)
    variables = caracteristicas.construir(historico, historico.tail(12), catalogos)
    cargado = cargar_version(version_vigente())

    _, _, gbm = entrenado
    assert cargado.predecir(variables)[1].tolist() == gbm.modelo.predecir(variables)[1].tolist()
    pyfunc = mlflow.pyfunc.load_model(f"models:/{NOMBRE_MODELO}@{ALIAS}").predict(variables)
    assert list(pyfunc.columns) == ["venta_esperada", "cantidad_sugerida"]


def test_huella_es_estable_y_detecta_cambios(historico):
    copia = historico.copy()

    assert huella(historico) == huella(copia)
    copia.loc[0, "ventas"] += 1
    assert huella(historico) != huella(copia)
    assert huella(pd.DataFrame()) == huella(pd.DataFrame())
