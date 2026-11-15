import pandas as pd
import pytest

from novamercado.caracteristicas import VARIABLES, construir


def objetivo(fecha, tienda=5, familia="abarrotes", promocion=0):
    return pd.DataFrame(
        {"fecha": [pd.Timestamp(fecha)], "tienda_id": [tienda], "familia_id": [familia], "en_promocion": [promocion]}
    )


def serie(inicio, valores, tienda=5, familia="abarrotes"):
    fechas = pd.date_range(inicio, periods=len(valores), freq="D")
    return pd.DataFrame({"fecha": fechas, "tienda_id": tienda, "familia_id": familia, "ventas": valores})


def test_tiene_las_variables_en_orden_y_una_fila_por_objetivo(historico, catalogos):
    variables = construir(historico, historico, catalogos)

    assert list(variables.columns) == VARIABLES
    assert len(variables) == len(historico)


def test_no_usa_la_venta_del_mismo_dia_ni_futuras(historico, catalogos):
    fecha = pd.Timestamp("2025-06-15")
    base = construir(historico, objetivo(fecha), catalogos)
    alterado = historico.copy()
    alterado.loc[alterado["fecha"] >= fecha, "ventas"] = 999_999

    assert construir(alterado, objetivo(fecha), catalogos).equals(base)


def test_valores_de_historia(catalogos):
    ventas = serie("2025-06-01", list(range(1, 29)))  # 1..28, del 1 al 28 de junio
    fila = construir(ventas, objetivo("2025-06-29"), catalogos).iloc[0]

    assert fila["venta_ayer"] == 28
    assert fila["ultima_venta"] == 28
    assert fila["dias_sin_dato"] == 1
    assert fila["media_7"] == pytest.approx(sum(range(22, 29)) / 7)
    assert fila["media_28"] == pytest.approx(sum(range(1, 29)) / 28)
    assert fila["venta_hace_7"] == 22
    assert fila["media_mismo_dia_4"] == pytest.approx((22 + 15 + 8 + 1) / 4)
    assert pd.isna(fila["venta_hace_364"])


def test_sin_observaciones_recientes_usa_la_ultima_conocida(catalogos):
    ventas = serie("2025-06-01", [10, 20, 30])
    fila = construir(ventas, objetivo("2025-06-10"), catalogos).iloc[0]

    assert pd.isna(fila["venta_ayer"])
    assert fila["ultima_venta"] == 30
    assert fila["dias_sin_dato"] == 7


def test_sin_ninguna_venta_conocida_la_historia_queda_vacia(catalogos):
    fila = construir(serie("2025-06-01", []), objetivo("2025-06-10"), catalogos).iloc[0]

    assert fila[["venta_ayer", "ultima_venta", "media_28"]].isna().all()


def test_calendario_y_promocion(catalogos):
    fila = construir(serie("2025-06-01", [1]), objetivo("2025-11-17", promocion=8), catalogos).iloc[0]

    assert (fila["dia_semana"], fila["dia_mes"], fila["mes"]) == (0, 17, 11)
    assert fila["en_promocion"] == 8


def test_feriado_nacional_y_su_vispera(catalogos):
    dia = construir(serie("2025-06-01", [1]), objetivo("2025-11-01"), catalogos).iloc[0]
    vispera = construir(serie("2025-06-01", [1]), objetivo("2025-10-31"), catalogos).iloc[0]

    assert (dia["feriado"], dia["vispera_feriado"]) == (1, 0)
    assert (vispera["feriado"], vispera["vispera_feriado"]) == (0, 1)


def test_feriado_local_solo_aplica_a_su_ciudad(catalogos):
    xela = construir(serie("2025-06-01", [1], tienda=5), objetivo("2025-09-15", tienda=5), catalogos).iloc[0]
    capital = construir(serie("2025-06-01", [1], tienda=1), objetivo("2025-09-15", tienda=1), catalogos).iloc[0]

    assert xela["feriado"] == 1
    assert capital["feriado"] == 0


def test_fecha_de_pago(catalogos):
    fila = construir(serie("2025-06-01", [1]), objetivo("2025-07-15"), catalogos).iloc[0]

    assert fila["pago"] == 1 and fila["feriado"] == 0


def test_dias_desde_apertura_y_tipo_de_tienda(catalogos):
    fila = construir(serie("2025-03-15", [1], tienda=10), objetivo("2025-03-25", tienda=10), catalogos).iloc[0]

    assert fila["dias_desde_apertura"] == 10
    assert fila["tipo_tienda"] == "express"


def test_las_categorias_son_las_del_catalogo(catalogos):
    variables = construir(serie("2025-06-01", [1]), objetivo("2025-06-02"), catalogos)

    assert list(variables["tienda_id"].cat.categories) == [1, 5, 10]
    assert list(variables["familia_id"].cat.categories) == sorted(catalogos.ids_familias)
