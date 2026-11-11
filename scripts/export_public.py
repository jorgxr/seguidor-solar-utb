
import json
import math
import os

from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen


# =========================================
# CANALES PRIVADOS DE THINGSPEAK
# =========================================

CANALES = {
    "orientacion": (
        3575336,
        "TS_READ_ORIENTACION"
    ),
    "gps": (
        3575337,
        "TS_READ_GPS_SOL"
    ),
    "diagnostico": (
        3575338,
        "TS_READ_DIAGNOSTICO"
    )
}


# =========================================
# PRIVACIDAD DE LA UBICACION PUBLICA
# =========================================

# RADIO CONFIGURABLE DEL CIRCULO PUBLICO
# 300 = 300 metros
# 500 = 500 metros
# 1200 = 1.2 kilometros

RADIO_PUBLICO_METROS = 300

# La cuadricula de aproximacion se ajusta
# automaticamente al radio escogido.
# Su lado sera de aproximadamente 300 m.
#
# La distancia maxima entre el punto GPS
# real y el centro de la celda sera
# aproximadamente 212 m para un radio de
# 300 m, en la zona de Cartagena.
#
# Asi evitamos publicar el punto preciso
# y mantenemos el dispositivo dentro
# del circulo de privacidad.

LADO_CELDA_METROS = RADIO_PUBLICO_METROS


# =========================================
# CONSULTAR THINGSPEAK
# =========================================

def obtener_datos(nombre):

    canal_id, nombre_secreto = CANALES[nombre]

    clave = os.environ.get(
        nombre_secreto, ""
    ).strip()

    if not clave:
        raise RuntimeError(
            f"Falta el secreto {nombre_secreto}"
        )

    parametros = urlencode({
        "api_key": clave,
        "minutes": 720,
        "results": 720
    })

    url = (
        "https://api.thingspeak.com/"
        f"channels/{canal_id}/feeds.json?"
        f"{parametros}"
    )

    with urlopen(url, timeout=30) as respuesta:
        datos = json.load(respuesta)

    registros = datos.get("feeds", [])

    if not registros:
        raise RuntimeError(
            f"No hay datos del canal {canal_id}"
        )

    return registros


# =========================================
# CONVERSION DE NUMEROS
# =========================================

def numero(valor, decimales=1):

    try:
        if valor is None or valor == "":
            return None

        resultado = float(valor)

        if not math.isfinite(resultado):
            return None

        return round(resultado, decimales)

    except (ValueError, TypeError):
        return None


def entero(valor):

    valor_numerico = numero(valor, 0)

    if valor_numerico is None:
        return None

    return int(valor_numerico)


def campo(registro, indice, decimales=1):

    return numero(
        registro.get(f"field{indice}"),
        decimales
    )


def ultimo(registros):
    return registros[-1]


# =========================================
# FECHAS PUBLICAS
# =========================================

def fecha_publica(fecha):

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


# =========================================
# HISTORIAL PUBLICO DE ORIENTACION
# =========================================

def construir_historial(registros):

    agrupados = {}

    for registro in registros:

        fecha = fecha_publica(
            registro["created_at"]
        )

        agrupados[fecha] = {
            "t": fecha,

            "az_actual": campo(
                registro, 1
            ),

            "az_objetivo": campo(
                registro, 2
            ),

            "el_actual": campo(
                registro, 4
            ),

            "el_objetivo": campo(
                registro, 5
            )
        }

    return [
        agrupados[fecha]
        for fecha in sorted(agrupados)
    ]


# =========================================
# GENERALIZACION GPS
# =========================================

def centro_aproximado(latitud, longitud):
    """
    Convierte la ubicacion GPS en el centro
    de una celda aproximada.

    La celda cambia de tamaño cuando
    modificamos RADIO_PUBLICO_METROS.

    Nunca devuelve directamente la
    coordenada original del receptor.
    """

    metros_por_grado = 111320.0

    lado = float(LADO_CELDA_METROS)

    paso_lat = lado / metros_por_grado

    cos_lat = math.cos(
        math.radians(latitud)
    )

    paso_lon = lado / (
        metros_por_grado *
        max(0.1, abs(cos_lat))
    )

    centro_lat = (
        math.floor(latitud / paso_lat) + 0.5
    ) * paso_lat

    centro_lon = (
        math.floor(longitud / paso_lon) + 0.5
    ) * paso_lon

    return {
        "lat": round(centro_lat, 5),
        "lon": round(centro_lon, 5),
        "radio_m": RADIO_PUBLICO_METROS
    }


def ubicacion_aproximada(registros):
    """
    Field 4 = latitud GPS
    Field 5 = longitud GPS
    Field 6 = GPS fix

    Busca la ultima lectura valida y
    publica solamente la zona aproximada.
    """

    for registro in reversed(registros):

        fix = entero(
            registro.get("field6")
        )

        latitud = campo(
            registro, 4, 7
        )

        longitud = campo(
            registro, 5, 7
        )

        coordenadas_validas = (
            fix == 1
            and latitud is not None
            and longitud is not None
            and -90 <= latitud <= 90
            and -180 <= longitud <= 180
            and not (
                latitud == 0
                and longitud == 0
            )
        )

        if coordenadas_validas:

            return centro_aproximado(
                latitud,
                longitud
            )

    return {
        "lat": None,
        "lon": None,
        "radio_m": RADIO_PUBLICO_METROS
    }


# =========================================
# PREPARAR DATOS PUBLICOS
# =========================================

def main():

    orientacion = obtener_datos(
        "orientacion"
    )

    gps = obtener_datos(
        "gps"
    )

    diagnostico = obtener_datos(
        "diagnostico"
    )

    o = ultimo(orientacion)
    g = ultimo(gps)
    d = ultimo(diagnostico)

    # Se publican solo campos autorizados.
    #
    # NO se publica:
    # - GPS preciso
    # - API Keys
    # - Credenciales MQTT
    # - Registros completos privados

    publico = {

        "publicado_utc": datetime.now(
            timezone.utc
        ).replace(
            microsecond=0
        ).isoformat(),

        # ORIENTACION

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
            )
        },

        # GPS Y CALCULO SOLAR

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
            )
        },

        # DIAGNOSTICO

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
            )
        },

        # HISTORIAL DE LOS EJES

        "historial": construir_historial(
            orientacion
        )
    }

    # GUARDAR SOLO LOS DATOS FILTRADOS

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

    print("Telemetria publica preparada.")
    print(
        "Radio de privacidad:",
        RADIO_PUBLICO_METROS,
        "metros"
    )
    print(
        "Registros historicos:",
        len(publico["historial"])
    )
    print(
        "Coordenadas GPS exactas: "
        "NO PUBLICADAS"
    )


if __name__ == "__main__":
    main()
