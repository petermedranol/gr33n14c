# Greeniac — Placa controladora (diseño)

Placa controladora del invernadero que se monta sobre la Raspberry Pi por el header de
40 pines. Ya **no** es un HAT estándar (crece por el DevKitC + 8 relés); es una placa
custom (~110×90 mm) que se conecta a la Pi con separadores y sobresale.

## Arquitectura

```
          +5V ext (2-3A)                    cargas (bomba, ventilación, luz, calefacción...)
               │                                  ▲  (contactos del relé = aislamiento a mains)
               ▼                                  │
  Raspberry Pi 40-pin ──┐                  ┌── 8× relé SRD-05VDC ── borneras
                        │                  │
  ESP32 DevKitC ────────┤   OR por canal   │   ULN2803A (×1, 8 canales,
   (socket 2×19)        ├── (diodos) ──────┴──  diodos de rueda libre integrados)
                        │
  Pi ⇄ ESP32: UART + I2C (GND común)
```

- **Control redundante ("ambos pueden"):** cada entrada del ULN2803 recibe un OR con
  diodos (1N4148) desde un GPIO de la Pi y un GPIO del ESP32, con pull-down 10k a GND.
  Cualquiera enciende el relé; por defecto OFF. (Alternativa: jumper selector por canal.)
- **Driver:** 1× **ULN2803A** maneja los 8 relés (Darlington + clamp diodes internos).
- **Aislamiento:** lo dan los **contactos del relé** (carga ↔ lógica). Opto en el control
  sería redundante porque Pi/ESP32/relés comparten GND; queda como opción.

## Alimentación

| Dominio | Fuente | Notas |
|---|---|---|
| Lógica Pi | 40-pin (3V3 / 5V) | la Pi se alimenta por su propio USB-C |
| Bobinas relé (5V, ~8×70mA) | **entrada 5V externa** (barrel + bornera) | NO tomar 8 relés del 5V de la Pi |
| ESP32 DevKitC | 5V de la placa (pin VIN/5V) | LDO interno a 3V3 |
| GND | **común** a todo | requisito para UART/I2C |

## Mapeo de pines (propuesta)

Relés R1..R8. Cada relé lo puede encender la Pi **o** el ESP32 (OR por diodos).

| Relé | GPIO Pi (BCM) | Pin fís. Pi | GPIO ESP32 | Carga sugerida |
|------|---------------|-------------|------------|----------------|
| R1 | GPIO5  | 29 | IO4  | Bomba de riego |
| R2 | GPIO6  | 31 | IO5  | Electroválvula |
| R3 | GPIO13 | 33 | IO13 | Ventilación |
| R4 | GPIO16 | 36 | IO14 | Extractor |
| R5 | GPIO19 | 35 | IO16 | Calefacción |
| R6 | GPIO20 | 38 | IO17 | Luz crecimiento |
| R7 | GPIO21 | 40 | IO18 | Nebulizador |
| R8 | GPIO26 | 37 | IO19 | Auxiliar |

Comunicación Pi ⇄ ESP32 (GND común):
- **UART:** Pi GPIO14/15 (TXD/RXD, pines 8/10) ⇄ ESP32 RX0/TX0.
- **I2C:** Pi GPIO2/3 (SDA/SCL, pines 3/5) ⇄ ESP32 IO21/IO22.
- Sensores analógicos al ESP32 (ADC): IO32/33/34/35/36/39 a header/bornera.

> Pines ESP32 elegidos evitando los strapping sensibles al boot (0, 2, 12, 15).

## BOM preliminar

- 1× Raspberry Pi 40-pin header hembra (ya en la placa base)
- 1× socket 2×19 (2.54 mm) para ESP32 DevKitC (hembra, removible)
- 8× relé SRD-05VDC-SL-C (SPDT, bobina 5V)
- 1× ULN2803A (DIP-18 o SOIC-18)
- 16× diodo 1N4148 (OR por canal)
- 8× R 10k (pull-down) + 8× R 1k (si se usa opto opcional)
- 8× bornera 3 pos. 5.08 mm (NO/COM/NC por relé)
- 1× bornera 2 pos. + barrel jack 5V (entrada de potencia)
- Condensadores de desacoplo (100nF ×varios, 470µF bulk en 5V)
- 8× LED indicador por relé (opcional) + R 1k

## Estado / plan de construcción (por etapas, validando con kicad-cli)

- [x] Base KiCad y conexión verificada.
- [ ] Redimensionar contorno a ~110×90 mm, reubicar header Pi + barrenos.
- [ ] Colocar socket DevKitC, matriz de 8 relés y ULN2803.
- [ ] Esquemático: alimentación, OR por diodos, ULN→relés, comms Pi/ESP32.
- [ ] Asignar netlist, rutear, DRC/ERC limpios.
- [ ] Exportar Gerbers + BOM + posiciones para fabricación.
