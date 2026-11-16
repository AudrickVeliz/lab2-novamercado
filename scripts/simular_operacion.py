"""Simula semanas de operación diaria contra el producto levantado (ver D-012).

Imita el programa de evaluación del enunciado: cada día llegan primero las
observaciones del día anterior y después las solicitudes de pronóstico de cada
tienda, algunas con problemas; cada cierto tiempo se reentrena por /admin. Mide el
costo de las cantidades sugeridas con costos.csv.

Las ventas "reales" se simulan a partir del mismo día de la semana del año anterior,
con el crecimiento interanual, un cambio de demanda y ruido de Poisson.

    python scripts/simular_operacion.py --datos data/publicados --salida docs/evidencia
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

CRECIMIENTO_INTERANUAL = 1.10  # febrero 2026 frente a febrero 2025 en el histórico
SEMILLA = 20260301


def llamar(api: str, metodo: str, ruta: str, cuerpo=None, crudo: bool = False) -> tuple[int, dict]:
    datos = None if cuerpo is None else (cuerpo if crudo else json.dumps(cuerpo)).encode()
    solicitud = urllib.request.Request(api + ruta, data=datos, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(solicitud, timeout=60) as respuesta:
            return respuesta.status, json.loads(respuesta.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def ventas_reales(historico: pd.DataFrame, fechas: pd.DatetimeIndex, inicio_cambio: pd.Timestamp, cambio: float) -> pd.DataFrame:
    """Ventas y promoción simuladas: mismo día de la semana del año anterior, escalado y con ruido."""
    azar = np.random.default_rng(SEMILLA)
    base = historico.set_index(["fecha", "tienda_id", "familia_id"])
    filas = []
    for fecha in fechas:
        anterior = base.loc[fecha - pd.Timedelta(days=364)]
        factor = CRECIMIENTO_INTERANUAL * (cambio if fecha >= inicio_cambio else 1.0)
        for (tienda, familia), fila in anterior.iterrows():
            filas.append((fecha, tienda, familia, int(azar.poisson(fila["ventas"] * factor)), int(fila["en_promocion"])))
    return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])


def con_error_de_prediccion(azar: random.Random, cuerpo: dict) -> tuple[dict, str]:
    """Algunas solicitudes llegan con uno de los problemas del catálogo."""
    cuerpo = copy.deepcopy(cuerpo)
    tipo = azar.choice(["E01", "E02", "E03", "E04", "E05", "E06", "E07", "extra"])
    familias = cuerpo["familias"]
    if tipo == "E01":
        cuerpo["tienda_id"] = f"T{cuerpo['tienda_id']:02d}"
    elif tipo == "E02":
        familias[0]["familia_id"] = familias[0]["familia_id"].upper() + " "
    elif tipo == "E03":
        familias[1]["en_promocion"] = str(familias[1]["en_promocion"])
    elif tipo == "E04":
        anio, mes, dia = cuerpo["fecha"].split("-")
        cuerpo["fecha"] = f"{dia}/{mes}/{anio}"
    elif tipo == "E05":
        del familias[-2:]
    elif tipo == "E06":
        familias.append({**familias[0], "en_promocion": familias[0]["en_promocion"] + 3})
    elif tipo == "E07":
        cuerpo["tienda"] = cuerpo.pop("tienda_id")
    else:
        cuerpo["sistema_origen"] = "pos-v2"
    return cuerpo, tipo


def con_error_de_observacion(azar: random.Random, cuerpo: dict) -> tuple[dict, str]:
    cuerpo = copy.deepcopy(cuerpo)
    tipo = azar.choice(["E08", "E10", "parcial"])
    ventas = cuerpo["ventas"]
    if tipo == "E08":
        ventas[0]["ventas"] = -abs(ventas[0]["ventas"]) - 1
    elif tipo == "E10":
        ventas[1]["ventas"] = f"{ventas[1]['ventas']:,}"
    else:
        del ventas[-1]
    return cuerpo, tipo


def reentrenar(api: str, version_actual: str) -> dict:
    inicio = time.monotonic()
    codigo, disparo = llamar(api, "POST", "/admin/reentrenar")
    if codigo != 202:
        return {"estado": f"HTTP {codigo}", "motivo": disparo.get("detail", "")}
    id = urllib.request.quote(disparo["id"], safe="")
    while True:
        _, estado = llamar(api, "GET", f"/admin/reentrenar/{id}")
        if estado.get("estado") != "en_curso":
            break
        time.sleep(3)
    estado["segundos"] = round(time.monotonic() - inicio)
    if estado.get("promovido"):
        # Cuánto tarda la API en usar el modelo nuevo, sin reinicio (límite: 2 minutos).
        inicio = time.monotonic()
        while llamar(api, "GET", "/modelo")[1].get("version") != estado["version"]:
            if time.monotonic() - inicio > 180:
                estado["segundos_hasta_usarlo"] = "no la usó en 180"
                break
            time.sleep(2)
        else:
            estado["segundos_hasta_usarlo"] = round(time.monotonic() - inicio)
    estado["version_anterior"] = version_actual
    return estado


def principal() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--api", default="http://127.0.0.1:8000")
    argumentos.add_argument("--datos", default="data/publicados")
    argumentos.add_argument("--salida", default="docs/evidencia")
    argumentos.add_argument("--inicio", default="2026-03-01")
    argumentos.add_argument("--semanas", type=int, default=10)
    argumentos.add_argument("--semana-cambio", type=int, default=4, help="semana en que empieza el cambio de demanda")
    argumentos.add_argument("--cambio", type=float, default=1.20)
    argumentos.add_argument("--reentrenar-cada", type=int, default=14, help="días entre reentrenamientos")
    argumentos.add_argument("--errores", type=float, default=0.15, help="fracción de solicitudes con problemas")
    a = argumentos.parse_args()

    datos, salida = Path(a.datos), Path(a.salida)
    historico = pd.read_csv(datos / "historico_ventas.csv", parse_dates=["fecha"])
    costos = pd.read_csv(datos / "costos.csv").set_index("familia_id")
    inicio = pd.Timestamp(a.inicio)
    fechas = pd.date_range(inicio, periods=7 * a.semanas, freq="D")
    inicio_cambio = inicio + pd.Timedelta(weeks=a.semana_cambio - 1)
    reales = ventas_reales(historico, fechas, inicio_cambio, a.cambio)
    conocidas = pd.concat([historico[["fecha", "tienda_id", "familia_id", "ventas"]], reales[["fecha", "tienda_id", "familia_id", "ventas"]]])
    azar = random.Random(SEMILLA)

    filas, reentrenamientos, estados_calidad, codigos = [], [], {}, {}
    version = llamar(a.api, "GET", "/modelo")[1].get("version", "?")
    for numero, fecha in enumerate(fechas):
        dia = fecha.date().isoformat()
        # 1. Observaciones del día anterior (llegan antes que las solicitudes del día).
        ayer = reales[reales["fecha"] == fecha - pd.Timedelta(days=1)]
        for tienda, grupo in ayer.groupby("tienda_id"):
            cuerpo = {"tienda_id": int(tienda), "fecha": (fecha - pd.Timedelta(days=1)).date().isoformat(),
                      "ventas": [{"familia_id": f, "ventas": int(v)} for f, v in zip(grupo["familia_id"], grupo["ventas"])]}
            if azar.random() < a.errores:
                cuerpo, _ = con_error_de_observacion(azar, cuerpo)
            codigo, respuesta = llamar(a.api, "POST", "/v1/observaciones", cuerpo)
            codigos[codigo] = codigos.get(codigo, 0) + 1
            if azar.random() < 0.05:  # E09: el sistema de la tienda reenvía lo mismo
                assert llamar(a.api, "POST", "/v1/observaciones", cuerpo)[1]["registros_guardados"] == 0
        # 2. Solicitudes de pronóstico de cada tienda.
        hoy = reales[reales["fecha"] == fecha]
        for tienda, grupo in hoy.groupby("tienda_id"):
            cuerpo = {"tienda_id": int(tienda), "fecha": dia,
                      "familias": [{"familia_id": f, "en_promocion": int(p)} for f, p in zip(grupo["familia_id"], grupo["en_promocion"])]}
            error = None
            if azar.random() < a.errores:
                cuerpo, error = con_error_de_prediccion(azar, cuerpo)
            codigo, respuesta = llamar(a.api, "POST", "/v1/prediccion", cuerpo)
            codigos[codigo] = codigos.get(codigo, 0) + 1
            if codigo != 200:
                continue
            estados_calidad[respuesta["calidad"]["estado"]] = estados_calidad.get(respuesta["calidad"]["estado"], 0) + 1
            version = respuesta["version_modelo"]
            real = grupo.set_index("familia_id")["ventas"]
            for p in respuesta["predicciones"]:
                r = int(real[p["familia_id"]])
                cf, cs = costos.loc[p["familia_id"], ["costo_faltante", "costo_sobrante"]]
                # Referencia ingenua: sugerir la media de los cuatro mismos días anteriores.
                previas = [fecha - pd.Timedelta(days=7 * k) for k in range(1, 5)]
                serie = conocidas[(conocidas["tienda_id"] == tienda) & (conocidas["familia_id"] == p["familia_id"])]
                media = serie[serie["fecha"].isin(previas)]["ventas"].mean()
                ingenua = 0 if pd.isna(media) else round(media)
                filas.append({
                    "fecha": dia, "tienda_id": int(tienda), "familia_id": p["familia_id"], "version_modelo": version,
                    "error_inyectado": error or "", "real": r, "venta_esperada": p["venta_esperada"],
                    "cantidad_sugerida": p["cantidad_sugerida"], "sugerida_ingenua": ingenua,
                    "costo": cf * max(r - p["cantidad_sugerida"], 0) + cs * max(p["cantidad_sugerida"] - r, 0),
                    "costo_ingenuo": cf * max(r - ingenua, 0) + cs * max(ingenua - r, 0),
                })
        # 3. Reentrenamiento periódico por el endpoint de administración.
        if (numero + 1) % a.reentrenar_cada == 0:
            resultado = reentrenar(a.api, version)
            resultado["dia"] = dia
            reentrenamientos.append(resultado)
            print(f"{dia} reentrenamiento: {resultado}")
        print(f"{dia} listo ({len(filas)} pronósticos, versión {version})", flush=True)

    salida.mkdir(parents=True, exist_ok=True)
    detalle = pd.DataFrame(filas)
    detalle.to_csv(salida / "simulacion.csv", index=False)
    escribir_reporte(salida / "simulacion.md", a, inicio_cambio, detalle, reentrenamientos, estados_calidad, codigos)


def escribir_reporte(ruta, a, inicio_cambio, detalle, reentrenamientos, estados_calidad, codigos) -> None:
    detalle = detalle.assign(semana=(pd.to_datetime(detalle["fecha"]) - pd.Timestamp(a.inicio)).dt.days // 7 + 1)
    semanal = detalle.groupby("semana").agg(
        desde=("fecha", "min"), version=("version_modelo", lambda v: ", ".join(sorted(set(v)))),
        real=("real", "sum"), esperada=("venta_esperada", "sum"), costo=("costo", "sum"), costo_ingenuo=("costo_ingenuo", "sum"),
    )
    semanal["wape"] = detalle.assign(e=(detalle["venta_esperada"] - detalle["real"]).abs()).groupby("semana")["e"].sum() / semanal["real"]
    total, ingenuo = detalle["costo"].sum(), detalle["costo_ingenuo"].sum()
    lineas = [
        "# Simulación de operación", "",
        f"Generada con `python scripts/simular_operacion.py` contra el producto levantado con `docker compose up`. Ver D-012.", "",
        "## Configuración", "",
        f"- Desde {a.inicio}, {a.semanas} semanas; cambio de demanda ×{a.cambio} desde {inicio_cambio.date()} (semana {a.semana_cambio}).",
        f"- Ventas reales: mismo día de la semana del año anterior × {CRECIMIENTO_INTERANUAL} (crecimiento interanual) × cambio × ruido de Poisson; la promoción es la de ese día del año anterior.",
        f"- Cada día: observaciones del día anterior y luego una solicitud de pronóstico por tienda. {a.errores:.0%} de las solicitudes con un problema del catálogo; 5 % de las observaciones se reenvían (E09).",
        f"- Reentrenamiento por `POST /admin/reentrenar` cada {a.reentrenar_cada} días.", "",
        "## Resultado", "",
        f"- Pronósticos evaluados: {len(detalle)} (tienda × familia × día).",
        f"- **Costo total de las sugerencias: {total:,.0f}**, frente a {ingenuo:,.0f} de sugerir la media de los 4 mismos días anteriores ({(1 - total / ingenuo):.1%} menos).".replace(",", " "),
        f"- Respuestas HTTP: {dict(sorted(codigos.items()))}. Calidad de las predicciones: {dict(sorted(estados_calidad.items()))}.", "",
        "### Por semana", "",
        "| Semana | Desde | Versión | Ventas reales | Venta esperada | WAPE | Costo | Costo ingenuo |", "|---|---|---|---|---|---|---|---|",
    ]
    for semana, f in semanal.iterrows():
        lineas.append(f"| {semana} | {f['desde']} | {f['version']} | {f['real']:,.0f} | {f['esperada']:,.0f} | {f['wape']:.3f} | {f['costo']:,.0f} | {f['costo_ingenuo']:,.0f} |".replace(",", " "))
    lineas += ["", "### Reentrenamientos", "", "| Día | Estado | Promovido | Versión anterior → vigente | Motivo | Duración | Hasta usarlo |", "|---|---|---|---|---|---|---|"]
    for r in reentrenamientos:
        usar = f"{r['segundos_hasta_usarlo']} s" if "segundos_hasta_usarlo" in r else "—"
        lineas.append(f"| {r['dia']} | {r.get('estado')} | {r.get('promovido')} | {r.get('version_anterior')} → {r.get('version')} | {r.get('motivo')} | {r.get('segundos', '—')} s | {usar} |")
    # LF también en Windows, como el resto del repositorio.
    Path(ruta).write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lineas))


if __name__ == "__main__":
    principal()
