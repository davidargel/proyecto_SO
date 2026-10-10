"""
catalogo.py — Datos del escenario: catálogo central de la biblioteca universitaria.

Cada título tiene un número FIJO de copias físicas. Ese número es el valor inicial
del threading.Semaphore del título (semáforo contador): nunca puede haber más
préstamos simultáneos que copias.

Los ISBN son códigos de ejemplo (ficticios); lo importante es que definen un
ORDEN TOTAL entre recursos, que el modo normal usa para prevenir la espera circular.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Titulo:
    isbn: str          # identificador y criterio de orden global (modo normal)
    titulo: str        # título completo
    autor: str
    copias: int        # copias físicas = valor inicial del semáforo
    corto: str         # nombre corto para el grafo y los logs
    popular: bool      # los títulos "de hora pico" (1 copia) generan la contención


CATALOGO = [
    Titulo("978-0-0000-0001-1", "Sistemas Operativos Modernos", "A. S. Tanenbaum", 1, "SO Modernos", True),
    Titulo("978-0-0000-0002-8", "Fundamentos de Sistemas Operativos", "A. Silberschatz", 2, "Silberschatz", False),
    Titulo("978-0-0000-0003-5", "Redes de Computadoras", "J. Kurose", 1, "Redes", True),
    Titulo("978-0-0000-0004-2", "Fundamentos de Bases de Datos", "H. Korth", 1, "Bases de Datos", True),
    Titulo("978-0-0000-0005-9", "Cálculo de una Variable", "J. Stewart", 3, "Cálculo", False),
    Titulo("978-0-0000-0006-6", "Introducción a los Algoritmos", "T. Cormen", 2, "Algoritmos", False),
]

# Recurso adicional: estaciones (mostradores) de préstamo compartidas por todas las sucursales.
ID_ESTACIONES = "ESTACIONES"
NUM_ESTACIONES = 4

# Título usado por la prueba de condición de carrera (3 copias, muchas reservas en línea).
ISBN_CARRERA = "978-0-0000-0005-9"

SUCURSALES = ["Central", "Chimaltenango", "Villa Nueva", "Antigua", "Mixco", "Zona 1"]

POR_ISBN = {t.isbn: t for t in CATALOGO}


def nombre_recurso(rid: str) -> str:
    """Nombre corto legible de un recurso (título o estaciones)."""
    if rid == ID_ESTACIONES:
        return "Estaciones"
    t = POR_ISBN.get(rid)
    return t.corto if t else rid
