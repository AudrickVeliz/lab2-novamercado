"""Defensa del contrato: convierte una solicitud cruda en una solicitud limpia.

Cada problema en los datos recibe una de tres políticas (ver DECISIONES.md, D-003):

- **Reparar:** hay una sola interpretación posible. Se corrige y se informa.
- **Advertir:** se responde asumiendo algo. Se informa qué se asumió.
- **Rechazar:** no se puede responder sin inventar datos (`SolicitudRechazada`, 422).

Las reglas son generales (nombres de campos, números, fechas y familias se
normalizan de la misma forma en todo el contrato) para cubrir problemas que no
están en el catálogo. Este módulo no usa el reloj del sistema.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Generic, TypeVar

import pandas as pd

from novamercado.catalogos import Catalogos
from novamercado.contrato import (
    MAXIMO_ENTERO,
    Calidad,
    FamiliaPromocion,
    ObservacionCalidad,
    SolicitudObservacion,
    SolicitudPrediccion,
    VentaFamilia,
)

# Una observación mayor que FACTOR_ATIPICO veces el máximo histórico de su tienda
# y familia se guarda, pero con advertencia (D-003).
FACTOR_ATIPICO = 5

T = TypeVar("T")


class SolicitudRechazada(ValueError):
    """La solicitud no se puede atender sin inventar datos: se responde 422."""

    def __init__(self, detalle: str):
        super().__init__(detalle)
        self.detalle = detalle


@dataclass(frozen=True)
class Referencia:
    """Lo que la limpieza necesita conocer: catálogos y máximos históricos."""

    catalogos: Catalogos
    # (tienda_id, familia_id) -> máximo histórico de ventas. Vacío: no se revisan atípicos.
    maximos: Mapping[tuple[int, str], int] = field(default_factory=dict)

    @cached_property
    def indice_familias(self) -> dict[str, str | None]:
        """clave → familia_id, a partir del id y del nombre. None marca una clave ambigua."""
        indice: dict[str, str | None] = {}
        for familia_id, fila in self.catalogos.familias.iterrows():
            for texto in (familia_id, fila["nombre"]):
                k = clave(str(texto))
                indice[k] = familia_id if indice.get(k, familia_id) == familia_id else None
        return indice


@dataclass(frozen=True)
class Resultado(Generic[T]):
    solicitud: T
    observaciones: list[ObservacionCalidad]
    # Rutas de los campos desconocidos que se ignoraron (se guardan en la BD, no en la respuesta).
    ignorados: list[str]

    @property
    def calidad(self) -> Calidad:
        return Calidad.desde(self.observaciones)


def maximos_historicos(historico: pd.DataFrame) -> dict[tuple[int, str], int]:
    """Máximo de ventas por tienda y familia, para detectar observaciones atípicas."""
    maximos = historico.groupby(["tienda_id", "familia_id"])["ventas"].max()
    return {(int(t), str(f)): int(v) for (t, f), v in maximos.items()}


# Nombres de campos (E07)

_ALIAS_TIENDA = {"tiendaid", "tienda", "idtienda", "store", "storeid", "storenbr",
                 "codigotienda", "codtienda", "sucursal", "sucursalid"}
_ALIAS_FAMILIA = {"familiaid", "familia", "idfamilia", "family", "familyid",
                  "categoria", "categoriaid"}

ALIAS_PREDICCION = {
    "tienda_id": _ALIAS_TIENDA,
    "fecha": {"fecha", "date", "dia", "fechapronostico", "fechaprediccion", "fechasolicitud"},
    "familias": {"familias", "families", "items", "productos", "detalle", "lineas"},
}
ALIAS_ITEM_PREDICCION = {
    "familia_id": _ALIAS_FAMILIA,
    "en_promocion": {"enpromocion", "promocion", "promociones", "promo", "onpromotion",
                     "productosenpromocion"},
}
ALIAS_OBSERVACION = {
    "tienda_id": _ALIAS_TIENDA,
    "fecha": {"fecha", "date", "dia", "fechaventa", "fechaobservacion"},
    "ventas": {"ventas", "observaciones", "familias", "items", "detalle", "lineas", "sales"},
}
ALIAS_ITEM_OBSERVACION = {
    "familia_id": _ALIAS_FAMILIA,
    "ventas": {"ventas", "venta", "sales", "unidades", "cantidad", "ventasreales",
               "unidadesvendidas"},
}


def clave(texto: str) -> str:
    """Forma comparable de un texto: sin tildes, minúsculas y solo letras y dígitos."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sin_tildes.lower())


@dataclass(frozen=True)
class _Campo:
    nombre: str  # como llegó en la solicitud
    ruta: str  # ruta para informar en calidad
    valor: Any


class _Registro:
    def __init__(self) -> None:
        self.observaciones: list[ObservacionCalidad] = []
        self.ignorados: list[str] = []

    def reparar(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo=campo, accion="reparar", detalle=detalle))

    def advertir(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo=campo, accion="advertir", detalle=detalle))


def _ruta(base: str, nombre: str) -> str:
    return f"{base}.{nombre}" if base else nombre


def _resolver_campos(
    objeto: dict, alias: dict[str, set[str]], base: str, registro: _Registro
) -> dict[str, _Campo]:
    """Asigna cada campo recibido a un campo del contrato.

    Un alias reconocido se repara. Dos campos que apuntan al mismo campo del
    contrato con valores distintos se rechazan. Los desconocidos se ignoran.
    """
    candidatos: dict[str, list[_Campo]] = {}
    for nombre, valor in objeto.items():
        nombre_texto = str(nombre)
        destino = next((c for c, claves in alias.items() if clave(nombre_texto) in claves), None)
        campo = _Campo(nombre_texto, _ruta(base, nombre_texto), valor)
        if destino is None:
            registro.ignorados.append(campo.ruta)
        else:
            candidatos.setdefault(destino, []).append(campo)

    resueltos: dict[str, _Campo] = {}
    for destino, campos in candidatos.items():
        exacto = next((c for c in campos if c.nombre == destino), None)
        if len({repr(c.valor) for c in campos}) > 1:
            nombres = ", ".join(f"'{c.nombre}'" for c in campos)
            raise SolicitudRechazada(
                f"Los campos {nombres} corresponden a '{_ruta(base, destino)}' y tienen valores distintos"
            )
        elegido = exacto or campos[0]
        for c in campos:
            if c is not exacto:
                registro.reparar(c.ruta, f"'{c.nombre}' se interpretó como '{destino}'")
        resueltos[destino] = elegido
    return resueltos


def _requerido(campos: dict[str, _Campo], nombre: str) -> _Campo:
    if nombre not in campos:
        raise SolicitudRechazada(f"Falta el campo obligatorio '{nombre}'")
    return campos[nombre]


# Números (E03, E08, E10)


def _miles_validos(texto: str, separador: str) -> bool:
    grupos = texto.split(separador)
    return (
        1 <= len(grupos[0]) <= 3
        and grupos[0].isdigit()
        and not grupos[0].startswith("0")
        and all(len(g) == 3 and g.isdigit() for g in grupos[1:])
    )


def interpretar_numero(valor: Any) -> float | None:
    """Lee un número que puede venir como texto y con separadores.

    Un separador seguido de exactamente tres dígitos es de miles ("1,234" → 1234).
    Con uno o dos dígitos, o más de tres, es decimal ("812,0" → 812). Si aparecen
    punto y coma, el último es el decimal. Devuelve None si no es un número.
    """
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return float(valor)
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if not isinstance(valor, str):
        return None

    texto = re.sub(r"\s", "", valor)
    coincidencia = re.fullmatch(r"([+-]?)(\d[\d.,]*)", texto)
    if not coincidencia or texto[-1] in ".,":
        return None
    signo, cuerpo = coincidencia.groups()
    separadores = set(re.findall(r"[.,]", cuerpo))

    if not separadores:
        return float(signo + cuerpo)
    if len(separadores) == 2:
        decimal = cuerpo[max(cuerpo.rfind("."), cuerpo.rfind(","))]
        miles = "," if decimal == "." else "."
        entera, fraccion = cuerpo.rsplit(decimal, 1)
        if decimal in entera or not _miles_validos(entera, miles):
            return None
        return float(f"{signo}{entera.replace(miles, '')}.{fraccion}")

    separador = separadores.pop()
    partes = cuerpo.split(separador)
    if len(partes) > 2:
        return float(signo + cuerpo.replace(separador, "")) if _miles_validos(cuerpo, separador) else None
    entera, fraccion = partes
    if len(fraccion) == 3 and _miles_validos(cuerpo, separador):
        return float(signo + entera + fraccion)
    return float(f"{signo}{entera}.{fraccion}")


def _formato(valor: Any) -> str:
    return f"'{valor}'" if isinstance(valor, str) else repr(valor)


def _es_entero_json(valor: Any) -> bool:
    # bool es subclase de int en Python, pero en JSON true no es un número.
    return isinstance(valor, int) and not isinstance(valor, bool)


def _entero_reparado(valor: Any) -> tuple[int | None, bool]:
    """(entero, se_reinterpretó). None si no es un número entero."""
    numero = interpretar_numero(valor)
    if numero is None or not numero.is_integer():
        return None, False
    return int(numero), not _es_entero_json(valor)


# Tienda (E01)


def _tienda(campo: _Campo, referencia: Referencia, registro: _Registro) -> int:
    valor = campo.valor
    tienda, reinterpretado = _entero_reparado(valor)
    if tienda is None and isinstance(valor, str):
        # Un único número con prefijo o sufijo de texto: "T05", "tienda 5", "#5".
        numeros = re.findall(r"\d+", valor)
        if len(numeros) == 1 and not re.search(r"[.,]\d", valor):
            tienda, reinterpretado = int(numeros[0]), True
    if tienda is None:
        raise SolicitudRechazada(f"'{campo.ruta}' no identifica una tienda: {_formato(valor)}")
    if tienda not in referencia.catalogos.ids_tiendas:
        raise SolicitudRechazada(f"La tienda {tienda} no existe")
    if reinterpretado:
        registro.reparar(campo.ruta, f"{_formato(valor)} se interpretó como la tienda {tienda}")
    return tienda


# Fecha (E04)

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_ISO_CON_HORA = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
_ANIO_PRIMERO = re.compile(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})")
_ANIO_AL_FINAL = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")


def _crear_fecha(anio: int, mes: int, dia: int, campo: _Campo) -> dt.date:
    try:
        return dt.date(anio, mes, dia)
    except ValueError:
        raise SolicitudRechazada(f"'{campo.ruta}' no es una fecha válida: {_formato(campo.valor)}") from None


def _fecha(campo: _Campo, registro: _Registro) -> dt.date:
    valor = campo.valor
    if not isinstance(valor, str):
        raise SolicitudRechazada(f"'{campo.ruta}' debe ser una fecha AAAA-MM-DD: {_formato(valor)}")
    texto = valor.strip()
    ambigua, nota = False, ""

    if m := _ISO.fullmatch(texto) or _ISO_CON_HORA.fullmatch(texto) or _ANIO_PRIMERO.fullmatch(texto):
        anio, mes, dia = map(int, m.groups()[:3])
    elif m := _ANIO_AL_FINAL.fullmatch(texto):
        a, b, anio = map(int, m.groups())
        if a > 12 and b > 12:
            raise SolicitudRechazada(f"'{campo.ruta}' no es una fecha válida: {_formato(valor)}")
        # Día primero, la convención en Guatemala, salvo que el segundo número no pueda ser mes.
        dia, mes = (b, a) if b > 12 else (a, b)
        nota = " (mes primero)" if b > 12 else ""
        ambigua = a <= 12 and b <= 12 and a != b
    else:
        raise SolicitudRechazada(f"'{campo.ruta}' debe ser una fecha AAAA-MM-DD: {_formato(valor)}")

    fecha = _crear_fecha(anio, mes, dia, campo)
    if ambigua:
        registro.advertir(campo.ruta, f"{_formato(valor)} es ambigua; se asumió día primero: {fecha.isoformat()}")
    elif valor != fecha.isoformat():
        registro.reparar(campo.ruta, f"{_formato(valor)} se interpretó como {fecha.isoformat()}{nota}")
    return fecha


def _validar_apertura(tienda: int, fecha: dt.date, referencia: Referencia) -> None:
    apertura = referencia.catalogos.tiendas.loc[tienda, "fecha_apertura"].date()
    if fecha < apertura:
        raise SolicitudRechazada(
            f"La tienda {tienda} abrió el {apertura.isoformat()}; no opera el {fecha.isoformat()}"
        )


# Familias (E02)


def _familia(campos: dict[str, _Campo], ruta_item: str, referencia: Referencia, registro: _Registro) -> str | None:
    campo = campos.get("familia_id")
    if campo is None:
        registro.advertir(ruta_item, "no trae familia_id; se omitió")
        return None
    valor = campo.valor
    if isinstance(valor, str) and valor in referencia.catalogos.ids_familias:
        return valor
    familia = referencia.indice_familias.get(clave(valor)) if isinstance(valor, str) else None
    if familia is None:
        registro.advertir(campo.ruta, f"la familia {_formato(valor)} no se reconoce; se omitió")
        return None
    registro.reparar(campo.ruta, f"{_formato(valor)} se interpretó como '{familia}'")
    return familia


def _items(campo_lista: _Campo, registro: _Registro) -> list[tuple[str, dict]]:
    if not isinstance(campo_lista.valor, list):
        raise SolicitudRechazada(f"'{campo_lista.ruta}' debe ser una lista")
    items = []
    for i, item in enumerate(campo_lista.valor):
        ruta = f"{campo_lista.ruta}[{i}]"
        if isinstance(item, dict):
            items.append((ruta, item))
        else:
            registro.advertir(ruta, f"no es un objeto ({_formato(item)}); se omitió")
    return items


def _objeto(crudo: Any) -> dict:
    if not isinstance(crudo, dict):
        raise SolicitudRechazada("El cuerpo de la solicitud debe ser un objeto JSON")
    return crudo


# Predicción


def _promocion(campos: dict[str, _Campo], ruta_item: str, registro: _Registro) -> int:
    campo = campos.get("en_promocion")
    if campo is None:
        registro.advertir(ruta_item, "no trae en_promocion; se asumió 0")
        return 0
    promocion, reinterpretado = _entero_reparado(campo.valor)
    if promocion is None or not 0 <= promocion <= MAXIMO_ENTERO:
        registro.advertir(campo.ruta, f"en_promocion inválida ({_formato(campo.valor)}); se asumió 0")
        return 0
    if reinterpretado:
        registro.reparar(campo.ruta, f"{_formato(campo.valor)} se interpretó como {promocion}")
    return promocion


def limpiar_prediccion(crudo: Any, referencia: Referencia) -> Resultado[SolicitudPrediccion]:
    registro = _Registro()
    campos = _resolver_campos(_objeto(crudo), ALIAS_PREDICCION, "", registro)
    tienda = _tienda(_requerido(campos, "tienda_id"), referencia, registro)
    campo_fecha = _requerido(campos, "fecha")
    fecha = _fecha(campo_fecha, registro)
    _validar_apertura(tienda, fecha, referencia)
    ultimo_feriado = referencia.catalogos.feriados["fecha"].max().date()
    if fecha > ultimo_feriado:
        registro.advertir(
            campo_fecha.ruta,
            f"no se conocen los feriados posteriores al {ultimo_feriado.isoformat()}; se pronosticó sin ellos",
        )

    campo_lista = _requerido(campos, "familias")
    recibidas: dict[str, list[tuple[str, int]]] = {}
    for ruta, item in _items(campo_lista, registro):
        campos_item = _resolver_campos(item, ALIAS_ITEM_PREDICCION, ruta, registro)
        familia = _familia(campos_item, ruta, referencia, registro)
        if familia is not None:
            recibidas.setdefault(familia, []).append((ruta, _promocion(campos_item, ruta, registro)))

    familias = []
    for familia, valores in recibidas.items():
        promociones = [p for _, p in valores]
        if len(valores) > 1:
            rutas = ", ".join(r for r, _ in valores)
            if len(set(promociones)) == 1:
                registro.reparar(rutas, f"'{familia}' llegó {len(valores)} veces con los mismos valores; se usó una vez")
            else:
                registro.advertir(
                    rutas,
                    f"'{familia}' llegó {len(valores)} veces con en_promocion distintas "
                    f"({', '.join(map(str, promociones))}); se usó la mayor ({max(promociones)})",
                )
        familias.append(FamiliaPromocion(familia_id=familia, en_promocion=max(promociones)))

    for faltante in sorted(referencia.catalogos.ids_familias - recibidas.keys()):
        registro.advertir(campo_lista.ruta, f"no se recibió '{faltante}'; se pronosticó con en_promocion = 0")
        familias.append(FamiliaPromocion(familia_id=faltante, en_promocion=0))

    solicitud = SolicitudPrediccion(tienda_id=tienda, fecha=fecha, familias=tuple(familias))
    return Resultado(solicitud, registro.observaciones, registro.ignorados)


# Observaciones


def _ventas(campos: dict[str, _Campo], ruta_item: str, familia: str, registro: _Registro) -> int | None:
    campo = campos.get("ventas")
    if campo is None:
        registro.advertir(ruta_item, f"no trae ventas para '{familia}'; no se guardó")
        return None
    numero = interpretar_numero(campo.valor)
    problema = (
        "ilegibles" if numero is None
        else "negativas" if numero < 0
        else "no enteras" if not numero.is_integer()
        else "fuera de rango" if numero > MAXIMO_ENTERO
        else None
    )
    if problema:
        registro.advertir(campo.ruta, f"ventas {problema} ({_formato(campo.valor)}) para '{familia}'; no se guardó")
        return None
    if not _es_entero_json(campo.valor):
        registro.reparar(campo.ruta, f"{_formato(campo.valor)} se interpretó como {int(numero)}")
    return int(numero)


def limpiar_observacion(crudo: Any, referencia: Referencia) -> Resultado[SolicitudObservacion]:
    registro = _Registro()
    campos = _resolver_campos(_objeto(crudo), ALIAS_OBSERVACION, "", registro)
    tienda = _tienda(_requerido(campos, "tienda_id"), referencia, registro)
    fecha = _fecha(_requerido(campos, "fecha"), registro)
    _validar_apertura(tienda, fecha, referencia)

    campo_lista = _requerido(campos, "ventas")
    recibidas: dict[str, list[tuple[str, int | None]]] = {}
    for ruta, item in _items(campo_lista, registro):
        campos_item = _resolver_campos(item, ALIAS_ITEM_OBSERVACION, ruta, registro)
        familia = _familia(campos_item, ruta, referencia, registro)
        if familia is not None:
            recibidas.setdefault(familia, []).append((ruta, _ventas(campos_item, ruta, familia, registro)))

    ventas = []
    for familia, valores in recibidas.items():
        validos = [v for _, v in valores if v is not None]
        if not validos:
            continue
        if len(validos) > 1:
            rutas = ", ".join(r for r, v in valores if v is not None)
            if len(set(validos)) > 1:
                registro.advertir(
                    rutas,
                    f"'{familia}' llegó {len(validos)} veces con ventas distintas "
                    f"({', '.join(map(str, validos))}); no se guardó",
                )
                continue
            registro.reparar(rutas, f"'{familia}' llegó {len(validos)} veces con las mismas ventas; se usó una vez")
        valor = validos[0]
        maximo = referencia.maximos.get((tienda, familia))
        if maximo is not None and valor > FACTOR_ATIPICO * max(maximo, 1):
            registro.advertir(
                valores[0][0],
                f"ventas atípicas para '{familia}': {valor} supera {FACTOR_ATIPICO} veces el máximo "
                f"histórico ({maximo}); se guardó",
            )
        ventas.append(VentaFamilia(familia_id=familia, ventas=valor))

    for faltante in sorted(referencia.catalogos.ids_familias - recibidas.keys()):
        registro.advertir(campo_lista.ruta, f"no se recibió '{faltante}'")

    solicitud = SolicitudObservacion(tienda_id=tienda, fecha=fecha, ventas=tuple(ventas))
    return Resultado(solicitud, registro.observaciones, registro.ignorados)
