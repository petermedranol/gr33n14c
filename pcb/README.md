# PCB — Greeniac

Diseño de placa(s) para el proyecto Greeniac (control de casa/invernadero sobre la Raspberry Pi).

## Entorno

- **KiCad 10.0.8** instalado en `C:\Program Files\KiCad\10.0\`.
- `kicad-cli.exe` — CLI para exportar Gerbers, SVG, PDF, correr DRC/ERC, etc.
- Python integrado con el módulo `pcbnew` en `C:\Program Files\KiCad\10.0\bin\python.exe`.

## Estructura

```
pcb/
  greeniac/              proyecto KiCad (HAT para Raspberry Pi)
    greeniac.kicad_pro   proyecto
    greeniac.kicad_sch   esquemático
    greeniac.kicad_pcb   placa: contorno 65x56, 4 barrenos y header 40-pin ya posicionados
  scripts/
    make_project.py      crea un proyecto KiCad en blanco (usa pcbnew)
    kcli.ps1             wrapper de kicad-cli
```

El proyecto `greeniac` parte de la plantilla oficial **RaspberryPi-HAT** que trae KiCad
(`...\share\kicad\template\RaspberryPi-HAT`), renombrada. Por eso ya cumple la mecánica
del HAT (tamaño, esquinas, barrenos y header de 40 pines en su posición exacta).

## Uso rápido (PowerShell)

```powershell
# versión
.\scripts\kcli.ps1 version

# correr DRC sobre la placa
.\scripts\kcli.ps1 pcb drc .\greeniac\greeniac.kicad_pcb

# preview SVG de la cara superior + contorno
.\scripts\kcli.ps1 pcb export svg --layers "F.Cu,Edge.Cuts" `
    --output .\greeniac\preview.svg .\greeniac\greeniac.kicad_pcb

# scripting directo con pcbnew
& "C:\Program Files\KiCad\10.0\bin\python.exe" .\scripts\make_project.py <dir> <nombre>
```

## Objetivo de la placa

HAT para la Raspberry Pi con **relés para actuadores** del invernadero
(riego, ventilación, calefacción, luces).

## Estado

- [x] KiCad 10.0.8 detectado y funcionando (CLI + `pcbnew`).
- [x] Proyecto `greeniac` creado desde la plantilla oficial RaspberryPi-HAT.
- [x] Mecánica del HAT lista (contorno, barrenos, header 40-pin).
- [ ] Definir nº de canales de relé y GPIOs asignados.
- [ ] Esquemático de la etapa de relés (driver + optoacoplador + diodo de rueda libre).
- [ ] Ruteo, DRC limpio y Gerbers para fabricación.

> Las violaciones DRC/ERC actuales provienen de la plantilla de referencia (GPIOs del
> header sin conectar, EEPROM de ejemplo); se van resolviendo al cablear el circuito.

> Nota: para editar a mano abre `greeniac.kicad_pro` con `kicad.exe`. Yo puedo
> generar/modificar la placa por script con `pcbnew` y validar con `kicad-cli`.
