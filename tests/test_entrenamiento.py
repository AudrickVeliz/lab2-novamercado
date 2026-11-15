import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from novamercado import caracteristicas
from novamercado.entrenamiento import (
    Candidato,
    DatosInsuficientes,
    Tramos,
    decidir,
    entrenar,
    preparar_datos,
)
from novamercado.modelo import Baseline, ModeloEntrenado


def candidato(costo, tipo=Baseline):
    return Candidato(ModeloEntrenado(tipo(), {}), {"costo": costo})


def test_tramos_de_28_dias_sin_solaparse():
    tramos = Tramos.hasta(pd.Timestamp("2026-02-28"))

    assert tramos.como_texto() == {
        "inicio_calibracion": "2026-01-04",
        "inicio_validacion": "2026-02-01",
        "fin_validacion": "2026-02-28",
    }


def test_entrena_ambos_modelos_y_los_valida_fuera_de_muestra(entrenado):
    tramos, baseline, gbm = entrenado

    assert baseline.modelo.tipo == "baseline" and gbm.modelo.tipo == "gradient_boosting"
    for c in (baseline, gbm):
        assert set(c.metricas) == {"costo", "mae", "rmse", "wape", "sesgo"}
        assert c.modelo.linaje["inicio_validacion"] == tramos.como_texto()["inicio_validacion"]


def test_el_gradient_boosting_mejora_al_baseline_con_un_patron_aprendible(entrenado):
    _, baseline, gbm = entrenado

    assert gbm.metricas["costo"] < baseline.metricas["costo"]


def test_con_menos_de_un_ano_de_historia_entrena_igual(entrenado):
    # 180 días sintéticos: venta_hace_364 no tiene ningún dato.
    _, _, gbm = entrenado

    assert gbm.modelo.estimador.sin_datos == ["venta_hace_364"]


def test_el_modelo_entrenado_predice_esperada_y_sugerida(entrenado, historico, catalogos):
    _, _, gbm = entrenado
    variables = caracteristicas.construir(historico, historico.tail(20), catalogos)
    esperada, sugerida = gbm.modelo.predecir(variables)

    assert (esperada >= 0).all()
    assert sugerida.dtype.kind == "i" and (sugerida >= 0).all()


def test_rechaza_si_no_alcanzan_los_datos(historico, catalogos):
    corto = historico[historico["fecha"] < historico["fecha"].min() + pd.Timedelta(days=40)]
    with pytest.raises(DatosInsuficientes):
        entrenar(preparar_datos(corto), catalogos)


def test_las_observaciones_registradas_se_suman_al_historico(historico):
    ultima = historico["fecha"].max()
    nueva = ultima + pd.Timedelta(days=1)
    observaciones = pd.DataFrame({"fecha": [nueva, nueva], "tienda_id": [5, 5],
                                  "familia_id": ["abarrotes", "snacks"], "ventas": [700, 130]})
    promociones = pd.DataFrame({"fecha": [nueva], "tienda_id": [5], "familia_id": ["abarrotes"], "en_promocion": [3]})
    datos = preparar_datos(historico, observaciones, promociones)

    assert len(datos.ventas) == len(historico) + 2
    # Sin promoción conocida (snacks) la fila no entra al aprendizaje.
    assert len(datos.objetivos) == len(historico) + 1
    assert datos.objetivos.iloc[-1][["familia_id", "ventas", "en_promocion"]].tolist() == ["abarrotes", 700, 3]


def test_una_observacion_corrige_al_historico(historico):
    fila = historico.iloc[[0]].copy()
    fila["ventas"] = 1
    datos = preparar_datos(historico, fila[["fecha", "tienda_id", "familia_id", "ventas"]], fila)

    assert len(datos.ventas) == len(historico)
    clave = (datos.ventas["fecha"] == fila["fecha"].iloc[0]) & (datos.ventas["tienda_id"] == fila["tienda_id"].iloc[0])
    clave &= datos.ventas["familia_id"] == fila["familia_id"].iloc[0]
    assert datos.ventas.loc[clave, "ventas"].tolist() == [1]


def test_primer_modelo_promueve_el_mejor():
    from novamercado.modelo import GradientBoosting

    gbm = candidato(90, GradientBoosting)
    assert decidir(candidato(130), gbm, None).promover is gbm
    base = candidato(80)
    assert decidir(base, candidato(90, GradientBoosting), None).promover is base


def test_reemplaza_si_cuesta_menos_que_el_vigente_y_que_el_baseline():
    gbm = candidato(18210)
    decision = decidir(candidato(25000), gbm, 19940)

    assert decision.promover is gbm
    assert decision.motivo == "Costo en validación 18 210 vs 19 940 del vigente"


@pytest.mark.parametrize(("baseline", "vigente", "motivo"), [(17000, 19940, "baseline"), (25000, 18000, "vigente")])
def test_no_reemplaza_si_no_supera_al_baseline_o_al_vigente(baseline, vigente, motivo):
    decision = decidir(candidato(baseline), candidato(18210), vigente)

    assert decision.promover is None
    assert motivo in decision.motivo


DATOS = Path(__file__).resolve().parents[1] / "data" / "publicados"


@pytest.mark.skipif(not (DATOS / "historico_ventas.csv").is_file(), reason="sin los datos publicados")
def test_con_los_datos_publicados_el_ml_cuesta_menos_que_el_baseline():
    from novamercado.catalogos import cargar_catalogos, cargar_historico

    catalogos = cargar_catalogos(DATOS)
    tramos, baseline, gbm = entrenar(preparar_datos(cargar_historico(catalogos, DATOS)), catalogos)

    assert tramos.fin_validacion.date() == dt.date(2026, 2, 28)
    assert gbm.metricas["costo"] < baseline.metricas["costo"]
    assert gbm.metricas["wape"] < baseline.metricas["wape"]
    assert np.isfinite(list(gbm.modelo.factores.values())).all()
