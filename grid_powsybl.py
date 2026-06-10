#!/usr/bin/env python3
"""
Simulateur de Réseau Électrique — PyPowSybl + IIDM
Load flow OpenLoadFlow (RTE), stockage IIDM natif, interface tkinter
Usage : python3 grid_powsybl.py [reseau.xiidm]
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, math, os, sys, tempfile
import numpy as np
import pandas as pd
import pypowsybl.network  as pn
import pypowsybl.loadflow as plf

# ═══════════════════════════════════════════════════════════
#  COUCHE RÉSEAU — création, lecture, écriture IIDM
# ═══════════════════════════════════════════════════════════

BASE_MVA = 100.0
BASE_KV  = 20.0
Z_BASE   = BASE_KV**2 / BASE_MVA   # 4 Ω
Y_BASE   = 1.0 / Z_BASE             # 0.25 S

# ── Description statique du réseau (topologie + paramètres)
# Ces dicts sont la "vérité terrain" ; le fichier IIDM en est l'export.

NODES = [
    {"id":"N1","name":"Noeud 1 - SM1",    "type":"slack","x":200,"y":120,"vl":"VL1","bus":"B1","sub":"S1"},
    {"id":"N2","name":"Noeud 2 - SM2",    "type":"pv",   "x":620,"y":120,"vl":"VL2","bus":"B2","sub":"S2"},
    {"id":"N3","name":"Noeud 3 - Eolien", "type":"pv",   "x":200,"y":380,"vl":"VL3","bus":"B3","sub":"S3"},
    {"id":"N4","name":"Noeud 4 - PV Sol", "type":"pq",   "x":620,"y":380,"vl":"VL4","bus":"B4","sub":"S4"},
    {"id":"N5","name":"Noeud 5 - Charge A","type":"pq",  "x":410,"y":200,"vl":"VL5","bus":"B5","sub":"S5"},
    {"id":"N6","name":"Noeud 6 - Charge B","type":"pq",  "x":410,"y":310,"vl":"VL6","bus":"B6","sub":"S6"},
]

GENERATORS = [
    {"id":"SM1", "node":"N1","name":"Machine Sync. 1","type":"synchronous",
     "P_mw":80,"V_pu":1.02,"P_min":10,"P_max":150,"V_min":0.95,"V_max":1.05},
    {"id":"SM2", "node":"N2","name":"Machine Sync. 2","type":"synchronous",
     "P_mw":60,"V_pu":1.01,"P_min":10,"P_max":120,"V_min":0.95,"V_max":1.05},
    {"id":"WIND","node":"N3","name":"Parc Eolien",    "type":"wind",
     "P_mw":30,"Q_mvar":5,"P_min":0,"P_max":80,"Q_min":-20,"Q_max":20},
    {"id":"PVSOL","node":"N4","name":"Centrale PV",   "type":"solar",
     "P_mw":25,"Q_mvar":0,"P_min":0,"P_max":60,"Q_min":-15,"Q_max":15},
]

LOADS = [
    {"id":"LOAD_A","node":"N5","name":"Charge Industrielle A","P_mw":50,"Q_mvar":15},
    {"id":"LOAD_B","node":"N6","name":"Charge Residentielle B","P_mw":40,"Q_mvar":12},
]

SHUNTS = [
    {"id":"CAP_N5","node":"N5","name":"Batterie Capa N5","type":"capacitor",
     "B_pu":0.05,"B_min":-0.0,"B_max":0.30},
    {"id":"CAP_N6","node":"N6","name":"Batterie Capa N6","type":"capacitor",
     "B_pu":0.04,"B_min": 0.0,"B_max":0.25},
    {"id":"IND_N2","node":"N2","name":"Reactance shunt N2","type":"inductor",
     "B_pu":-0.03,"B_min":-0.20,"B_max":0.0},
    {"id":"IND_N4","node":"N4","name":"Bobine shunt N4","type":"inductor",
     "B_pu":-0.02,"B_min":-0.15,"B_max":0.0},
]

LINES = [
    {"id":"L1-2","from":"N1","to":"N2","name":"Ligne 1-2 Nord",
     "R_pu":0.02,"X_pu":0.06,"Bc_pu":0.04,"Gc_pu":0.0002,"rating_mva":80},
    {"id":"L1-3","from":"N1","to":"N3","name":"Ligne 1-3 Ouest",
     "R_pu":0.03,"X_pu":0.08,"Bc_pu":0.03,"Gc_pu":0.0001,"rating_mva":60},
    {"id":"L1-5","from":"N1","to":"N5","name":"Ligne 1-5 Centre-H",
     "R_pu":0.015,"X_pu":0.05,"Bc_pu":0.025,"Gc_pu":0.0001,"rating_mva":70},
    {"id":"L2-5","from":"N2","to":"N5","name":"Ligne 2-5 Centre-H",
     "R_pu":0.015,"X_pu":0.05,"Bc_pu":0.025,"Gc_pu":0.0001,"rating_mva":70},
    {"id":"L2-4","from":"N2","to":"N4","name":"Ligne 2-4 Est",
     "R_pu":0.025,"X_pu":0.07,"Bc_pu":0.035,"Gc_pu":0.00015,"rating_mva":65},
    {"id":"L3-6","from":"N3","to":"N6","name":"Ligne 3-6 Sud-O",
     "R_pu":0.02,"X_pu":0.055,"Bc_pu":0.028,"Gc_pu":0.0001,"rating_mva":55},
    {"id":"L4-6","from":"N4","to":"N6","name":"Ligne 4-6 Sud-E",
     "R_pu":0.022,"X_pu":0.06,"Bc_pu":0.030,"Gc_pu":0.00012,"rating_mva":55},
    {"id":"L5-6","from":"N5","to":"N6","name":"Ligne 5-6 Centre-V",
     "R_pu":0.01,"X_pu":0.04,"Bc_pu":0.016,"Gc_pu":0.00008,"rating_mva":60},
    {"id":"L3-5","from":"N3","to":"N5","name":"Ligne 3-5 Diagonale",
     "R_pu":0.025,"X_pu":0.07,"Bc_pu":0.035,"Gc_pu":0.00015,"rating_mva":50},
]

NODE_BY_ID = {n["id"]: n for n in NODES}
GEN_BY_ID  = {g["id"]: g for g in GENERATORS}
LOAD_BY_ID = {l["id"]: l for l in LOADS}
SH_BY_ID   = {s["id"]: s for s in SHUNTS}


def build_network(gen_setpoints: dict, load_setpoints: dict,
                  shunt_setpoints: dict,
                  open_lines: set = None,
                  open_nodes: set = None) -> pn.Network:
    """
    Construit un objet pypowsybl.Network à partir des consignes courantes.
    gen_setpoints  : {gen_id: {"P_mw":..., "V_pu":... ou "Q_mvar":...}}
    load_setpoints : {load_id: {"P_mw":..., "Q_mvar":...}}
    shunt_setpoints: {shunt_id: B_pu}
    open_lines     : set d'ids de lignes à ouvrir (disjoncteurs ouverts)
    open_nodes     : set d'ids de nœuds à déconnecter
    """
    if open_lines is None: open_lines = set()
    if open_nodes is None: open_nodes = set()
    net = pn.create_empty("reseau_6n")

    # Substations + voltage levels
    net.create_substations(id=[nd["sub"] for nd in NODES])
    net.create_voltage_levels(
        id              =[nd["vl"]  for nd in NODES],
        substation_id   =[nd["sub"] for nd in NODES],
        topology_kind   =['BUS_BREAKER']*len(NODES),
        nominal_v       =[BASE_KV]*len(NODES))
    for nd in NODES:
        net.create_buses(id=[nd["bus"]], voltage_level_id=[nd["vl"]])

    # Générateurs
    for g in GENERATORS:
        sp = gen_setpoints.get(g["id"], {})
        P  = sp.get("P_mw",  g["P_mw"])
        V  = sp.get("V_pu",  g.get("V_pu",1.0)) * BASE_KV
        Q  = sp.get("Q_mvar",g.get("Q_mvar",0.0))
        reg = g["type"] == "synchronous"
        nd  = NODE_BY_ID[g["node"]]
        net.create_generators(
            id=[g["id"]], voltage_level_id=[nd["vl"]], bus_id=[nd["bus"]],
            target_p=[P], target_q=[Q], target_v=[V],
            voltage_regulator_on=[reg],
            min_p=[g["P_min"]], max_p=[g["P_max"]])

    # Charges
    for l in LOADS:
        sp = load_setpoints.get(l["id"], {})
        P  = sp.get("P_mw",  l["P_mw"])
        Q  = sp.get("Q_mvar",l["Q_mvar"])
        nd = NODE_BY_ID[l["node"]]
        net.create_loads(id=[l["id"]], voltage_level_id=[nd["vl"]],
                         bus_id=[nd["bus"]], p0=[P], q0=[Q])

    # Shunts
    if SHUNTS:
        shunt_rows = []
        linear_rows = []
        for sh in SHUNTS:
            B_pu = shunt_setpoints.get(sh["id"], sh["B_pu"])
            B_si = B_pu * Y_BASE
            nd   = NODE_BY_ID[sh["node"]]
            shunt_rows.append({
                "id": sh["id"],
                "voltage_level_id": nd["vl"],
                "bus_id": nd["bus"],
                "model_type": "LINEAR",
                "section_count": 1,
                "target_v": BASE_KV,
                "target_deadband": 0.5,
            })
            linear_rows.append({
                "id": sh["id"],
                "g_per_section": 0.0,
                "b_per_section": B_si,
                "max_section_count": 1,
            })
        sh_df  = pd.DataFrame(shunt_rows ).set_index("id")
        lin_df = pd.DataFrame(linear_rows).set_index("id")
        net.create_shunt_compensators(sh_df, lin_df)

    # Lignes (modèle π : r,x en Ω physiques, b1=b2=Bc/2 en S physiques)
    net.create_lines(
        id                =[l["id"]          for l in LINES],
        bus1_id           =[NODE_BY_ID[l["from"]]["bus"] for l in LINES],
        voltage_level1_id =[NODE_BY_ID[l["from"]]["vl"]  for l in LINES],
        bus2_id           =[NODE_BY_ID[l["to"]]["bus"]   for l in LINES],
        voltage_level2_id =[NODE_BY_ID[l["to"]]["vl"]    for l in LINES],
        r  =[l["R_pu"] *Z_BASE        for l in LINES],
        x  =[l["X_pu"] *Z_BASE        for l in LINES],
        b1 =[l["Bc_pu"]*Y_BASE/2      for l in LINES],
        b2 =[l["Bc_pu"]*Y_BASE/2      for l in LINES],
        g1 =[l["Gc_pu"]*Y_BASE/2      for l in LINES],
        g2 =[l["Gc_pu"]*Y_BASE/2      for l in LINES],
    )
    # ── Déconnexion des ouvrages hors tension ────────────────
    # Lignes ouvertes : déconnecter les deux extrémités
    for line_id in open_lines:
        try:
            net.disconnect(line_id)
        except Exception:
            pass   # ligne inexistante ou déjà ouverte

    # Nœuds hors tension : ouvrir toutes les lignes connectées
    # (pypowsybl ne permet pas de déconnecter un bus directement ;
    #  on ouvre toutes les lignes adjacentes, ce qui isole le nœud)
    for node_id in open_nodes:
        for line in LINES:
            if line["from"] == node_id or line["to"] == node_id:
                try:
                    net.disconnect(line["id"])
                except Exception:
                    pass
        # Déconnecter aussi les injections (generateur, charge, shunt) sur ce nœud
        for g in GENERATORS:
            if g["node"] == node_id:
                try: net.disconnect(g["id"])
                except Exception: pass
        for l in LOADS:
            if l["node"] == node_id:
                try: net.disconnect(l["id"])
                except Exception: pass
        for sh in SHUNTS:
            if sh["node"] == node_id:
                try: net.disconnect(sh["id"])
                except Exception: pass

    return net


def run_loadflow(net: pn.Network):
    """Lance le load flow AC OpenLoadFlow. Retourne (résultats_bus, résultats_lignes, statut)."""
    params = plf.Parameters(
        distributed_slack    = False,
        voltage_init_mode    = plf.VoltageInitMode.DC_VALUES,
        balance_type         = plf.BalanceType.PROPORTIONAL_TO_GENERATION_P_MAX,
    )
    lf_res = plf.run_ac(net, parameters=params)
    status = lf_res[0].status
    iters  = lf_res[0].iteration_count

    # Résultats bus
    buses_raw = net.get_buses()[["v_mag","v_angle"]]
    node_results = {}
    for nd in NODES:
        vl_bus = nd["vl"] + "_0"   # convention pypowsybl : VL1_0
        if vl_bus in buses_raw.index:
            row = buses_raw.loc[vl_bus]
            V   = row["v_mag"] / BASE_KV
            ang = row["v_angle"]
        else:
            V, ang = 1.0, 0.0
        node_results[nd["id"]] = {
            "V_pu":      V,
            "theta_deg": ang,
            "V_kv":      V * BASE_KV,
        }

    # Résultats générateurs (P, Q réellement injectés)
    gens_raw = net.get_generators()[["p","q"]]
    for g in GENERATORS:
        gid = g["id"]
        if gid in gens_raw.index:
            # pypowsybl convention : p = injection donc P_mw = -p (load convention → generator)
            node_results[g["node"]]["P_gen_mw"]  = -gens_raw.loc[gid,"p"]
            node_results[g["node"]]["Q_gen_mvar"] = -gens_raw.loc[gid,"q"]

    # Résultats lignes
    lines_raw  = net.get_lines()[["p1","q1","p2","q2","i1","i2"]]
    line_results = {}
    for l in LINES:
        lid = l["id"]
        if lid in lines_raw.index:
            row = lines_raw.loc[lid]
            # Taux de charge thermique : I1 en A → p.u. approx
            I1_pu = row["i1"] / (BASE_MVA / (math.sqrt(3)*BASE_KV)*1000) \
                    if row["i1"] == row["i1"] else 0.0
            loading = I1_pu / (l["rating_mva"]/BASE_MVA) * 100 if I1_pu>0 else 0.0
            P_loss  = row["p1"] + row["p2"]   # pertes = somme algébrique des transits
            Q_loss  = row["q1"] + row["q2"]
            line_results[lid] = {
                "P_from": row["p1"],  "Q_from": row["q1"],
                "P_to":   row["p2"],  "Q_to":   row["q2"],
                "P_loss": P_loss,     "Q_loss": Q_loss,
                "loading_pct": loading,
            }
        else:
            line_results[lid] = {"P_from":0,"Q_from":0,"P_to":0,"Q_to":0,
                                  "P_loss":0,"Q_loss":0,"loading_pct":0}

    converged = (status == plf.ComponentStatus.CONVERGED)
    return node_results, line_results, converged, iters, status


def save_iidm(net: pn.Network, path: str):
    """Exporte le réseau au format IIDM (.xiidm)."""
    net.dump(path)


def load_iidm(path: str) -> pn.Network:
    """Charge un fichier IIDM."""
    return pn.load(path)


# ═══════════════════════════════════════════════════════════
#  CONSTANTES GRAPHIQUES
# ═══════════════════════════════════════════════════════════

BG     = "#0d1117"; PANEL  = "#161b22"; CARD   = "#1c2128"; BORDER = "#30363d"
T_PRI  = "#e6edf3"; T_SEC  = "#8b949e"
BLUE   = "#58a6ff"; GREEN  = "#3fb950"; AMBER  = "#d29922"; RED    = "#f85149"
TEAL   = "#39d353"; PURPLE = "#bc8cff"; ORANGE = "#ffa657"
CYAN   = "#56d3f7"; PINK   = "#ff79c6"

FONT_SCALE = 2

def mono(size, bold=False):
    size = max(1, round(size * FONT_SCALE))
    for fam in ("Consolas","DejaVu Sans Mono","Liberation Mono",
                "Courier New","Courier","monospace"):
        try:
            f = tk.font.Font(family=fam, size=size,
                             weight="bold" if bold else "normal")
            if f.actual("family").lower() not in ("helvetica","fixed",""):
                return (fam, size, "bold" if bold else "normal")
        except Exception:
            pass
    return ("Courier", size, "bold" if bold else "normal")


# ═══════════════════════════════════════════════════════════
#  APPLICATION PRINCIPALE
# ═══════════════════════════════════════════════════════════

class GridApp:

    ZOOM_MIN  = 0.3; ZOOM_MAX = 5.0; ZOOM_STEP = 1.15
    DW, DH    = 820, 500

    def __init__(self, root, iidm_path=None):
        self.root        = root
        self.iidm_path   = iidm_path        # fichier courant (None = nouveau)
        self.node_results = {}
        self.line_results = {}
        self.converged    = False
        self.lf_status    = ""
        self.gen_vars     = {}
        self.load_vars    = {}
        self.shunt_vars   = {}
        self._show        = {}
        self._after_id    = None
        self._zoom        = 1.0
        self._pan_x       = 0.0; self._pan_y = 0.0
        self._drag_start  = None
        self._menu_win    = None

        # Ouvrages hors tension (disjoncteurs ouverts)
        self._open_lines  = set()   # ids de lignes ouvertes
        self._open_nodes  = set()   # ids de nœuds déconnectés

        self._build_ui()
        self.root.after(250, self.run_simulation)

    # ══════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════

    def _build_ui(self):
        self.root.title("Simulateur Réseau — PyPowSybl / IIDM")
        self.root.configure(bg=BG)
        self.root.geometry("1400x900"); self.root.minsize(900,650)

        # Barre de titre
        bar = tk.Frame(self.root, bg=PANEL, height=60)
        bar.pack(fill='x'); bar.pack_propagate(False)
        tk.Label(bar, text="  SIMULATEUR RESEAU  —  PyPowSybl / OpenLoadFlow / IIDM",
                 font=mono(11,True), fg=BLUE, bg=PANEL).pack(side='left',padx=8,pady=10)
        self.status_lbl = tk.Label(bar, text="  En attente...",
                                   font=mono(10), fg=T_SEC, bg=PANEL)
        self.status_lbl.pack(side='left')
        # Boutons fichier à droite
        for txt, cmd in [("Sauver IIDM", self._save_iidm),
                         ("Ouvrir IIDM", self._open_iidm),
                         ("Exporter JSON", self._export_json)]:
            tk.Button(bar, text=txt, command=cmd,
                      font=mono(8), fg=T_PRI, bg=CARD, activebackground=BORDER,
                      relief='flat', bd=0, padx=8, pady=3, cursor='hand2'
                      ).pack(side='right', padx=4, pady=10)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True)

        # Panneau gauche à onglets
        left = tk.Frame(body, bg=PANEL, width=440,
                        highlightbackground=BORDER, highlightthickness=1)
        left.pack(side='left', fill='y', padx=(6,3), pady=6)
        left.pack_propagate(False)
        self._build_tabs(left)

        # Canvas
        ctr = tk.Frame(body, bg=BG)
        ctr.pack(side='left', fill='both', expand=True, padx=3, pady=6)
        self._build_canvas_zone(ctr)

    # ── Onglets ────────────────────────────────────────────────

    def _build_tabs(self, parent):
        style = ttk.Style()
        style.configure('Dark.TNotebook', background=PANEL, borderwidth=0)
        style.configure('Dark.TNotebook.Tab', background=CARD, foreground=T_SEC,
                        padding=[8,5], font=mono(8,True))
        style.map('Dark.TNotebook.Tab',
                  background=[('selected',BORDER)],
                  foreground=[('selected',T_PRI)])

        nb = ttk.Notebook(parent, style='Dark.TNotebook')
        nb.pack(fill='both', expand=True, padx=4, pady=4)

        t1=tk.Frame(nb,bg=PANEL); nb.add(t1, text='  Production  ')
        t2=tk.Frame(nb,bg=PANEL); nb.add(t2, text=' Conso & Comp ')
        t3=tk.Frame(nb,bg=PANEL); nb.add(t3, text='  Resultats   ')

        self._build_prod_tab(t1)
        self._build_conso_tab(t2)
        self._build_results_tab(t3)

    def _build_prod_tab(self, parent):
        tk.Label(parent,text="SOURCES DE PRODUCTION",font=mono(9,True),
                 fg=BLUE,bg=PANEL).pack(pady=(8,2))
        inner = self._scrollable(parent)
        self._sep(inner,"Machines Synchrones")
        for g in GENERATORS:
            if g["type"]=="synchronous": self._sync_widget(inner,g)
        self._sep(inner,"Sources Renouvelables")
        for g in GENERATORS:
            if g["type"] in ("wind","solar"): self._ren_widget(inner,g)

    def _build_conso_tab(self, parent):
        tk.Label(parent,text="CHARGES  &  COMPENSATION",font=mono(9,True),
                 fg=RED,bg=PANEL).pack(pady=(8,2))
        inner = self._scrollable(parent)
        self._sep(inner,"Charges")
        for l in LOADS: self._load_widget(inner,l)
        self._sep(inner,"Elements Shunt (reglage tension)")
        for sh in SHUNTS: self._shunt_widget(inner,sh)

    def _build_results_tab(self, parent):
        tk.Label(parent,text="RESULTATS — PyPowSybl OLF",font=mono(9,True),
                 fg=GREEN,bg=PANEL).pack(pady=(8,2))
        inner = self._scrollable(parent)

        self._sep(inner,"Bilan Reseau")
        bf=tk.Frame(inner,bg=CARD,highlightbackground=BORDER,highlightthickness=1)
        bf.pack(fill='x',padx=8,pady=3)
        self._blbls={}
        for k,lbl in [("P_gen","Prod active"),("P_load","Conso active"),
                       ("P_loss","Pertes act."),("Q_gen","Prod reactive"),
                       ("Q_load","Conso react."),("Q_shunt","Q shunts")]:
            fr=tk.Frame(bf,bg=CARD); fr.pack(fill='x',padx=6,pady=2)
            tk.Label(fr,text=lbl+" :",font=mono(8),fg=T_SEC,bg=CARD,
                     width=14,anchor='w').pack(side='left')
            v=tk.Label(fr,text="--",font=mono(8,True),fg=T_PRI,bg=CARD)
            v.pack(side='right',padx=2); self._blbls[k]=v

        self._sep(inner,"Tensions aux Noeuds")
        vf=tk.Frame(inner,bg=CARD,highlightbackground=BORDER,highlightthickness=1)
        vf.pack(fill='x',padx=8,pady=3)
        self._vlbls={}
        for nd in NODES:
            fr=tk.Frame(vf,bg=CARD); fr.pack(fill='x',padx=6,pady=2)
            tk.Label(fr,text=f"{nd['id']} {nd['name'].split('-')[0].strip()}:",
                     font=mono(7),fg=T_SEC,bg=CARD,width=16,anchor='w').pack(side='left')
            v=tk.Label(fr,text="--",font=mono(7,True),fg=T_PRI,bg=CARD)
            v.pack(side='right',padx=2); self._vlbls[nd["id"]]=v

        self._sep(inner,"Flux sur les Lignes")
        lf=tk.Frame(inner,bg=CARD,highlightbackground=BORDER,highlightthickness=1)
        lf.pack(fill='x',padx=8,pady=3)
        self._lflbls={}
        for line in LINES:
            fr=tk.Frame(lf,bg=CARD); fr.pack(fill='x',padx=6,pady=2)
            tk.Label(fr,text=f"{line['id']}:",font=mono(7),fg=T_SEC,bg=CARD,
                     width=7,anchor='w').pack(side='left')
            v=tk.Label(fr,text="--",font=mono(7,True),fg=T_PRI,bg=CARD)
            v.pack(side='right',padx=2); self._lflbls[line["id"]]=v

        self._conv_lbl=tk.Label(inner,text="Statut: --",
                                font=mono(8),fg=T_SEC,bg=PANEL)
        self._conv_lbl.pack(pady=4)

        # Bouton info solveur
        tk.Label(inner,text="Solveur : OpenLoadFlow (RTE/Powsybl)",
                 font=mono(7),fg=T_SEC,bg=PANEL).pack(pady=2)

    # ── Canvas + toolbar ───────────────────────────────────────

    def _build_canvas_zone(self, parent):
        # Toolbar compacte
        toolbar = tk.Frame(parent,bg=PANEL,
                           highlightbackground=BORDER,highlightthickness=1)
        toolbar.pack(fill='x',pady=(0,4))

        self._checks_def = [
            ('flux',       'Flux P/Q lignes',     BLUE),
            ('pertes',     'Pertes lignes',        AMBER),
            ('pi_schema',  'Schema en pi (Bc/2)', CYAN),
            ('impedances', 'Impedances R/X',       ORANGE),
            ('tensions',   'Tensions noeuds',      GREEN),
            ('shunts',     'Shunts (C/L)',         PINK),
            ('fleches',    'Fleches de flux',      TEAL),
        ]
        for key,_,_ in self._checks_def:
            self._show[key] = tk.BooleanVar(value=True)

        self._disp_btn = tk.Button(toolbar, text="  Affichage  v",
            font=mono(8,True), fg=T_PRI, bg=CARD, activebackground=BORDER,
            relief='flat', bd=0, padx=10, pady=4, cursor='hand2',
            command=self._open_display_menu)
        self._disp_btn.pack(side='left',padx=(8,4),pady=6)

        tk.Frame(toolbar,bg=BORDER,width=1).pack(side='left',fill='y',padx=8,pady=4)

        tk.Label(toolbar,text="ZOOM :",font=mono(8,True),
                 fg=T_SEC,bg=PANEL).pack(side='left',padx=(4,2),pady=6)
        bst=dict(font=mono(10,True),fg=T_PRI,bg=CARD,activebackground=BORDER,
                 relief='flat',bd=0,width=2,cursor='hand2')
        tk.Button(toolbar,text="-",command=self.zoom_out,**bst).pack(side='left',padx=2,pady=4)
        self._zoom_lbl=tk.Label(toolbar,text="100%",font=mono(8,True),
                                fg=BLUE,bg=PANEL,width=5)
        self._zoom_lbl.pack(side='left',padx=2)
        tk.Button(toolbar,text="+",command=self.zoom_in,**bst).pack(side='left',padx=2,pady=4)
        tk.Button(toolbar,text="Reset vue",command=self.zoom_reset,
                  font=mono(8),fg=T_SEC,bg=CARD,activebackground=BORDER,
                  relief='flat',bd=0,padx=6,pady=2,cursor='hand2'
                  ).pack(side='left',padx=6,pady=4)

        # Canvas
        self.canvas=tk.Canvas(parent,bg=BG,highlightbackground=BORDER,
                              highlightthickness=1,cursor='fleur')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',  lambda e: self.root.after(80,self.draw_network))
        self.canvas.bind('<Button-4>',   self._wheel_up)
        self.canvas.bind('<Button-5>',   self._wheel_down)
        self.canvas.bind('<MouseWheel>', self._wheel_win)
        self.canvas.bind('<ButtonPress-1>',  self._drag_start_cb)
        self.canvas.bind('<B1-Motion>',      self._drag_move)
        self.canvas.bind('<ButtonRelease-1>',self._drag_end)
        # Clic droit → menu contextuel ouvrage
        self.canvas.bind('<Button-3>',       self._on_right_click)

        # Légende
        leg=tk.Frame(parent,bg=PANEL,height=34,
                     highlightbackground=BORDER,highlightthickness=1)
        leg.pack(fill='x',pady=(4,0)); leg.pack_propagate(False)
        for txt,col in [("[SM]Slack",BLUE),("[SM]PV",GREEN),("[Eo]Eolien",PURPLE),
                         ("[PV]Sol",AMBER),("[Ch]Charge",RED),("[C]Capa",CYAN),
                         ("[L]Ind",PINK),("Pi:Bc/2",CYAN),("R/X",ORANGE),("P/Q",BLUE),
                         ("H.T.=clic droit",RED)]:
            tk.Label(leg,text=txt,font=mono(7),fg=col,bg=PANEL
                     ).pack(side='left',padx=5,pady=7)

    # ══════════════════════════════════════════════════════════
    #  MENU AFFICHAGE DÉROULANT
    # ══════════════════════════════════════════════════════════

    def _open_display_menu(self):
        if hasattr(self,'_menu_win') and self._menu_win and \
                self._menu_win.winfo_exists():
            self._menu_win.destroy(); self._menu_win=None; return
        btn=self._disp_btn
        bx=btn.winfo_rootx(); by=btn.winfo_rooty()+btn.winfo_height()
        win=tk.Toplevel(self.root); win.overrideredirect(True)
        win.configure(bg=BORDER); win.geometry(f"+{bx}+{by}"); win.lift()
        win.focus_set(); self._menu_win=win
        inner=tk.Frame(win,bg=CARD,padx=2,pady=4)
        inner.pack(fill='both',expand=True,padx=1,pady=1)
        tk.Label(inner,text="  Couches d'affichage",
                 font=mono(8,True),fg=T_SEC,bg=CARD
                 ).pack(anchor='w',padx=8,pady=(4,2))
        tk.Frame(inner,bg=BORDER,height=1).pack(fill='x',padx=6,pady=(0,4))
        br=tk.Frame(inner,bg=CARD); br.pack(fill='x',padx=8,pady=(0,4))
        def _all():
            for v in self._show.values(): v.set(True)
            self.draw_network(); self._refresh_btn()
        def _none():
            for v in self._show.values(): v.set(False)
            self.draw_network(); self._refresh_btn()
        for txt,cmd in (("Tout cocher",_all),("Tout decocher",_none)):
            tk.Button(br,text=txt,command=cmd,font=mono(7),fg=T_PRI,bg=BORDER,
                      activebackground=PANEL,relief='flat',bd=0,
                      padx=6,pady=2,cursor='hand2').pack(side='left',padx=2)
        tk.Frame(inner,bg=BORDER,height=1).pack(fill='x',padx=6,pady=(2,6))
        for key,label,col in self._checks_def:
            def _cmd(k=key): self.draw_network(); self._refresh_btn()
            tk.Checkbutton(inner,text=f"  {label}",variable=self._show[key],
                           command=_cmd,font=mono(8),fg=col,bg=CARD,
                           activebackground=CARD,activeforeground=col,
                           selectcolor=BORDER,highlightthickness=0,bd=0,
                           cursor='hand2',anchor='w'
                           ).pack(fill='x',padx=4,pady=2)
        win.bind('<FocusOut>', lambda e: win.after(150, lambda:
            win.destroy() if win.winfo_exists() else None))

    def _refresh_btn(self):
        n_on=sum(1 for v in self._show.values() if v.get())
        n_tot=len(self._show)
        self._disp_btn.config(text=f"  Affichage ({n_on}/{n_tot})  v",
                              fg=BLUE if n_on==n_tot else AMBER)

    # ══════════════════════════════════════════════════════════
    #  WIDGETS DE CONTRÔLE
    # ══════════════════════════════════════════════════════════

    def _sep(self, parent, title):
        tk.Label(parent,text=title,font=mono(8,True),fg=T_SEC,bg=PANEL
                 ).pack(fill='x',padx=10,pady=(10,2))
        tk.Frame(parent,bg=BORDER,height=1).pack(fill='x',padx=10,pady=(0,6))

    def _scrollable(self, parent):
        outer=tk.Frame(parent,bg=PANEL); outer.pack(fill='both',expand=True)
        cv=tk.Canvas(outer,bg=PANEL,highlightthickness=0,bd=0)
        sb=ttk.Scrollbar(outer,orient='vertical',command=cv.yview)
        inner=tk.Frame(cv,bg=PANEL)
        inner.bind('<Configure>',lambda e: cv.configure(scrollregion=cv.bbox('all')))
        cv.create_window((0,0),window=inner,anchor='nw')
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y'); cv.pack(side='left',fill='both',expand=True)
        cv.bind('<Enter>',lambda e,c=cv: (
            c.bind_all('<Button-4>',lambda ev: c.yview_scroll(-1,'units')),
            c.bind_all('<Button-5>',lambda ev: c.yview_scroll(1,'units'))))
        cv.bind('<Leave>',lambda e,c=cv: (
            c.unbind_all('<Button-4>'), c.unbind_all('<Button-5>')))
        return inner

    def _slider(self, parent, key, param, label, vmin, vmax, default,
                color, store, res=0.5):
        fr=tk.Frame(parent,bg=CARD); fr.pack(fill='x',padx=6,pady=(2,0))
        tk.Label(fr,text=label,font=mono(7),fg=T_SEC,bg=CARD).pack(side='left')
        prec=3 if res<0.05 else (2 if res<0.1 else 1)
        vl=tk.Label(fr,text=f"{default:.{prec}f}",
                    font=mono(7,True),fg=color,bg=CARD,width=7,anchor='e')
        vl.pack(side='right')
        var=tk.DoubleVar(value=default)
        store[key][param]=var; store[key][param+'_lbl']=vl
        def _cb(v,l=vl,p=prec):
            l.config(text=f"{float(v):.{p}f}"); self._schedule()
        tk.Scale(parent,variable=var,orient='horizontal',
                 from_=vmin,to=vmax,resolution=res,
                 bg=CARD,fg=color,troughcolor=BORDER,activebackground=color,
                 highlightthickness=0,bd=0,showvalue=False,sliderrelief='flat',
                 command=_cb).pack(fill='x',padx=6,pady=(0,2))

    def _sync_widget(self, parent, g):
        col=BLUE if g["id"]=="SM1" else GREEN
        card=tk.Frame(parent,bg=CARD,highlightbackground=col,highlightthickness=1)
        card.pack(fill='x',padx=8,pady=3)
        hdr=tk.Frame(card,bg=CARD); hdr.pack(fill='x',padx=6,pady=(5,1))
        tk.Label(hdr,text="[SM]",font=mono(8,True),fg=col,bg=CARD).pack(side='left')
        tk.Label(hdr,text=" "+g["name"],font=mono(8,True),fg=T_PRI,bg=CARD).pack(side='left')
        tk.Label(hdr,text=g["node"],font=mono(8),fg=T_SEC,bg=CARD).pack(side='right',padx=4)
        self.gen_vars[g["id"]]={}
        self._slider(card,g["id"],'P','P active [MW]',
                     g["P_min"],g["P_max"],g["P_mw"],col,self.gen_vars)
        self._slider(card,g["id"],'V','Tension [p.u.]',
                     g["V_min"],g["V_max"],g["V_pu"],GREEN,self.gen_vars,res=0.005)
        fr=tk.Frame(card,bg=CARD); fr.pack(fill='x',padx=6,pady=(1,5))
        self.gen_vars[g["id"]]['rlbl']=tk.Label(fr,text="P:-- Q:--",
                                                font=mono(7),fg=T_SEC,bg=CARD)
        self.gen_vars[g["id"]]['rlbl'].pack(side='left')

    def _ren_widget(self, parent, g):
        col=PURPLE if g["type"]=="wind" else AMBER
        icon="[Eo]" if g["type"]=="wind" else "[PV]"
        card=tk.Frame(parent,bg=CARD,highlightbackground=col,highlightthickness=1)
        card.pack(fill='x',padx=8,pady=3)
        hdr=tk.Frame(card,bg=CARD); hdr.pack(fill='x',padx=6,pady=(5,1))
        tk.Label(hdr,text=icon,font=mono(8,True),fg=col,bg=CARD).pack(side='left')
        tk.Label(hdr,text=" "+g["name"],font=mono(8,True),fg=T_PRI,bg=CARD).pack(side='left')
        tk.Label(hdr,text=g["node"],font=mono(8),fg=T_SEC,bg=CARD).pack(side='right',padx=4)
        self.gen_vars[g["id"]]={}
        self._slider(card,g["id"],'P','P active [MW]',
                     g["P_min"],g["P_max"],g["P_mw"],col,self.gen_vars)
        self._slider(card,g["id"],'Q','Q reactive [Mvar]',
                     g["Q_min"],g["Q_max"],g["Q_mvar"],TEAL,self.gen_vars)
        fr=tk.Frame(card,bg=CARD); fr.pack(fill='x',padx=6,pady=(1,5))
        self.gen_vars[g["id"]]['rlbl']=tk.Label(fr,text="P:-- Q:--",
                                                font=mono(7),fg=T_SEC,bg=CARD)
        self.gen_vars[g["id"]]['rlbl'].pack(side='left')

    def _load_widget(self, parent, l):
        card=tk.Frame(parent,bg=CARD,highlightbackground=RED,highlightthickness=1)
        card.pack(fill='x',padx=8,pady=3)
        hdr=tk.Frame(card,bg=CARD); hdr.pack(fill='x',padx=6,pady=(5,1))
        tk.Label(hdr,text="[Ch]",font=mono(8,True),fg=RED,bg=CARD).pack(side='left')
        tk.Label(hdr,text=" "+l["name"],font=mono(8,True),fg=T_PRI,bg=CARD).pack(side='left')
        tk.Label(hdr,text=l["node"],font=mono(8),fg=T_SEC,bg=CARD).pack(side='right',padx=4)
        self.load_vars[l["id"]]={}
        self._slider(card,l["id"],'P','P active [MW]',0,150,l["P_mw"],RED,self.load_vars)
        self._slider(card,l["id"],'Q','Q reactive [Mvar]',0,60,l["Q_mvar"],ORANGE,self.load_vars)

    def _shunt_widget(self, parent, sh):
        col=CYAN if sh["type"]=="capacitor" else PINK
        icon="[C]" if sh["type"]=="capacitor" else "[L]"
        desc="Condensateur" if sh["type"]=="capacitor" else "Inductance"
        card=tk.Frame(parent,bg=CARD,highlightbackground=col,highlightthickness=1)
        card.pack(fill='x',padx=8,pady=3)
        hdr=tk.Frame(card,bg=CARD); hdr.pack(fill='x',padx=6,pady=(5,1))
        tk.Label(hdr,text=icon,font=mono(8,True),fg=col,bg=CARD).pack(side='left')
        tk.Label(hdr,text=f" {desc} — {sh['name']}",
                 font=mono(8,True),fg=T_PRI,bg=CARD).pack(side='left')
        tk.Label(hdr,text=sh["node"],font=mono(8),fg=T_SEC,bg=CARD).pack(side='right',padx=4)
        info="B>0: produit Q, hausse V" if sh["type"]=="capacitor" else "B<0: consomme Q, baisse V"
        tk.Label(card,text=info,font=mono(7),fg=col,bg=CARD).pack(anchor='w',padx=10)
        self.shunt_vars[sh["id"]]={}
        self._slider(card,sh["id"],'B','Susceptance B [p.u.]',
                     sh["B_min"],sh["B_max"],sh["B_pu"],col,self.shunt_vars,res=0.01)
        fr=tk.Frame(card,bg=CARD); fr.pack(fill='x',padx=6,pady=(1,5))
        self.shunt_vars[sh["id"]]['rlbl']=tk.Label(fr,text="Q shunt: -- Mvar",
                                                   font=mono(7),fg=col,bg=CARD)
        self.shunt_vars[sh["id"]]['rlbl'].pack(side='left')

    # ══════════════════════════════════════════════════════════
    #  SIMULATION
    # ══════════════════════════════════════════════════════════

    def _schedule(self):
        if self._after_id: self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(120, self.run_simulation)

    def _get_gen_sp(self):
        sp={}
        for g in GENERATORS:
            gid=g["id"]; sp[gid]={}
            if gid in self.gen_vars:
                if 'P' in self.gen_vars[gid]: sp[gid]["P_mw"]=self.gen_vars[gid]['P'].get()
                if 'V' in self.gen_vars[gid]: sp[gid]["V_pu"]=self.gen_vars[gid]['V'].get()
                if 'Q' in self.gen_vars[gid]: sp[gid]["Q_mvar"]=self.gen_vars[gid]['Q'].get()
        return sp

    def _get_load_sp(self):
        sp={}
        for l in LOADS:
            lid=l["id"]; sp[lid]={}
            if lid in self.load_vars:
                if 'P' in self.load_vars[lid]: sp[lid]["P_mw"]=self.load_vars[lid]['P'].get()
                if 'Q' in self.load_vars[lid]: sp[lid]["Q_mvar"]=self.load_vars[lid]['Q'].get()
        return sp

    def _get_shunt_sp(self):
        sp={}
        for sh in SHUNTS:
            sid=sh["id"]
            sp[sid]=(self.shunt_vars[sid]['B'].get()
                     if sid in self.shunt_vars and 'B' in self.shunt_vars[sid]
                     else sh["B_pu"])
        return sp

    def run_simulation(self):
        self._after_id=None
        gen_sp=self._get_gen_sp(); load_sp=self._get_load_sp()
        shunt_sp=self._get_shunt_sp()
        try:
            net = build_network(gen_sp, load_sp, shunt_sp,
                                open_lines=self._open_lines,
                                open_nodes=self._open_nodes)
            self.node_results, self.line_results, self.converged, iters, status = \
                run_loadflow(net)
            # Conserver le réseau pour l'export IIDM (avec résultats)
            self._last_net = net

            if self.converged:
                self.status_lbl.config(text=f"  Converge OLF ({iters} iter)",fg=GREEN)
                self._conv_lbl.config(text=f"OK  Converge en {iters} iterations",fg=GREEN)
            else:
                self.status_lbl.config(text=f"  {status}",fg=AMBER)
                self._conv_lbl.config(text=f"WARN  {status}",fg=AMBER)

            self._update_results(gen_sp, load_sp, shunt_sp)
            self.draw_network()
        except Exception as e:
            import traceback
            self.status_lbl.config(text="  Erreur calcul",fg=RED)
            if hasattr(self,'_conv_lbl'):
                self._conv_lbl.config(text=f"ERR: {str(e)[:80]}",fg=RED)

    def _update_results(self, gen_sp, load_sp, shunt_sp):
        # Résultats générateurs
        P_gen=0.0; Q_gen=0.0
        for g in GENERATORS:
            gid=g["id"]; nid=g["node"]
            if gid in self.gen_vars and 'rlbl' in self.gen_vars[gid]:
                P=self.node_results.get(nid,{}).get("P_gen_mw",  gen_sp.get(gid,{}).get("P_mw", g["P_mw"]))
                Q=self.node_results.get(nid,{}).get("Q_gen_mvar",gen_sp.get(gid,{}).get("Q_mvar",g.get("Q_mvar",0)))
                self.gen_vars[gid]['rlbl'].config(
                    text=f"P:{P:+.1f} MW  Q:{Q:+.1f} Mvar",fg=GREEN)
                P_gen+=P; Q_gen+=Q

        # Résultats shunts
        Q_sh_tot=0.0
        for sh in SHUNTS:
            sid=sh["id"]; nid=sh["node"]
            B=shunt_sp.get(sid, sh["B_pu"])
            V=self.node_results.get(nid,{}).get("V_pu",1.0)
            Qs=B*V**2*BASE_MVA; Q_sh_tot+=Qs
            if sid in self.shunt_vars and 'rlbl' in self.shunt_vars[sid]:
                self.shunt_vars[sid]['rlbl'].config(
                    text=f"Q shunt: {Qs:+.2f} Mvar",
                    fg=CYAN if Qs>=0 else PINK)

        P_load=sum(load_sp.get(l["id"],{}).get("P_mw", l["P_mw"]) for l in LOADS)
        Q_load=sum(load_sp.get(l["id"],{}).get("Q_mvar",l["Q_mvar"]) for l in LOADS)
        P_loss=sum(f.get("P_loss",0) for f in self.line_results.values())

        self._blbls['P_gen'].config( text=f"{P_gen:.1f} MW",  fg=GREEN)
        self._blbls['P_load'].config(text=f"{P_load:.1f} MW", fg=RED)
        self._blbls['P_loss'].config(text=f"{P_loss:.2f} MW", fg=AMBER)
        self._blbls['Q_gen'].config( text=f"{Q_gen:.1f} Mvar", fg=BLUE)
        self._blbls['Q_load'].config(text=f"{Q_load:.1f} Mvar",fg=ORANGE)
        self._blbls['Q_shunt'].config(text=f"{Q_sh_tot:+.2f} Mvar",
                                      fg=CYAN if Q_sh_tot>=0 else PINK)

        for nid,lbl in self._vlbls.items():
            if nid in self.node_results:
                nr=self.node_results[nid]; v=nr["V_pu"]
                lbl.config(text=f"{v:.4f}pu  {nr['theta_deg']:+.2f}deg",
                           fg=RED if v<0.95 else AMBER if v>1.05 else GREEN)

        for lid,lbl in self._lflbls.items():
            if lid in self.line_results:
                lf=self.line_results[lid]; lp=lf["loading_pct"]
                col=RED if lp>90 else AMBER if lp>70 else GREEN
                lbl.config(text=f"P:{lf['P_from']:+.0f}MW Q:{lf['Q_from']:+.0f}Mvar ({lp:.0f}%)",
                           fg=col)

    # ══════════════════════════════════════════════════════════
    #  FICHIERS IIDM / JSON
    # ══════════════════════════════════════════════════════════

    def _save_iidm(self):
        if not hasattr(self,'_last_net'):
            messagebox.showwarning("Pas de résultats","Lancez d'abord un calcul."); return
        path=filedialog.asksaveasfilename(
            defaultextension=".xiidm",
            filetypes=[("IIDM réseau","*.xiidm"),("Tous","*.*")],
            title="Sauvegarder le réseau IIDM")
        if not path: return
        try:
            save_iidm(self._last_net, path)
            self.iidm_path=path
            messagebox.showinfo("Sauvegardé",f"Réseau sauvegardé :\n{path}")
        except Exception as e:
            messagebox.showerror("Erreur",str(e))

    def _open_iidm(self):
        path=filedialog.askopenfilename(
            filetypes=[("IIDM réseau","*.xiidm *.iidm"),("Tous","*.*")],
            title="Ouvrir un fichier IIDM")
        if not path: return
        try:
            net=load_iidm(path)
            self._last_net=net
            self.iidm_path=path
            # Relancer le load flow sur le réseau chargé
            params=plf.Parameters(distributed_slack=False,
                voltage_init_mode=plf.VoltageInitMode.DC_VALUES)
            res=plf.run_ac(net,parameters=params)
            self.converged=(res[0].status==plf.ComponentStatus.CONVERGED)
            iters=res[0].iteration_count
            # Lire les résultats (sans mise à jour des curseurs)
            self.node_results, self.line_results, self.converged, iters, _ = \
                run_loadflow(net)
            self.status_lbl.config(
                text=f"  IIDM charge — LF {'OK' if self.converged else 'WARN'}",
                fg=GREEN if self.converged else AMBER)
            self.draw_network()
            messagebox.showinfo("IIDM chargé",
                f"Fichier : {os.path.basename(path)}\n"
                f"Load flow : {'convergé' if self.converged else 'non convergé'} "
                f"en {iters} iter.")
        except Exception as e:
            messagebox.showerror("Erreur ouverture IIDM",str(e))

    def _export_json(self):
        """Exporte les résultats courants en JSON pour post-traitement."""
        if not self.node_results:
            messagebox.showwarning("Pas de résultats","Lancez d'abord un calcul."); return
        path=filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON","*.json"),("Tous","*.*")],
            title="Exporter résultats JSON")
        if not path: return
        data={
            "nodes": self.node_results,
            "lines": self.line_results,
            "converged": self.converged,
        }
        with open(path,'w') as f:
            json.dump(data, f, indent=2)
        messagebox.showinfo("Exporté",f"Résultats JSON :\n{path}")

    # ══════════════════════════════════════════════════════════
    #  CLIC DROIT — menu contextuel ouvrage
    # ══════════════════════════════════════════════════════════

    def _on_right_click(self, event):
        """Détecte l'ouvrage cliqué et affiche un menu contextuel."""
        tx, ty, scale = self._transform()
        nd_pos = {nd["id"]: (tx(nd["x"]), ty(nd["y"])) for nd in NODES}
        r = max(20, min(40, int(scale * 20)))

        hit_node = None
        hit_line = None

        # Test sur les nœuds (cercle de rayon r+8)
        for nd in NODES:
            nx, ny = nd_pos[nd["id"]]
            if math.hypot(event.x - nx, event.y - ny) <= r + 8:
                hit_node = nd["id"]
                break

        # Test sur les lignes (distance point-segment < seuil)
        if hit_node is None:
            for line in LINES:
                x1, y1 = nd_pos[line["from"]]
                x2, y2 = nd_pos[line["to"]]
                d = self._dist_point_segment(event.x, event.y, x1, y1, x2, y2)
                if d < 10:
                    hit_line = line["id"]
                    break

        if hit_node is None and hit_line is None:
            return  # rien cliqué

        # Construction du menu contextuel
        menu = tk.Menu(self.root, tearoff=0,
                       bg=CARD, fg=T_PRI,
                       activebackground=BORDER, activeforeground=T_PRI,
                       font=mono(8), bd=0, relief='flat')

        if hit_node:
            nd   = next(n for n in NODES if n["id"] == hit_node)
            open_ = hit_node in self._open_nodes
            label = f"Noeud {hit_node} — {nd['name'].split('-')[-1].strip()}"
            menu.add_command(label=label, state='disabled',
                             font=mono(8, True))
            menu.add_separator()
            if open_:
                menu.add_command(
                    label="  ⚡  Remettre sous tension",
                    foreground=GREEN,
                    command=lambda n=hit_node: self._toggle_node(n))
            else:
                menu.add_command(
                    label="  ✕  Mettre hors tension (ouvrir DJ)",
                    foreground=RED,
                    command=lambda n=hit_node: self._toggle_node(n))
            # Lister les lignes connectées
            connected = [l for l in LINES
                         if l["from"] == hit_node or l["to"] == hit_node]
            if connected:
                menu.add_separator()
                menu.add_command(label="  Lignes connectées :", state='disabled')
                for l in connected:
                    open_l = l["id"] in self._open_lines
                    status = "  [OUVERTE]" if open_l else ""
                    menu.add_command(
                        label=f"    {l['id']} — {l['name']}{status}",
                        foreground=T_SEC if open_l else T_PRI,
                        command=lambda lid=l["id"]: self._toggle_line(lid))

        elif hit_line:
            line  = next(l for l in LINES if l["id"] == hit_line)
            open_ = hit_line in self._open_lines
            menu.add_command(label=f"Ligne {hit_line} — {line['name']}",
                             state='disabled', font=mono(8, True))
            menu.add_separator()
            lf = self.line_results.get(hit_line, {})
            if lf:
                P = lf.get("P_from", 0); Q = lf.get("Q_from", 0)
                load_pct = lf.get("loading_pct", 0)
                menu.add_command(
                    label=f"  P={P:+.1f} MW  Q={Q:+.1f} Mvar  ({load_pct:.0f}%)",
                    state='disabled')
                menu.add_command(
                    label=f"  R={line['R_pu']:.4f} pu   X={line['X_pu']:.4f} pu",
                    state='disabled')
                menu.add_separator()
            if open_:
                menu.add_command(
                    label="  ⚡  Réenclencher la ligne",
                    foreground=GREEN,
                    command=lambda lid=hit_line: self._toggle_line(lid))
            else:
                menu.add_command(
                    label="  ✕  Ouvrir les disjoncteurs (H.T.)",
                    foreground=RED,
                    command=lambda lid=hit_line: self._toggle_line(lid))

        menu.add_separator()
        menu.add_command(label="  Remettre tout sous tension",
                         foreground=AMBER,
                         command=self._restore_all)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _dist_point_segment(px, py, ax, ay, bx, by):
        """Distance d'un point (px,py) au segment (ax,ay)-(bx,by)."""
        dx = bx - ax; dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / (dx*dx + dy*dy)))
        return math.hypot(px - (ax + t*dx), py - (ay + t*dy))

    def _toggle_line(self, line_id):
        """Ouvre ou ferme une ligne et relance le calcul."""
        if line_id in self._open_lines:
            self._open_lines.discard(line_id)
        else:
            self._open_lines.add(line_id)
        self._schedule()

    def _toggle_node(self, node_id):
        """Déconnecte ou reconnecte un nœud (ouvre tous ses disjoncteurs)."""
        if node_id in self._open_nodes:
            self._open_nodes.discard(node_id)
            # Réenclencher les lignes qui étaient ouvertes à cause de ce nœud
            for line in LINES:
                if (line["from"] == node_id or line["to"] == node_id):
                    self._open_lines.discard(line["id"])
        else:
            self._open_nodes.add(node_id)
            # Ouvrir toutes les lignes connectées
            for line in LINES:
                if line["from"] == node_id or line["to"] == node_id:
                    self._open_lines.add(line["id"])
        self._schedule()

    def _restore_all(self):
        """Remet tous les ouvrages sous tension."""
        self._open_lines.clear()
        self._open_nodes.clear()
        self._schedule()

    # ══════════════════════════════════════════════════════════
    #  ZOOM / PAN
    # ══════════════════════════════════════════════════════════

    def _update_zoom_lbl(self):
        self._zoom_lbl.config(text=f"{self._zoom*100:.0f}%")

    def zoom_in(self,cx=None,cy=None):   self._apply_zoom(self.ZOOM_STEP,cx,cy)
    def zoom_out(self,cx=None,cy=None):  self._apply_zoom(1/self.ZOOM_STEP,cx,cy)
    def zoom_reset(self):
        self._zoom=1.0; self._pan_x=0.0; self._pan_y=0.0
        self._update_zoom_lbl(); self.draw_network()

    def _apply_zoom(self,factor,cx=None,cy=None):
        old=self._zoom
        new=max(self.ZOOM_MIN,min(self.ZOOM_MAX,old*factor))
        if new==old: return
        if cx is None: cx=self.canvas.winfo_width()/2; cy=self.canvas.winfo_height()/2
        self._pan_x=cx-(cx-self._pan_x)*(new/old)
        self._pan_y=cy-(cy-self._pan_y)*(new/old)
        self._zoom=new; self._update_zoom_lbl(); self.draw_network()

    def _wheel_up(self,e):   self.zoom_in(e.x,e.y)
    def _wheel_down(self,e): self.zoom_out(e.x,e.y)
    def _wheel_win(self,e):
        if e.delta>0: self.zoom_in(e.x,e.y)
        else:         self.zoom_out(e.x,e.y)
    def _drag_start_cb(self,e):
        self._drag_start=(e.x,e.y); self.canvas.config(cursor='hand2')
    def _drag_move(self,e):
        if not self._drag_start: return
        dx=e.x-self._drag_start[0]; dy=e.y-self._drag_start[1]
        self._pan_x+=dx; self._pan_y+=dy
        self._drag_start=(e.x,e.y); self.draw_network()
    def _drag_end(self,e):
        self._drag_start=None; self.canvas.config(cursor='fleur')

    # ══════════════════════════════════════════════════════════
    #  DESSIN DU RÉSEAU
    # ══════════════════════════════════════════════════════════

    def _transform(self):
        W=self.canvas.winfo_width(); H=self.canvas.winfo_height()
        margin=60
        s=min((W-2*margin)/self.DW,(H-2*margin)/self.DH)*self._zoom
        def tx(x): return margin+x*s+self._pan_x
        def ty(y): return margin+y*s+self._pan_y
        return tx,ty,s

    def draw_network(self):
        c=self.canvas; c.delete('all')
        W=c.winfo_width(); H=c.winfo_height()
        if W<80 or H<80: return
        tx,ty,scale=self._transform()
        c.create_text(W-6,H-8,text=f"zoom {self._zoom*100:.0f}%",
                      font=mono(7),fill=T_SEC,anchor='se')

        # ── Lignes
        nd_pos={nd["id"]:(tx(nd["x"]),ty(nd["y"])) for nd in NODES}
        for line in LINES:
            x1,y1=nd_pos[line["from"]]; x2,y2=nd_pos[line["to"]]
            is_open = line["id"] in self._open_lines
            if is_open:
                # Ligne ouverte : tirets gris + symbole disjoncteur
                self._draw_open_line(c, x1, y1, x2, y2, line)
            else:
                lf=self.line_results.get(line["id"],{})
                loading=lf.get("loading_pct",0)
                lcol=RED if loading>90 else AMBER if loading>70 else "#2a3a5c"
                lw=3.5 if loading>90 else 2.5 if loading>70 else 2
                self._draw_pi_line(c,x1,y1,x2,y2,line,lf,lcol,lw,scale)

        # ── Shunts
        sh_by_node={}
        for sh in SHUNTS: sh_by_node.setdefault(sh["node"],[]).append(sh)

        # ── Nœuds
        r=max(20,min(40,int(scale*20)))
        for nd in NODES:
            nx,ny=nd_pos[nd["id"]]; nid=nd["id"]
            gn=next((g for g in GENERATORS if g["node"]==nid),None)
            ln=next((l for l in LOADS       if l["node"]==nid),None)
            if gn and gn["type"]=="synchronous":
                col=BLUE if nid=="N1" else GREEN; sym="[SM]"
            elif gn and gn["type"]=="wind":  col=PURPLE; sym="[Eo]"
            elif gn and gn["type"]=="solar": col=AMBER;  sym="[PV]"
            elif ln:                         col=RED;    sym="[Ch]"
            else:                            col=T_SEC;  sym="[?]"

            if self._show['shunts'].get() and nid in sh_by_node:
                self._draw_shunts(c,nx,ny,r,sh_by_node[nid])

            is_open_node = nid in self._open_nodes
            node_col = "#444444" if is_open_node else col

            c.create_oval(nx-r-5,ny-r-5,nx+r+5,ny+r+5,
                          fill='',outline=node_col,width=1,dash=(4,4))
            c.create_oval(nx-r,ny-r,nx+r,ny+r,
                          fill=CARD if not is_open_node else "#1a1a1a",
                          outline=node_col,width=2.5)
            c.create_text(nx,ny-8,text=sym,font=mono(8,True),fill=node_col)
            c.create_text(nx,ny+9,text=nid,font=mono(8,True),
                          fill=T_PRI if not is_open_node else T_SEC)
            # Croix rouge "hors tension"
            if is_open_node:
                d=r*0.55
                c.create_line(nx-d,ny-d,nx+d,ny+d,fill=RED,width=3)
                c.create_line(nx+d,ny-d,nx-d,ny+d,fill=RED,width=3)
                c.create_text(nx,ny-r-14,text="H.T.",
                              font=mono(7,True),fill=RED)

            if self._show['tensions'].get() and nid in self.node_results:
                nr=self.node_results[nid]; v=nr["V_pu"]; ang=nr["theta_deg"]
                vcol=RED if v<0.95 else AMBER if v>1.05 else GREEN
                lx,anc=(nx-r-8,'e') if nd["x"]>500 else (nx+r+8,'w')
                for ddx,ddy in ((1,0),(-1,0),(0,1),(0,-1)):
                    c.create_text(lx+ddx,ny-16+ddy,text=f"{v:.3f}pu",
                                  font=mono(8),fill=BG,anchor=anc)
                c.create_text(lx,ny-16,text=f"{v:.3f}pu",
                              font=mono(8,True),fill=vcol,anchor=anc)
                c.create_text(lx,ny-2, text=f"{ang:+.1f}deg",
                              font=mono(7),fill=T_SEC,anchor=anc)
                c.create_text(lx,ny+12,text=f"{nr['V_kv']:.2f}kV",
                              font=mono(7),fill=T_SEC,anchor=anc)

        Pl=sum(self.load_vars[l["id"]]['P'].get() for l in LOADS
               if l["id"] in self.load_vars and 'P' in self.load_vars[l["id"]])
        Ql=sum(self.load_vars[l["id"]]['Q'].get() for l in LOADS
               if l["id"] in self.load_vars and 'Q' in self.load_vars[l["id"]])
        c.create_text(W/2,H-10,text=f"Charge totale : {Pl:.0f} MW  /  {Ql:.0f} Mvar",
                      font=mono(8),fill=T_SEC)

    def _draw_open_line(self, c, x1, y1, x2, y2, line):
        """
        Dessine une ligne ouverte (hors tension) :
        - tirets gris foncé
        - symbole disjoncteur ouvert (carré barré) au milieu
        - label H.T.
        """
        GRAY = "#444455"
        mx = (x1+x2)/2; my = (y1+y2)/2
        angle = math.atan2(y2-y1, x2-x1)
        cos_a = math.cos(angle); sin_a = math.sin(angle)

        # Ligne en tirets gris
        c.create_line(x1,y1,x2,y2, fill=GRAY, width=2, dash=(6,5))

        # Symbole disjoncteur ouvert : deux petits segments interrompus + carré
        sz = 10  # demi-taille du symbole
        # Carré représentant le disjoncteur
        pts = [
            mx - cos_a*sz - sin_a*sz,  my - sin_a*sz + cos_a*sz,
            mx + cos_a*sz - sin_a*sz,  my + sin_a*sz + cos_a*sz,
            mx + cos_a*sz + sin_a*sz,  my + sin_a*sz - cos_a*sz,
            mx - cos_a*sz + sin_a*sz,  my - sin_a*sz - cos_a*sz,
        ]
        c.create_polygon(*pts, fill=BG, outline=RED, width=2)
        # Barre oblique dans le carré (= ouvert)
        c.create_line(mx - cos_a*sz + sin_a*sz, my - sin_a*sz - cos_a*sz,
                      mx + cos_a*sz - sin_a*sz, my + sin_a*sz + cos_a*sz,
                      fill=RED, width=2)

        # Label
        perp_x = -sin_a; perp_y = cos_a
        lx = mx + perp_x*18; ly = my + perp_y*18
        c.create_text(lx, ly-7,  text=f"{line['id']}", font=mono(7,True),
                      fill=GRAY, anchor='center')
        c.create_text(lx, ly+6, text="H.T.", font=mono(7,True),
                      fill=RED, anchor='center')

    def _draw_pi_line(self,c,x1,y1,x2,y2,line,lf,lcol,lw,scale):
        angle=math.atan2(y2-y1,x2-x1)
        cos_a=math.cos(angle); sin_a=math.sin(angle)
        perp_x=-sin_a; perp_y=cos_a
        t1,t2=0.20,0.80
        px1=x1+(x2-x1)*t1; py1=y1+(y2-y1)*t1
        px2=x1+(x2-x1)*t2; py2=y1+(y2-y1)*t2
        Bc=line["Bc_pu"]; Gc=line.get("Gc_pu",0)
        R=line["R_pu"];   X=line["X_pu"]
        sh=max(8,14*scale); sw=max(5,8*scale)

        c.create_line(x1,y1,px1,py1,fill=lcol,width=lw)
        c.create_line(px1,py1,px2,py2,fill=lcol,width=lw+0.5)
        c.create_line(px2,py2,x2,y2,fill=lcol,width=lw)

        if self._show['pi_schema'].get() and abs(Bc)>1e-6:
            for px,py in ((px1,py1),(px2,py2)):
                bx=px+perp_x*sh*0.6; by=py+perp_y*sh*0.6
                c.create_line(px,py,bx,by,fill=CYAN,width=1.5)
                p1x=bx-cos_a*sw; p1y=by-sin_a*sw
                p2x=bx+cos_a*sw; p2y=by+sin_a*sw
                ox=perp_x*3; oy=perp_y*3
                c.create_line(p1x,p1y,p2x,p2y,fill=CYAN,width=2.5)
                c.create_line(p1x+ox,p1y+oy,p2x+ox,p2y+oy,fill=CYAN,width=2.5)
                if self._show['impedances'].get():
                    c.create_text(px+perp_x*(sh+12),py+perp_y*(sh+12),
                                  text=f"Bc/2={Bc/2:.4f}",font=mono(6),
                                  fill=CYAN,anchor='n')

        mx=(px1+px2)/2; my=(py1+py2)/2
        if self._show['impedances'].get():
            rx=mx+perp_x*22; ry=my+perp_y*22
            for ddx,ddy in ((1,0),(-1,0),(0,1),(0,-1)):
                c.create_text(rx+ddx,ry-7+ddy,text=f"R={R:.4f}",font=mono(6),fill=BG)
                c.create_text(rx+ddx,ry+5+ddy,text=f"X={X:.4f}",font=mono(6),fill=BG)
            c.create_text(rx,ry-7,text=f"R={R:.4f}",font=mono(6),fill=AMBER)
            c.create_text(rx,ry+5,text=f"X={X:.4f}",font=mono(6),fill=ORANGE)

        if self._show['flux'].get() and lf:
            P=lf.get("P_from",0); Q=lf.get("Q_from",0)
            fx=mx-perp_x*26; fy=my-perp_y*26
            for ddx,ddy in ((1,0),(-1,0),(0,1),(0,-1)):
                c.create_text(fx+ddx,fy-8+ddy,text=f"P:{P:+.0f}MW",font=mono(7),fill=BG)
                c.create_text(fx+ddx,fy+5+ddy,text=f"Q:{Q:+.0f}Mvar",font=mono(7),fill=BG)
            c.create_text(fx,fy-8, text=f"P:{P:+.0f}MW",  font=mono(7,True),fill=BLUE)
            c.create_text(fx,fy+5, text=f"Q:{Q:+.0f}Mvar",font=mono(7),     fill=TEAL)

        if self._show['pertes'].get() and lf:
            Pl=lf.get("P_loss",0)
            if abs(Pl)>0.01:
                fx=mx-perp_x*26; fy=my-perp_y*26
                c.create_text(fx,fy+18,text=f"Pertes:{Pl:.2f}MW",
                              font=mono(6),fill=AMBER)

        if self._show['fleches'].get() and lf:
            P=lf.get("P_from",0)
            if abs(P)>0.5:
                fa=angle if P>0 else angle+math.pi
                ax=x1+(x2-x1)*0.55; ay=y1+(y2-y1)*0.55
                c.create_line(ax-math.cos(fa)*8,ay-math.sin(fa)*8,
                              ax+math.cos(fa)*8,ay+math.sin(fa)*8,
                              fill=lcol,width=2.5,arrow='last',arrowshape=(8,10,4))

    def _draw_shunts(self,c,nx,ny,r,shunts):
        for k,sh in enumerate(shunts):
            sid=sh["id"]; styp=sh["type"]
            B=(self.shunt_vars[sid]['B'].get()
               if sid in self.shunt_vars and 'B' in self.shunt_vars[sid]
               else sh["B_pu"])
            col=CYAN if styp=="capacitor" else PINK
            sign=1 if k%2==0 else -1
            sx=nx+sign*(r+15+k*12); sy=ny+r+5
            c.create_line(nx,ny+r,sx,sy,fill=col,width=1.5,dash=(3,2))
            if styp=="capacitor":
                sw=10
                c.create_line(sx,sy,sx,sy+12,fill=col,width=1.5)
                c.create_line(sx-sw,sy+12,sx+sw,sy+12,fill=col,width=2.5)
                c.create_line(sx-sw,sy+16,sx+sw,sy+16,fill=col,width=2.5)
                c.create_line(sx,sy+16,sx,sy+26,fill=col,width=1.5)
                c.create_line(sx-6,sy+26,sx+6,sy+26,fill=col,width=1.5)
            else:
                c.create_line(sx,sy,sx,sy+6,fill=col,width=1.5)
                for ai in range(3):
                    ay0=sy+6+ai*7
                    c.create_arc(sx-6,ay0,sx+6,ay0+8,
                                 start=180,extent=180,style='arc',outline=col,width=2)
                c.create_line(sx,sy+27,sx,sy+33,fill=col,width=1.5)
                c.create_line(sx-6,sy+33,sx+6,sy+33,fill=col,width=1.5)
            V=self.node_results.get(sh["node"],{}).get("V_pu",1.0)
            Qs=B*V**2*BASE_MVA
            c.create_text(sx,sy+36,text=f"B={B:.3f}\nQ={Qs:+.1f}",
                          font=mono(6),fill=col,anchor='n',justify='center')


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    iidm_path=sys.argv[1] if len(sys.argv)>1 else None
    root=tk.Tk(); root.withdraw(); root.update()
    style=ttk.Style()
    try: style.theme_use('clam')
    except Exception: pass
    style.configure('Vertical.TScrollbar',background=CARD,
                    troughcolor=BG,bordercolor=BORDER,arrowcolor=T_SEC)
    app=GridApp(root,iidm_path)
    root.deiconify(); root.update_idletasks()
    x=(root.winfo_screenwidth() -root.winfo_width()) //2
    y=(root.winfo_screenheight()-root.winfo_height())//2
    root.geometry(f"+{x}+{y}")
    root.mainloop()

if __name__=="__main__":
    main()
