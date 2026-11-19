#!/usr/bin/env python3
"""Prueba de que el flujo local -> Pi funciona."""
import platform
import socket

print("¡Hola desde la Raspberry Pi!")
print(f"Equipo:  {socket.gethostname()}")
print(f"Sistema: {platform.system()} {platform.release()}")
print(f"Python:  {platform.python_version()}")
print(f"Arq.:    {platform.machine()}")
