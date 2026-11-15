import numpy as np
import pytest

from novamercado.negocio import (
    FACTOR_NEUTRO,
    calibrar_factores,
    cantidad_sugerida,
    costo,
    cuantil_objetivo,
    metricas,
)


def test_costo_sigue_la_formula_del_enunciado(catalogos):
    # lacteos: faltante 1.0, sobrante 1.2
    real = np.array([100.0, 100.0, 100.0])
    sugerida = np.array([90, 100, 110])
    familias = np.array(["lacteos"] * 3)

    assert costo(real, sugerida, familias, catalogos).tolist() == pytest.approx([10.0, 0.0, 12.0])


def test_cuantil_objetivo(catalogos):
    cuantiles = cuantil_objetivo(catalogos)

    assert cuantiles["abarrotes"] == pytest.approx(1.0 / 1.2)
    assert cuantiles["frutas_verduras"] == pytest.approx(1.0 / 3.0)


def test_el_factor_calibrado_minimiza_el_costo(catalogos):
    azar = np.random.default_rng(1)
    esperada = azar.uniform(50, 500, 2000)
    real = esperada * azar.lognormal(0, 0.3, 2000)
    familias = np.array(["frutas_verduras"] * 2000)
    factor = calibrar_factores(real, esperada, familias, catalogos)["frutas_verduras"]

    def costo_con(f):
        return costo(real, esperada * f, familias, catalogos).sum()

    candidatos = np.linspace(0.5, 1.5, 201)
    mejor = candidatos[np.argmin([costo_con(f) for f in candidatos])]
    assert factor == pytest.approx(mejor, abs=0.01)
    assert costo_con(factor) <= costo_con(1.0)


def test_sobrar_barato_sube_el_factor_y_sobrar_caro_lo_baja(catalogos):
    azar = np.random.default_rng(2)
    esperada = np.tile(azar.uniform(50, 500, 1000), 2)
    real = esperada * azar.lognormal(0, 0.3, 2000)
    familias = np.array(["abarrotes"] * 1000 + ["frutas_verduras"] * 1000)
    factores = calibrar_factores(real, esperada, familias, catalogos)

    assert factores["abarrotes"] > 1 > factores["frutas_verduras"]


def test_familia_sin_datos_usa_el_factor_neutro(catalogos):
    factores = calibrar_factores(np.array([10.0]), np.array([10.0]), np.array(["lacteos"]), catalogos)

    assert factores["snacks"] == FACTOR_NEUTRO


def test_pronosticos_en_cero_no_afectan_la_calibracion(catalogos):
    real = np.array([10.0, 10.0, 7.0])
    esperada = np.array([0.0, 10.0, 10.0])
    factores = calibrar_factores(real, esperada, np.array(["lacteos"] * 3), catalogos)

    assert np.isfinite(factores["lacteos"])


def test_cantidad_sugerida_es_entera_y_no_negativa():
    sugerida = cantidad_sugerida(np.array([10.4, 0.0, 3.3]), np.array(["a", "b", "c"]), {"a": 1.5, "b": 2.0, "c": -1.0})

    assert sugerida.tolist() == [16, 0, 0]
    assert sugerida.dtype.kind == "i"


def test_metricas(catalogos):
    real = np.array([100.0, 200.0])
    esperada = np.array([110.0, 180.0])
    resultado = metricas(real, esperada, np.array([110, 180]), np.array(["lacteos", "lacteos"]), catalogos)

    assert resultado["mae"] == pytest.approx(15.0)
    assert resultado["wape"] == pytest.approx(30 / 300)
    assert resultado["sesgo"] == pytest.approx(-10 / 300)
    assert resultado["costo"] == pytest.approx(1.2 * 10 + 1.0 * 20)
