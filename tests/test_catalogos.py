from pathlib import Path

import pytest

from novamercado.catalogos import (
    CARPETA_PREDETERMINADA,
    VARIABLE_CARPETA,
    CatalogoInvalido,
    cargar_catalogos,
    carpeta_datos,
)

VALIDOS = {
    "tiendas.csv": (
        "tienda_id,nombre,ciudad,departamento,tipo,fecha_apertura\n"
        "2,NovaMercado Mixco,Mixco,Guatemala,supermercado,2019-01-01\n"
        "1,NovaMercado Zona 10,Guatemala,Guatemala,hipermercado,2019-01-01\n"
    ),
    "familias.csv": "familia_id,nombre\nlacteos,Lácteos\nabarrotes,Abarrotes\n",
    "costos.csv": (
        "familia_id,costo_faltante,costo_sobrante\n"
        "abarrotes,1.0,0.2\n"
        "lacteos,1.0,1.2\n"
    ),
    "feriados.csv": (
        "fecha,nombre,tipo,ambito\n"
        "2024-05-01,Día del Trabajo,feriado,nacional\n"
        "2024-03-28,Jueves Santo,feriado,nacional\n"
    ),
}


def escribir(carpeta: Path, **reemplazos: str) -> Path:
    """Escribe los catálogos válidos; cada argumento reemplaza un archivo (None lo omite)."""
    archivos = {**VALIDOS, **{f"{k}.csv": v for k, v in reemplazos.items()}}
    for nombre, contenido in archivos.items():
        if contenido is not None:
            (carpeta / nombre).write_text(contenido, encoding="utf-8")
    return carpeta


def test_carga_catalogos_validos(tmp_path):
    catalogos = cargar_catalogos(escribir(tmp_path))

    assert catalogos.ids_tiendas == {1, 2}
    assert catalogos.ids_familias == {"abarrotes", "lacteos"}
    assert list(catalogos.tiendas.index) == [1, 2]
    assert catalogos.tiendas.loc[1, "ciudad"] == "Guatemala"
    assert catalogos.costos.loc["lacteos", "costo_sobrante"] == 1.2
    assert catalogos.feriados["fecha"].is_monotonic_increasing
    assert str(catalogos.feriados["fecha"].dtype).startswith("datetime64")


def test_acepta_columnas_adicionales_y_espacios(tmp_path):
    familias = "familia_id, nombre ,extra\n lacteos ,Lácteos,x\nabarrotes,Abarrotes,y\n"
    catalogos = cargar_catalogos(escribir(tmp_path, familias=familias))

    assert catalogos.ids_familias == {"abarrotes", "lacteos"}


def test_falla_si_falta_un_archivo(tmp_path):
    with pytest.raises(CatalogoInvalido, match="No se encontró .*feriados.csv"):
        cargar_catalogos(escribir(tmp_path, feriados=None))


def test_falla_si_falta_una_columna(tmp_path):
    with pytest.raises(CatalogoInvalido, match=r"tiendas.csv: faltan las columnas \['fecha_apertura'\]"):
        cargar_catalogos(escribir(tmp_path, tiendas="tienda_id,nombre,ciudad,departamento,tipo\n1,a,b,c,d\n"))


def test_falla_con_valores_vacios(tmp_path):
    familias = "familia_id,nombre\nlacteos,\nabarrotes,Abarrotes\n"
    with pytest.raises(CatalogoInvalido, match=r"familias.csv: hay valores vacíos en las filas \[2\]"):
        cargar_catalogos(escribir(tmp_path, familias=familias))


@pytest.mark.parametrize("tienda_id", ["T01", "1.5", "-1"])
def test_falla_si_tienda_id_no_es_entero(tmp_path, tienda_id):
    tiendas = VALIDOS["tiendas.csv"].replace("\n1,", f"\n{tienda_id},")
    with pytest.raises(CatalogoInvalido, match=r"tienda_id debe ser un entero \(filas \[3\]\)"):
        cargar_catalogos(escribir(tmp_path, tiendas=tiendas))


def test_falla_si_tienda_repetida(tmp_path):
    tiendas = VALIDOS["tiendas.csv"].replace("\n1,", "\n2,")
    with pytest.raises(CatalogoInvalido, match=r"tiendas.csv: tienda_id repetido: \['2'\]"):
        cargar_catalogos(escribir(tmp_path, tiendas=tiendas))


def test_falla_si_familia_repetida(tmp_path):
    familias = "familia_id,nombre\nlacteos,Lácteos\nlacteos,Lácteos 2\n"
    with pytest.raises(CatalogoInvalido, match=r"familias.csv: familia_id repetido: \['lacteos'\]"):
        cargar_catalogos(escribir(tmp_path, familias=familias))


def test_falla_si_una_familia_no_tiene_costo(tmp_path):
    costos = "familia_id,costo_faltante,costo_sobrante\nabarrotes,1.0,0.2\n"
    with pytest.raises(CatalogoInvalido, match=r"faltan los costos de \['lacteos'\]"):
        cargar_catalogos(escribir(tmp_path, costos=costos))


def test_falla_si_hay_costo_de_familia_desconocida(tmp_path):
    costos = VALIDOS["costos.csv"] + "pan,1.0,2.5\n"
    with pytest.raises(CatalogoInvalido, match=r"no están en familias.csv: \['pan'\]"):
        cargar_catalogos(escribir(tmp_path, costos=costos))


@pytest.mark.parametrize("valor", ["-0.5", "uno"])
def test_falla_si_un_costo_no_es_numero_no_negativo(tmp_path, valor):
    costos = VALIDOS["costos.csv"].replace("lacteos,1.0,1.2", f"lacteos,1.0,{valor}")
    with pytest.raises(CatalogoInvalido, match=r"costo_sobrante debe ser un número no negativo \(filas \[3\]\)"):
        cargar_catalogos(escribir(tmp_path, costos=costos))


def test_falla_si_ambos_costos_son_cero(tmp_path):
    costos = VALIDOS["costos.csv"].replace("lacteos,1.0,1.2", "lacteos,0,0")
    with pytest.raises(CatalogoInvalido, match="ambos costos son cero"):
        cargar_catalogos(escribir(tmp_path, costos=costos))


@pytest.mark.parametrize("fecha", ["01/05/2024", "2024-13-01", "2024-05-01T00:00:00"])
def test_falla_si_fecha_de_feriado_tiene_otro_formato(tmp_path, fecha):
    feriados = VALIDOS["feriados.csv"].replace("2024-05-01", fecha)
    with pytest.raises(CatalogoInvalido, match=r"feriados.csv: fecha debe tener el formato AAAA-MM-DD"):
        cargar_catalogos(escribir(tmp_path, feriados=feriados))


def test_carpeta_por_argumento_variable_o_predeterminada(monkeypatch, tmp_path):
    monkeypatch.delenv(VARIABLE_CARPETA, raising=False)
    assert carpeta_datos() == CARPETA_PREDETERMINADA

    monkeypatch.setenv(VARIABLE_CARPETA, str(tmp_path))
    assert carpeta_datos() == tmp_path
    assert carpeta_datos("otra") == Path("otra")


def test_lee_la_carpeta_de_la_variable_de_entorno(monkeypatch, tmp_path):
    monkeypatch.setenv(VARIABLE_CARPETA, str(escribir(tmp_path)))
    assert cargar_catalogos().ids_tiendas == {1, 2}


REALES = Path(__file__).resolve().parents[1] / CARPETA_PREDETERMINADA


@pytest.mark.skipif(not (REALES / "tiendas.csv").is_file(), reason="sin los datos publicados")
def test_los_catalogos_publicados_son_validos():
    catalogos = cargar_catalogos(REALES)

    assert catalogos.ids_tiendas == set(range(1, 11))
    assert len(catalogos.ids_familias) == 12
    assert set(catalogos.costos.index) == catalogos.ids_familias
