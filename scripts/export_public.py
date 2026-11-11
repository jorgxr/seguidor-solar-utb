
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

CANALES = {
    "orientacion": (
        3575336, "TS_READ_ORIENTACION"
    ),
    "gps": (
        3575337, "TS_READ_GPS_SOL"
    ),
    "diagnostico": (
        3575338, "TS_READ_DIAGNOSTICO"
    ),
}


def obtener_datos(nombre):
    canal_id, secreto = CANALES[nombre]
    clave = os.environ.get(secreto, "").strip()

    if not clave:
        raise RuntimeError(
            f"Falta el secreto {secreto}"
        )

    parametros = urlencode({
        "api_key": clave,
        "minutes": 720,
        "results": 720,
    })

    url = (
        f"https://api.thingspeak.com/"
        f"channels/{canal_id}/feeds.json?"
        f"{parametros}"
    )

    with urlopen(url, timeout=30) as respuesta:
        datos = json.load(respuesta)

    registros = datos.get("feeds", [])

    if not registros:
        raise RuntimeError(
            f"Sin datos del canal {canal_id}"
        )

    return registros


def numero(valor, decimales=1):
    try:
        if valor is None or valor == "":
            return None

        n = float(valor)

        if not math.isfinite(n):
            return None

        return round(n, decimales)

    except (TypeError, ValueError):
        return None


def entero(valor):
    n = numero(valor, 0)
    return None if n is None else int(n)


def fecha_publica(fecha):
    """Ocultar segundos y agrupar en 5 minutos."""
    instante = datetime.fromisoformat(
        fecha.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    minuto = (instante.minute // 5) * 5

    instante = instante.replace(
        minute=minuto,
        second=0,
        microsecond=0
    )

    return instante.isoformat().replace(
        "+00:00", "Z"
    )


def campo(registro, indice, decimales=1):
    return numero(
        registro.get(f"field{indice}"),
        decimales
    )


def ultimo(registros):
    return registros[-1]


def construir_historial(registros):
    """Solo ángulos; nunca coordenadas GPS."""
    agrupados = {}

    for registro in registros:
        fecha = fecha_publica(
            registro["created_at"]
        )

        agrupados[fecha] = {
            "t": fecha,
            "az_actual": campo(registro, 1),
            "az_objetivo": campo(registro, 2),
            "el_actual": campo(registro, 4),
            "el_objetivo": campo(registro, 5),
        }

    return [
        agrupados[t] for t in sorted(agrupados)
    ]


def ubicacion_aproximada(registros):
    """Redondeo espacial: aproximadamente 10 km."""
    for registro in reversed(registros):
        lat = campo(registro, 4, 7)
        lon = campo(registro, 5, 7)

        if (
            lat is not None
            and lon is not None
            and -90 <= lat <= 90
            and -180 <= lon <= 180
            and not (lat == 0 and lon == 0)
        ):
            return {
                "lat": round(lat, 1),
                "lon": round(lon, 1)
            }

    return {
        "lat": None,
        "lon": None
    }


def main():
    orientacion = obtener_datos("orientacion")
    gps = obtener_datos("gps")
    diagnostico = obtener_datos("diagnostico")

    o = ultimo(orientacion)
    g = ultimo(gps)
    d = ultimo(diagnostico)

    # ÚNICAMENTE campos aprobados.
    # No publicar los registros originales.
    # No publicar credenciales.
    # No publicar latitud ni longitud exactas.

    publico = {
        "publicado_utc": datetime.now(
            timezone.utc
        ).replace(
            microsecond=0
        ).isoformat(),

        "orientacion": {
            "fecha": fecha_publica(
                o["created_at"]
            ),
            "az_actual": campo(o, 1),
            "az_objetivo": campo(o, 2),
            "error_az": campo(o, 3),
            "el_actual": campo(o, 4),
            "el_objetivo": campo(o, 5),
            "error_el": campo(o, 6),
            "inclinacion": campo(o, 7),
            "seguimiento": entero(
                o.get("field8")
            ),
        },

        "gps": {
            "fecha": fecha_publica(
                g["created_at"]
            ),
            "az_solar": campo(g, 1),
            "el_solar": campo(g, 2),
            "declinacion": campo(g, 3),
            "fix": entero(
                g.get("field6")
            ),
            "satelites": entero(
                g.get("field7")
            ),
            "hdop": campo(g, 8),
            "ubicacion": ubicacion_aproximada(
                gps
            ),
        },

        "diagnostico": {
            "fecha": fecha_publica(
                d["created_at"]
            ),
            "sol_actual": entero(
                d.get("field1")
            ),
            "estado": entero(
                d.get("field2")
            ),
            "wifi": entero(
                d.get("field3")
            ),
            "minutos": entero(
                d.get("field4")
            ),
        },

        "historial": construir_historial(
            orientacion
        )
    }

    destino = Path("site/data.json")
    destino.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    destino.write_text(
        json.dumps(
            publico,
            ensure_ascii=False,
            separators=(",", ":")
        ),
        encoding="utf-8"
    )

    print(
        "Telemetría pública preparada: "
        f"{len(publico['historial'])} puntos."
    )


if __name__ == "__main__":
    main()
