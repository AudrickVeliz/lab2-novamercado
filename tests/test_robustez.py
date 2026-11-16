"""Problemas fuera del catálogo: miles de solicitudes deformadas al azar (semilla fija).

La limpieza solo puede devolver una solicitud limpia o rechazarla, y la API solo
puede responder 200 o 422 por culpa de los datos: nunca 500, ni 503 por un dato
que la base no puede guardar.
"""

import copy
import os
import random

import pytest

from novamercado.limpieza import Resultado, SolicitudRechazada, limpiar_observacion, limpiar_prediccion
from test_api import PredictorFalso, cliente

TEXTOS = [
    "", " ", "T05", "tienda 5", "5-7", "abc", "LÁCTEOS", "Frutas y Verduras", "lacteo", "ninguna",
    "١٢", "５", "1,234", "1.234,5", "812,0", "-4", "+3", "--5", "1e5", "NaN", "Infinity", "null", "true",
    "2025-11-17", "17/11/2025", "05/11/2025", "2025-13-45", "0000-00-00", "2025-11-17T25:61:00", "11/17/2025",
    "9" * 40, "x" * 5000, "🚀", chr(0x202E) + "cifra", chr(0), "a" + chr(0) + "b", "'; DROP TABLE solicitudes; --",
]
NUMEROS = [0, 1, -1, 5, 10, 99, 2**31 - 1, 2**31, -(2**31) - 1, 10**30, -(10**30), 1.5, -0.0, 2.0, 1e300, -1e300]


def valor_raro(azar: random.Random, profundidad: int = 0):
    tipo = azar.randrange(7 if profundidad < 3 else 5)
    if tipo == 0:
        return None
    if tipo == 1:
        return azar.choice([True, False])
    if tipo == 2:
        return azar.choice(NUMEROS)
    if tipo in (3, 4):
        return azar.choice(TEXTOS)
    if tipo == 5:
        return [valor_raro(azar, profundidad + 1) for _ in range(azar.randrange(4))]
    return {azar.choice(TEXTOS + ["tienda", "fecha", "familias", "ventas"]): valor_raro(azar, profundidad + 1)
            for _ in range(azar.randrange(4))}


def nombre_raro(azar: random.Random, nombre: str) -> str:
    return azar.choice([nombre.upper(), f" {nombre} ", nombre.replace("_", "-"), "tienda", "familia",
                        "promocion", "unidades", nombre + "x", "", azar.choice(TEXTOS)])


def mutar(azar: random.Random, original: dict):
    """Aplica de 1 a 4 deformaciones al azar sobre una copia de una solicitud válida."""
    objeto = copy.deepcopy(original)
    for _ in range(azar.randint(1, 4)):
        contenedores = _contenedores(objeto)
        padre, clave = azar.choice(contenedores) if contenedores else (None, None)
        accion = azar.randrange(7)
        if padre is None or accion == 0:
            objeto = valor_raro(azar) if azar.random() < 0.1 else objeto
        elif accion in (1, 2):
            padre[clave] = valor_raro(azar)
        elif accion == 3 and isinstance(padre, dict):
            del padre[clave]
        elif accion == 4 and isinstance(padre, dict):
            padre[nombre_raro(azar, str(clave))] = padre.pop(clave)
        elif accion == 5 and isinstance(padre[clave], list) and padre[clave]:
            padre[clave].append(copy.deepcopy(azar.choice(padre[clave])))
        elif accion == 6 and isinstance(padre, dict):
            padre[azar.choice(TEXTOS)] = valor_raro(azar)
    return objeto


def _contenedores(objeto, acumulado=None):
    """(padre, clave) de cada valor dentro del objeto."""
    acumulado = [] if acumulado is None else acumulado
    if isinstance(objeto, dict):
        for clave, valor in objeto.items():
            acumulado.append((objeto, clave))
            _contenedores(valor, acumulado)
    elif isinstance(objeto, list):
        for i, valor in enumerate(objeto):
            acumulado.append((objeto, i))
            _contenedores(valor, acumulado)
    return acumulado


@pytest.mark.parametrize("limpiar", [limpiar_prediccion, limpiar_observacion])
def test_la_limpieza_solo_repara_advierte_o_rechaza(limpiar, prediccion, observacion, referencia):
    azar = random.Random(20261116)
    valido = prediccion if limpiar is limpiar_prediccion else observacion
    for intento in range(3000):
        cuerpo = mutar(azar, valido)
        try:
            resultado = limpiar(copy.deepcopy(cuerpo), referencia)
        except SolicitudRechazada:
            continue
        except Exception as error:  # pragma: no cover - el mensaje ayuda a reproducir
            pytest.fail(f"intento {intento}: {type(error).__name__}: {error} con {cuerpo!r}"[:2000])
        assert isinstance(resultado, Resultado)


def cuerpos_crudos():
    """Cuerpos que ni siquiera son el JSON esperado."""
    return [
        b"", b"{", b"null", b"[]", b'"texto"', b"12", b"\xff\xfe\x00", b'{"tienda_id": NaN}',
        b"[" * 100_000 + b"]" * 100_000,
        b'{"a":' * 5000 + b"1" + b"}" * 5000,
        b'{"tienda_id": 5, "fecha": "2025-11-17", "familias": [' + b'{"familia_id": "abarrotes", "en_promocion": 1},' * 5000 + b'{}]}',
    ]


def test_la_api_solo_responde_200_o_422_por_los_datos(referencia, prediccion, observacion):
    api, _ = cliente(referencia, predictor=PredictorFalso())
    azar = random.Random(7)
    for crudo in cuerpos_crudos():
        for ruta in ("/v1/prediccion", "/v1/observaciones"):
            r = api.post(ruta, content=crudo, headers={"Content-Type": "application/json"})
            assert r.status_code in (200, 422), (ruta, crudo[:80], r.status_code)
    for _ in range(300):
        for ruta, valido in (("/v1/prediccion", prediccion), ("/v1/observaciones", observacion)):
            cuerpo = mutar(azar, valido)
            r = api.post(ruta, json=cuerpo)
            assert r.status_code in (200, 422), (ruta, cuerpo, r.status_code, r.text[:300])


URL_PRUEBAS = os.environ.get("NOVAMERCADO_BD_PRUEBAS_URL")


@pytest.mark.skipif(not URL_PRUEBAS, reason="sin NOVAMERCADO_BD_PRUEBAS_URL")
def test_con_postgres_ningun_dato_impide_registrar(referencia, prediccion, observacion):
    """Un 503 por los datos sería una falla: la base debe poder guardar todo lo que la limpieza acepta."""
    from novamercado.persistencia import RegistroPostgres, crear_esquema, crear_motor, metadata

    motor = crear_motor(URL_PRUEBAS)
    metadata.drop_all(motor)
    crear_esquema(motor)
    api, _ = cliente(referencia, predictor=PredictorFalso(), registro=RegistroPostgres(motor))
    azar = random.Random(11)
    for crudo in cuerpos_crudos():
        r = api.post("/v1/observaciones", content=crudo, headers={"Content-Type": "application/json"})
        assert r.status_code in (200, 422), (crudo[:80], r.status_code)
    for _ in range(200):
        for ruta, valido in (("/v1/prediccion", prediccion), ("/v1/observaciones", observacion)):
            cuerpo = mutar(azar, valido)
            r = api.post(ruta, json=cuerpo)
            assert r.status_code in (200, 422), (ruta, cuerpo, r.status_code, r.text[:300])
    motor.dispose()
