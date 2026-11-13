
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
# PRIVACIDAD DEL MAPA GPS
# SE CONSERVA RADIO DE 300 METROS
# =========================================

RADIO_PUBLICO_METROS = 300
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
            f"Sin datos del canal {canal_id}"
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

    resultado = numero(valor, 0)

    if resultado is None:
        return None

    return int(resultado)


def campo(registro, indice, decimales=1):

    return numero(
        registro.get(f"field{indice}"),
        decimales
    )


def ultimo(registros):
    return registros[-1]


# =========================================
# FECHAS
# =========================================

def fecha_publica(fecha):
    """
    Agrupa las marcas temporales del
    historial angular en intervalos
    de cinco minutos.

    Se conserva la funcionalidad anterior.
    """

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


def fecha_exacta_utc(fecha):
    """
    Mantiene segundos reales de registro
    de ThingSpeak.

    No se utiliza para divulgar
    coordenadas GPS.
    """

    instante = datetime.fromisoformat(
        fecha.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    return instante.isoformat().replace(
        "+00:00", "Z"
    )


def ultimo_registro_thingspeak(*registros):
    """
    Obtiene la fecha mas reciente entre
    los tres canales.

    Corresponde a recepcion en ThingSpeak,
    no al reloj GPS del dispositivo.
    """

    fechas = [
        datetime.fromisoformat(
            r["created_at"].replace(
                "Z", "+00:00"
            )
        ).astimezone(timezone.utc)
        for r in registros
    ]

    return max(fechas).isoformat().replace(
        "+00:00", "Z"
    )


# =========================================
# HISTORIAL DE ORIENTACION
# =========================================

def construir_historial(registros):

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
            "el_objetivo": campo(registro, 5)
        }

    return [
        agrupados[fecha]
        for fecha in sorted(agrupados)
    ]


# =========================================
# NUEVO HISTORIAL DE LTR390
# FIELD 5 - IRRADIANCIA UV ESTIMADA
# =========================================

def construir_historial_uv(registros):
    """
    Conserva una muestra por publicacion
    valida, aproximadamente cada minuto.

    Publica exclusivamente:
    - Fecha de registro
    - Irradiancia UV estimada

    No expone los otros campos privados
    del canal Diagnostico.
    """

    historial = []

    for registro in registros:

        uv = campo(registro, 5, 3)

        if uv is None or uv < 0:
            continue

        historial.append({
            "t": fecha_exacta_utc(
                registro["created_at"]
            ),
            "uv": uv
        })

    return historial


# =========================================
# GPS GENERALIZADO
# MISMA LOGICA Y MISMO RADIO
# =========================================

def centro_aproximado(latitud, longitud):
    """
    Centro aproximado de una celda
    geográfica de unos 300 metros.

    No devuelve las coordenadas GPS
    originales del ESP32.
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

    Nunca publica el punto exacto.
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

    publico = {

        # Fecha del proceso de GitHub Actions
        "publicado_utc": datetime.now(
            timezone.utc
        ).replace(
            microsecond=0
        ).isoformat(),

        # Nueva fecha exacta del ultimo
        # registro recibido en ThingSpeak
        "ultimo_registro_utc":
            ultimo_registro_thingspeak(
                o, g, d
            ),

        # ==================================
        # ORIENTACION
        # ==================================

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

        # ==================================
        # GPS Y POSICION SOLAR
        # ==================================

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

            # Solamente coordenadas filtradas
            "ubicacion": ubicacion_aproximada(
                gps
            )
        },

        # ==================================
        # DIAGNOSTICO + LTR390
        # ==================================

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

            # NUEVO: LTR390
            # Field 5: UV estimada W/m2
            "uv_estimada": campo(
                d, 5, 3
            ),

            # Field 6: promedio cuentas UVS
            "uvs_promedio": campo(
                d, 6, 2
            ),

            # Field 7: estado de lecturas
            "ltr_valido": entero(
                d.get("field7")
            )

            # Field 8 no se hace publico.
        },

        # ==================================
        # HISTORIAL ANGULAR
        # ==================================

        "historial": construir_historial(
            orientacion
        ),

        # ==================================
        # NUEVO HISTORIAL UV
        # ==================================

        "historial_uv": construir_historial_uv(
            diagnostico
        )
    }

    # =====================================
    # GUARDAR JSON PUBLICO
    # =====================================

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

    print("Dashboard publico actualizado.")
    print(
        "Ultimo registro ThingSpeak:",
        publico["ultimo_registro_utc"]
    )
    print(
        "Registros de orientacion:",
        len(publico["historial"])
    )
    print(
        "Registros UV:",
        len(publico["historial_uv"])
    )
    print(
        "Radio GPS publico:",
        RADIO_PUBLICO_METROS,
        "metros"
    )
    print(
        "Coordenadas exactas GPS:",
        "NO PUBLICADAS"
    )
    print(
        "Field 8 comandos remotos:",
        "NO PUBLICADO"
    )


if __name__ == "__main__":
    main()
