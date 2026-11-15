import datetime as dt
import json
from pathlib import Path

import pytest

from novamercado.limpieza import (
    SolicitudRechazada,
    interpretar_numero,
    limpiar_observacion,
    limpiar_prediccion,
)

from conftest import FAMILIAS


def acciones(resultado):
    return [(o.campo, o.accion) for o in resultado.observaciones]


def promociones(resultado):
    return {f.familia_id: f.en_promocion for f in resultado.solicitud.familias}


def ventas(resultado):
    return {v.familia_id: v.ventas for v in resultado.solicitud.ventas}


# Solicitud válida


def test_prediccion_valida_queda_ok(prediccion, referencia):
    r = limpiar_prediccion(prediccion, referencia)

    assert r.calidad.estado == "ok"
    assert r.calidad.observaciones == []
    assert r.solicitud.tienda_id == 5
    assert r.solicitud.fecha == dt.date(2025, 11, 17)
    assert promociones(r) == {"abarrotes": 0, "frutas_verduras": 0, "lacteos": 2, "snacks": 9}


def test_observacion_valida_queda_ok(observacion, referencia):
    r = limpiar_observacion(observacion, referencia)

    assert r.calidad.estado == "ok"
    assert ventas(r) == {"abarrotes": 994, "frutas_verduras": 310, "lacteos": 0, "snacks": 120}


@pytest.mark.parametrize("cuerpo", [None, [], "texto", 5])
def test_rechaza_un_cuerpo_que_no_es_objeto(cuerpo, referencia):
    with pytest.raises(SolicitudRechazada, match="objeto JSON"):
        limpiar_prediccion(cuerpo, referencia)


# E01: tienda


@pytest.mark.parametrize("valor", ["5", "T05", "tienda 5", " 5 ", 5.0, "05", "#5"])
def test_e01_repara_tienda_inequivoca(valor, prediccion, referencia):
    prediccion["tienda_id"] = valor
    r = limpiar_prediccion(prediccion, referencia)

    assert r.solicitud.tienda_id == 5
    assert acciones(r) == [("tienda_id", "reparar")]
    assert r.calidad.estado == "corregido"


@pytest.mark.parametrize("valor", ["5-7", "T5.5", "tienda", 5.5, True, None, [5]])
def test_e01_rechaza_tienda_ambigua(valor, prediccion, referencia):
    prediccion["tienda_id"] = valor
    with pytest.raises(SolicitudRechazada, match="no identifica una tienda"):
        limpiar_prediccion(prediccion, referencia)


def test_e01_rechaza_tienda_inexistente(prediccion, referencia):
    prediccion["tienda_id"] = "T99"
    with pytest.raises(SolicitudRechazada, match="La tienda 99 no existe"):
        limpiar_prediccion(prediccion, referencia)


# E02: familia


@pytest.mark.parametrize(
    ("valor", "esperada"),
    [("LÁCTEOS", "lacteos"), ("lacteos ", "lacteos"), ("Frutas y Verduras", "frutas_verduras"),
     ("frutas-verduras", "frutas_verduras"), ("Snacks y dulces", "snacks")],
)
def test_e02_repara_familia_escrita_de_otra_forma(valor, esperada, prediccion, referencia):
    original = next(f for f in prediccion["familias"] if f["familia_id"] == esperada)
    original["familia_id"] = valor
    r = limpiar_prediccion(prediccion, referencia)

    assert esperada in promociones(r)
    assert r.calidad.estado == "corregido"
    [obs] = r.observaciones
    assert obs.accion == "reparar" and obs.campo.endswith(".familia_id")
    assert f"se interpretó como '{esperada}'" in obs.detalle


def test_e02_familia_desconocida_se_omite_con_advertencia(prediccion, referencia):
    prediccion["familias"].append({"familia_id": "ferreteria", "en_promocion": 1})
    r = limpiar_prediccion(prediccion, referencia)

    assert "ferreteria" not in promociones(r)
    assert acciones(r) == [("familias[4].familia_id", "advertir")]
    assert r.calidad.estado == "advertencia"


def test_e02_no_adivina_errores_de_tipeo(prediccion, referencia):
    prediccion["familias"][2]["familia_id"] = "lacteo"
    r = limpiar_prediccion(prediccion, referencia)

    # "lacteo" no se reconoce: se omite y, por E05, lacteos se completa con promoción 0.
    assert promociones(r)["lacteos"] == 0
    assert ("familias[2].familia_id", "advertir") in acciones(r)
    assert ("familias", "advertir") in acciones(r)


# E03: promoción


@pytest.mark.parametrize("valor", ["3", 3.0, " 3 ", "3,0"])
def test_e03_repara_promocion_entera(valor, prediccion, referencia):
    prediccion["familias"][0]["en_promocion"] = valor
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["abarrotes"] == 3
    assert acciones(r) == [("familias[0].en_promocion", "reparar")]


@pytest.mark.parametrize("valor", [-1, 2.5, "dos", "", None, True])
def test_e03_promocion_invalida_asume_cero(valor, prediccion, referencia):
    prediccion["familias"][3]["en_promocion"] = valor
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["snacks"] == 0
    assert acciones(r) == [("familias[3].en_promocion", "advertir")]


def test_e03_promocion_ausente_asume_cero(prediccion, referencia):
    del prediccion["familias"][3]["en_promocion"]
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["snacks"] == 0
    assert acciones(r) == [("familias[3]", "advertir")]


# E04: fecha


@pytest.mark.parametrize(
    "valor",
    ["2025-11-17T00:00:00", "2025-11-17 00:00", "2025-11-17T00:00:00Z", "17/11/2025",
     "17-11-2025", "2025/11/17", " 2025-11-17", "11/17/2025"],
)
def test_e04_repara_fecha_inequivoca(valor, prediccion, referencia):
    prediccion["fecha"] = valor
    r = limpiar_prediccion(prediccion, referencia)

    assert r.solicitud.fecha == dt.date(2025, 11, 17)
    assert acciones(r) == [("fecha", "reparar")]


def test_e04_fecha_ambigua_asume_dia_primero_con_advertencia(prediccion, referencia):
    prediccion["fecha"] = "05/11/2025"
    r = limpiar_prediccion(prediccion, referencia)

    assert r.solicitud.fecha == dt.date(2025, 11, 5)
    assert acciones(r) == [("fecha", "advertir")]


def test_e04_dia_y_mes_iguales_no_es_ambigua(prediccion, referencia):
    prediccion["fecha"] = "11/11/2025"
    r = limpiar_prediccion(prediccion, referencia)

    assert r.solicitud.fecha == dt.date(2025, 11, 11)
    assert acciones(r) == [("fecha", "reparar")]


@pytest.mark.parametrize("valor", ["mañana", "2025-02-30", "31/31/2025", "17/11/25", 20251117, None])
def test_e04_rechaza_fecha_irreconocible(valor, prediccion, referencia):
    prediccion["fecha"] = valor
    with pytest.raises(SolicitudRechazada, match="fecha"):
        limpiar_prediccion(prediccion, referencia)


def test_rechaza_fecha_anterior_a_la_apertura(prediccion, referencia):
    prediccion["tienda_id"] = 10
    prediccion["fecha"] = "2025-03-14"
    with pytest.raises(SolicitudRechazada, match="abrió el 2025-03-15"):
        limpiar_prediccion(prediccion, referencia)


def test_acepta_el_dia_de_apertura(prediccion, referencia):
    prediccion["tienda_id"] = 10
    prediccion["fecha"] = "2025-03-15"
    assert limpiar_prediccion(prediccion, referencia).calidad.estado == "ok"


def test_advierte_si_no_se_conocen_los_feriados(prediccion, referencia):
    prediccion["fecha"] = "2027-01-04"
    r = limpiar_prediccion(prediccion, referencia)

    assert acciones(r) == [("fecha", "advertir")]
    assert "2026-12-25" in r.observaciones[0].detalle


def test_no_usa_el_reloj_del_sistema(prediccion, referencia):
    # Una fecha lejana en el pasado o en el futuro solo depende de los catálogos.
    prediccion["fecha"] = "2019-01-01"
    assert limpiar_prediccion(prediccion, referencia).calidad.estado == "ok"


# E05: familias faltantes


def test_e05_completa_las_familias_faltantes(prediccion, referencia):
    prediccion["familias"] = prediccion["familias"][:2]
    r = limpiar_prediccion(prediccion, referencia)

    assert set(promociones(r)) == set(FAMILIAS)
    assert promociones(r)["lacteos"] == 0 and promociones(r)["snacks"] == 0
    assert acciones(r) == [("familias", "advertir"), ("familias", "advertir")]


def test_e05_lista_vacia_completa_todas(prediccion, referencia):
    prediccion["familias"] = []
    r = limpiar_prediccion(prediccion, referencia)

    assert set(promociones(r)) == set(FAMILIAS)
    assert r.calidad.estado == "advertencia"


# E06: familia repetida


def test_e06_repetida_con_mismos_valores_se_repara(prediccion, referencia):
    prediccion["familias"].append({"familia_id": "lacteos", "en_promocion": 2})
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["lacteos"] == 2
    assert acciones(r) == [("familias[2], familias[4]", "reparar")]


def test_e06_repetida_con_valores_distintos_usa_la_mayor(prediccion, referencia):
    prediccion["familias"].append({"familia_id": "abarrotes", "en_promocion": 3})
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["abarrotes"] == 3
    assert acciones(r) == [("familias[0], familias[4]", "advertir")]
    assert len(r.solicitud.familias) == len(FAMILIAS)


def test_e06_detecta_repetidas_escritas_de_otra_forma(prediccion, referencia):
    prediccion["familias"].append({"familia_id": "LÁCTEOS", "en_promocion": 5})
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["lacteos"] == 5
    assert r.calidad.estado == "advertencia"


# E07: nombres de campos


@pytest.mark.parametrize("nombre", ["tienda", "Tienda_ID", "id_tienda", "store_id", "tiendaId"])
def test_e07_repara_alias_de_tienda(nombre, prediccion, referencia):
    prediccion[nombre] = prediccion.pop("tienda_id")
    r = limpiar_prediccion(prediccion, referencia)

    assert r.solicitud.tienda_id == 5
    assert acciones(r) == [(nombre, "reparar")]


def test_e07_repara_alias_dentro_de_las_familias(prediccion, referencia):
    prediccion["familias"][0] = {"familia": "abarrotes", "promocion": 4}
    r = limpiar_prediccion(prediccion, referencia)

    assert promociones(r)["abarrotes"] == 4
    assert acciones(r) == [("familias[0].familia", "reparar"), ("familias[0].promocion", "reparar")]


def test_e07_alias_con_el_mismo_valor_no_es_conflicto(prediccion, referencia):
    prediccion["tienda"] = 5
    r = limpiar_prediccion(prediccion, referencia)

    assert r.solicitud.tienda_id == 5
    assert acciones(r) == [("tienda", "reparar")]


def test_e07_rechaza_alias_en_conflicto(prediccion, referencia):
    prediccion["tienda"] = 1
    with pytest.raises(SolicitudRechazada, match="valores distintos"):
        limpiar_prediccion(prediccion, referencia)


@pytest.mark.parametrize("campo", ["tienda_id", "fecha", "familias"])
def test_e07_rechaza_si_falta_un_campo_obligatorio(campo, prediccion, referencia):
    del prediccion[campo]
    with pytest.raises(SolicitudRechazada, match=f"Falta el campo obligatorio '{campo}'"):
        limpiar_prediccion(prediccion, referencia)


def test_campos_desconocidos_se_ignoran_sin_afectar_la_calidad(prediccion, referencia):
    prediccion["cajero"] = "x"
    prediccion["familias"][1]["color"] = "rojo"
    r = limpiar_prediccion(prediccion, referencia)

    assert r.calidad.estado == "ok"
    assert r.ignorados == ["cajero", "familias[1].color"]


def test_items_que_no_son_objetos_se_omiten(prediccion, referencia):
    prediccion["familias"].append("snacks")
    r = limpiar_prediccion(prediccion, referencia)

    assert ("familias[4]", "advertir") in acciones(r)


def test_rechaza_familias_que_no_son_lista(prediccion, referencia):
    prediccion["familias"] = {"abarrotes": 0}
    with pytest.raises(SolicitudRechazada, match="debe ser una lista"):
        limpiar_prediccion(prediccion, referencia)


# E08: ventas negativas


def test_e08_ventas_negativas_no_se_guardan(observacion, referencia):
    observacion["ventas"][1]["ventas"] = -4
    r = limpiar_observacion(observacion, referencia)

    assert "frutas_verduras" not in ventas(r)
    assert len(ventas(r)) == 3
    assert acciones(r) == [("ventas[1].ventas", "advertir")]


# E10: formato de números


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("1,234", 1234), ("812,0", 812), ("1.234", 1234), ("1,234.0", 1234), ("1.234,00", 1234),
     ("1 234", 1234), ("994", 994), (994.0, 994)],
)
def test_e10_repara_numeros_enteros_con_formato(valor, esperado, observacion, referencia):
    observacion["ventas"][0]["ventas"] = valor
    r = limpiar_observacion(observacion, referencia)

    assert ventas(r)["abarrotes"] == esperado
    assert acciones(r) == [("ventas[0].ventas", "reparar")]


@pytest.mark.parametrize("valor", ["12,5", "0,5", "1,23,4", "mil", "", None, True, "1e3"])
def test_e10_no_guarda_numeros_no_enteros_o_ilegibles(valor, observacion, referencia):
    observacion["ventas"][0]["ventas"] = valor
    r = limpiar_observacion(observacion, referencia)

    assert "abarrotes" not in ventas(r)
    assert acciones(r) == [("ventas[0].ventas", "advertir")]


@pytest.mark.parametrize(
    ("texto", "numero"),
    [("1,234", 1234.0), ("812,0", 812.0), ("12,5", 12.5), ("0,500", 0.5), ("2.0", 2.0),
     ("-4", -4.0), ("1.234,5", 1234.5), ("1,234,567", 1234567.0), ("12,34,567", None), ("1,", None), (",5", None)],
)
def test_interpretar_numero(texto, numero):
    assert interpretar_numero(texto) == numero


# Otras reglas de las observaciones


def test_observacion_repetida_identica_en_la_misma_solicitud_se_repara(observacion, referencia):
    observacion["ventas"].append({"familia_id": "snacks", "ventas": "120"})
    r = limpiar_observacion(observacion, referencia)

    assert ventas(r)["snacks"] == 120
    assert ("ventas[3], ventas[4]", "reparar") in acciones(r)


def test_observacion_repetida_con_valores_distintos_no_se_guarda(observacion, referencia):
    observacion["ventas"].append({"familia_id": "snacks", "ventas": 150})
    r = limpiar_observacion(observacion, referencia)

    assert "snacks" not in ventas(r)
    assert acciones(r) == [("ventas[3], ventas[4]", "advertir")]


def test_observacion_parcial_advierte_las_faltantes(observacion, referencia):
    observacion["ventas"] = observacion["ventas"][:3]
    r = limpiar_observacion(observacion, referencia)

    assert len(ventas(r)) == 3
    assert acciones(r) == [("ventas", "advertir")]
    assert "'snacks'" in r.observaciones[0].detalle


def test_observacion_atipica_se_guarda_con_advertencia(observacion, referencia):
    observacion["ventas"][0]["ventas"] = 20_000
    r = limpiar_observacion(observacion, referencia)

    assert ventas(r)["abarrotes"] == 20_000
    assert acciones(r) == [("ventas[0]", "advertir")]


def test_observacion_al_limite_no_es_atipica(observacion, referencia):
    observacion["ventas"][0]["ventas"] = 5000
    assert limpiar_observacion(observacion, referencia).calidad.estado == "ok"


def test_observacion_acepta_alias(observacion, referencia):
    observacion["observaciones"] = observacion.pop("ventas")
    observacion["observaciones"][0] = {"familia": "abarrotes", "unidades": 994}
    r = limpiar_observacion(observacion, referencia)

    assert ventas(r)["abarrotes"] == 994
    assert r.calidad.estado == "corregido"


def test_observacion_sin_registros_validos_queda_vacia(observacion, referencia):
    for item in observacion["ventas"]:
        item["ventas"] = -1
    r = limpiar_observacion(observacion, referencia)

    assert r.solicitud.ventas == ()
    assert r.calidad.estado == "advertencia"


def test_observacion_rechaza_fecha_anterior_a_la_apertura(observacion, referencia):
    observacion["tienda_id"] = 10
    observacion["fecha"] = "2024-12-31"
    with pytest.raises(SolicitudRechazada, match="abrió"):
        limpiar_observacion(observacion, referencia)


# Ejemplos publicados

EJEMPLOS = Path(__file__).resolve().parents[1] / "data" / "publicados" / "ejemplos"

ESPERADO = {
    "prediccion_valida.json": "ok",
    "observacion_valida.json": "ok",
    "E01_tienda_texto.json": "corregido",
    "E02_familia_otra_forma.json": "corregido",
    "E03_promocion_texto.json": "corregido",
    "E04_fecha_formato.json": "corregido",
    "E05_faltan_familias.json": "advertencia",
    "E06_familia_repetida.json": "advertencia",
    "E07_campo_renombrado.json": "corregido",
    "E08_ventas_negativas.json": "advertencia",
    "E09_envio_repetido.json": "ok",
    "E10_numero_formato.json": "corregido",
}


@pytest.mark.skipif(not EJEMPLOS.is_dir(), reason="sin los datos publicados")
@pytest.mark.parametrize("nombre", sorted(ESPERADO))
def test_ejemplos_publicados(nombre):
    from novamercado.catalogos import cargar_catalogos
    from novamercado.limpieza import Referencia

    referencia = Referencia(cargar_catalogos(EJEMPLOS.parent))
    ruta = EJEMPLOS / nombre if (EJEMPLOS / nombre).is_file() else EJEMPLOS / "errores" / nombre
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    es_observacion = "ventas" in crudo
    r = (limpiar_observacion if es_observacion else limpiar_prediccion)(crudo, referencia)

    assert r.calidad.estado == ESPERADO[nombre]
