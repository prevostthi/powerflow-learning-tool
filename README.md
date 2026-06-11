# powerflow-learning-tool
An interactive visual tool to explore and teach power flow in electric networks.


PowerFlow Learning Tool is an interactive visual application designed for teaching and understanding power flow in electric power systems.
It lets students and instructors:

Build simple transmission or distribution network examples
Configure loads, generators, and line parameters
Run power flow calculations and visualize voltages, flows, and losses
Experiment with “what‑if” scenarios to see how the grid reacts
Ideal for classroom demonstrations, labs, and self‑paced learning in power systems courses.



# ⚡ Meshed Power Grid Simulator

An interactive meshed power grid simulator featuring AC power flow calculation, π-model transmission lines, reactive power compensation, and circuit breaker switching operations.

The calculation engine is built on **PyPowSybl / OpenLoadFlow** (RTE's open-source library), and network data is stored in **IIDM format** — the native format of the Powsybl suite, compatible with Powsybl-Desktop, Dynawo, and the broader Powsybl ecosystem.

---

## Screenshots

> Main interface: 6-bus / 9-branch meshed network, π-model diagrams, power flows, node voltages, shunt elements, right-click switching.

---

## Features

### Network topology
- **6 buses** interconnected by **9 branches** forming a meshed network with a diagonal tie-line
- Each line is modelled using the **exact π equivalent circuit**: series resistance R and reactance X, shunt capacitive susceptance Bc/2 at each end, dielectric leakage conductance Gc

### Generation units
| ID | Name | IIDM `energySource` | Control mode |
|----|------|---------------------|--------------|
| SM1 | Synchronous Machine 1 (slack) | `NUCLEAR` | **PV** — voltage regulation |
| SM2 | Synchronous Machine 2 | `NUCLEAR` | **PV** — voltage regulation |
| WIND | Wind Farm | `WIND` | **PQ** — fixed P and Q setpoints |
| PVSOL | Photovoltaic Plant | `SOLAR` | **PQ** — fixed P and Q setpoints |

The `energySource` attribute is written into the IIDM file and can be consumed by any Powsybl tool. The PV/PQ mode is read from `voltage_regulator_on` in the network at solve time — not hardcoded in Python constants — so opening an external IIDM file with `HYDRO` or `THERMAL` units adapts automatically.

### Reactive power compensation (shunt elements)
- 2 **shunt capacitors** (B > 0): reactive power injection, voltage support
- 2 **shunt inductors** (B < 0): reactive power absorption, overvoltage limiting

### Power flow calculation
- **OpenLoadFlow** solver (RTE) via PyPowSybl
- Typical convergence: **2 iterations**
- DC values voltage initialisation
- Results: nodal voltages (p.u., kV, angle), P/Q flows on each branch, losses, thermal loading percentage

### Graphical interface (tkinter)
- **3-tab left panel**: Production / Load & Compensation / Results — all sliders update in real time
- **Interactive network canvas**: π-model symbols, P/Q flows, nodal voltages, shunt element symbols
- **Drop-down display menu**: 7 independently togglable layers (flows, losses, π schema, impedances, voltages, shunts, flow arrows)
- **Zoom + pan**: mouse-wheel zoom centred on cursor, +/− buttons, click-and-drag panning
- **Right-click** on any line or bus → open/close circuit breaker (switching to de-energised state)
- Automatic recalculation (120 ms debounce) after every slider change or switching operation

### IIDM file handling
- **Save** the current network state (setpoints + results) to a `.xiidm` file
- **Open** an existing `.xiidm` file and rerun the power flow
- **Export** results (voltages, flows) to JSON for post-processing

---

## Installation

### Prerequisites

- Python **3.9+**
- `tkinter` — bundled with Python on Windows and macOS

```bash
# Ubuntu / Debian
sudo apt install python3-tk
```

### Python dependencies

```bash
pip install pypowsybl numpy pandas
```

| Package | Tested version |
|---------|---------------|
| pypowsybl | 1.15.0 |
| numpy | 2.4.x |
| pandas | 3.0.x |

### Running the application

```bash
# Default network (built at startup)
python3 grid_powsybl.py

# Load an existing IIDM file
python3 grid_powsybl.py reseau_6noeuds.xiidm
```

---

## Project structure

```
.
├── grid_powsybl.py          # Main application (single file)
├── reseau_6noeuds.xiidm     # Example network in IIDM format
└── README.md
```

The application is intentionally contained in a single Python file for ease of exploration. It is split into two clearly separated layers:

```
grid_powsybl.py
│
├── Network / calculation layer  (≈ lines 1–320)
│   ├── NODES, LINES, GENERATORS, LOADS, SHUNTS  — topology and parameters
│   ├── build_network()     — builds a pypowsybl.Network from current setpoints
│   ├── run_loadflow()      — runs OLF, returns node_results + line_results
│   └── save_iidm() / load_iidm()  — IIDM export / import
│
└── GUI layer  (≈ lines 320–end)
    ├── class GridApp           — main tkinter application
    ├── _build_tabs()           — 3-tab left panel
    ├── _build_canvas_zone()    — canvas + display toolbar + zoom controls
    ├── run_simulation()        — sliders → calculation → display pipeline
    ├── draw_network()          — canvas rendering (buses, π lines, shunts)
    └── right-click / de-energise  — _on_right_click, _toggle_line, _toggle_node
```

---

## π line model

```
Bus i ──┬──────────[ R + jX ]──────────┬── Bus j
        │                              │
      jBc/2                          jBc/2
        │                              │
       GND                            GND
```

Parameters stored in the IIDM file (physical values, base 20 kV / 100 MVA, Z_base = 4 Ω):

| IIDM parameter | Unit | Description |
|----------------|------|-------------|
| `r` | Ω | Series resistance |
| `x` | Ω | Series reactance |
| `b1`, `b2` | S | Shunt susceptance at each end (= Bc_pu × Y_base / 2) |
| `g1`, `g2` | S | Dielectric leakage conductance |

---

## IIDM format

The `.xiidm` file is the native XML format of [Powsybl](https://www.powsybl.org/). It contains:

- **Topology**: substations, voltage levels, buses
- **Equipment**: generators with `energySource`, loads, shunt compensators, lines with π model
- **Setpoints**: `targetP`, `targetV`, `targetQ`, susceptance per section
- **Post-calculation results**: bus `v` and `angle`, equipment `p`, `q`, `i`

The format is directly compatible with:

| Tool | Use case |
|------|----------|

| [Dynawo](https://dynawo.github.io/) | Transient dynamic simulation |
| [PyPowSybl](https://pypowsybl.readthedocs.io/) | Security analysis, OPF, short-circuit |

---

## Example use cases

### Voltage regulation with shunt compensators
1. Increase the load on buses N5 and N6 until voltages drop below 0.95 p.u. (displayed in red)
2. Gradually increase the susceptance of CAP_N5 → observe the voltage recovery
3. Compare with raising the voltage setpoint of SM1

### N-1 contingency analysis
1. Right-click on line L1-5 → "Open circuit breakers"
2. Observe the load transfer onto L2-5 and the voltage change at N5
3. Check whether a thermal overload appears (line turns orange > 70 % or red > 90 %)

### Impact of renewables on reactive balance
1. Ramp the wind farm (WIND) up to its maximum output (80 MW)
2. Observe rising voltages and reactive power surplus in the network
3. Increase the inductance shunt IND_N2 to absorb the excess reactive power

### Bus de-energisation switching sequence
1. Right-click on bus N4 → "De-energise bus"
2. All adjacent lines (L2-4, L4-6) are opened automatically
3. The PV plant and shunt inductor IND_N4 are disconnected
4. The power flow immediately recalculates the degraded network state

---

## Extending with PyPowSybl

The IIDM file produced by this application can be fed directly into other PyPowSybl modules:

```python
import pypowsybl.network   as pn
import pypowsybl.security  as sa
import pypowsybl.shortcircuit as sc

# Load the network saved from the simulator
network = pn.load("reseau_6noeuds.xiidm")

# Automated N-1 security analysis
contingencies = sa.create_contingency_list(...)
results = sa.run_ac(network, contingencies)

# Short-circuit calculation
sc_results = sc.run(network, ...)
```

---

## References

- [PyPowSybl — Official documentation](https://pypowsybl.readthedocs.io/)
- [OpenLoadFlow — Algorithm description](https://www.powsybl.org/pages/documentation/simulation/powerflow/openlf.html)
- [IIDM format — XML specification](https://www.powsybl.org/pages/documentation/grid/formats/xiidm.html)
- [Powsybl — RTE open-source project](https://www.powsybl.org/)

---

## Licence

MIT
