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
    {"id":"SM1",  "node":"N1","name":"Machine Sync. 1","type":"synchronous",
     "energy_source":"NUCLEAR",
     "P_mw":80,"V_pu":1.02,"P_min":10,"P_max":150,"V_min":0.95,"V_max":1.05},
    {"id":"SM2",  "node":"N2","name":"Machine Sync. 2","type":"synchronous",
     "energy_source":"NUCLEAR",
     "P_mw":60,"V_pu":1.01,"P_min":10,"P_max":120,"V_min":0.95,"V_max":1.05},
    {"id":"WIND", "node":"N3","name":"Parc Eolien",    "type":"wind",
     "energy_source":"WIND",
     "P_mw":30,"Q_mvar":5,"P_min":0,"P_max":80,"Q_min":-20,"Q_max":20},
    {"id":"PVSOL","node":"N4","name":"Centrale PV",    "type":"solar",
     "energy_source":"SOLAR",
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
            min_p=[g["P_min"]], max_p=[g["P_max"]],
            energy_source=[g.get("energy_source", "OTHER")])

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

    # Résultats bus — clé = voltage_level_id (fonctionne quel que soit le réseau)
    buses_raw = net.get_buses()[["v_mag","v_angle"]]
    vls_raw   = net.get_voltage_levels()[["nominal_v","substation_id"]]
    node_results = {}

    for vl_id in vls_raw.index:
        vl_bus = vl_id + "_0"   # convention pypowsybl BUS_BREAKER
        nom_kv = float(vls_raw.loc[vl_id, "nominal_v"])
        if vl_bus in buses_raw.index:
            row = buses_raw.loc[vl_bus]
            V_raw = row["v_mag"]
            ang   = row["v_angle"]
            V     = V_raw / nom_kv if nom_kv > 0 else 1.0
        else:
            V, ang, V_raw = 1.0, 0.0, nom_kv
        node_results[vl_id] = {
            "V_pu":      V,
            "theta_deg": ang,
            "V_kv":      V_raw,
            "nominal_kv": nom_kv,
        }

    # Résultats générateurs — clé = voltage_level_id du générateur
    gens_raw = net.get_generators()[["p","q","energy_source","voltage_regulator_on",
                                      "voltage_level_id"]]
    for gid, row in gens_raw.iterrows():
        vl_id = row["voltage_level_id"]
        if vl_id in node_results:
            node_results[vl_id]["P_gen_mw"]      = -row["p"]
            node_results[vl_id]["Q_gen_mvar"]    = -row["q"]
            node_results[vl_id]["energy_source"] = row["energy_source"]
            node_results[vl_id]["is_pv"]         = bool(row["voltage_regulator_on"])

    # Résultats lignes — itère sur le réseau lui-même (pas sur la constante globale)
    lines_rating = {l["id"]: l.get("rating_mva", 100) for l in LINES}
    line_results = {}
    try:
        lines_raw = net.get_lines()[["p1","q1","p2","q2","i1","i2","voltage_level1_id"]]
        for lid, row in lines_raw.iterrows():
            vl1_id  = row["voltage_level1_id"]
            nom_kv  = float(vls_raw.loc[vl1_id,"nominal_v"]) if vl1_id in vls_raw.index else BASE_KV
            i1      = row["i1"]
            I1_pu   = (i1 / (BASE_MVA/(math.sqrt(3)*nom_kv)*1000)
                       if (i1==i1 and nom_kv>0) else 0.0)
            rating  = lines_rating.get(lid, 100)
            loading = I1_pu / (rating/BASE_MVA) * 100 if I1_pu>0 else 0.0
            P_loss  = row["p1"] + row["p2"]
            Q_loss  = row["q1"] + row["q2"]
            line_results[lid] = {
                "P_from": row["p1"], "Q_from": row["q1"],
                "P_to":   row["p2"], "Q_to":   row["q2"],
                "P_loss": P_loss,    "Q_loss": Q_loss,
                "loading_pct": loading,
                "kind": "line",
            }
    except Exception:
        pass

    # ── Résultats transformateurs (lus depuis l'IIDM — absent si réseau sans transfo)
    transformer_results = {}
    try:
        t2w = net.get_2_windings_transformers()
        if not t2w.empty:
            t2w_res = t2w[["p1","q1","p2","q2","i1","rated_u1","rated_u2",
                            "r","x","voltage_level1_id","voltage_level2_id",
                            "bus1_id","bus2_id","connected1","connected2"]]
            for tid, row in t2w_res.iterrows():
                I_pu = row["i1"] / (BASE_MVA / (math.sqrt(3)*row["rated_u1"])*1000) \
                       if row["i1"]==row["i1"] and row["rated_u1"]>0 else 0.0
                # Taux de charge sur puissance nominale (estimé à rated_u²/x si pas de rated_s)
                P_loss = row["p1"] + row["p2"]
                Q_loss = row["q1"] + row["q2"]
                transformer_results[tid] = {
                    "P_from":   row["p1"],     "Q_from":   row["q1"],
                    "P_to":     row["p2"],     "Q_to":     row["q2"],
                    "P_loss":   P_loss,        "Q_loss":   Q_loss,
                    "loading_pct": min(I_pu*100, 200),
                    "rated_u1": row["rated_u1"], "rated_u2": row["rated_u2"],
                    "R_pu":     row["r"],        "X_pu":     row["x"],
                    "vl1":      row["voltage_level1_id"],
                    "vl2":      row["voltage_level2_id"],
                    "bus1":     row["bus1_id"],
                    "bus2":     row["bus2_id"],
                    "connected": row["connected1"] and row["connected2"],
                    "kind": "transformer",
                }
    except Exception:
        pass

    converged = (status == plf.ComponentStatus.CONVERGED)
    return node_results, line_results, transformer_results, converged, iters, status


def save_iidm(net: pn.Network, path: str):
    """Exporte le réseau au format IIDM (.xiidm)."""
    net.dump(path)


def load_iidm(path: str) -> pn.Network:
    """Charge un fichier IIDM."""
    return pn.load(path)


def read_diagram_positions(net: pn.Network) -> dict:
    """
    Lit les propriétés diagram_x / diagram_y stockées sur les voltage levels.
    Retourne {vl_id: (x, y)} pour les VL qui ont ces propriétés.
    Retourne un dict vide si aucune propriété n'est présente.
    """
    try:
        props = net.get_elements_properties()
        if props.empty:
            return {}
        pos = {}
        for _, row in props.iterrows():
            if row['key'] in ('diagram_x', 'diagram_y'):
                vl_id = row.name
                pos.setdefault(vl_id, {})[row['key']] = float(row['value'])
        # Ne retourner que les VL avec x ET y définis
        return {vl: (int(d['diagram_x']), int(d['diagram_y']))
                for vl, d in pos.items()
                if 'diagram_x' in d and 'diagram_y' in d}
    except Exception:
        return {}


def write_diagram_positions(net: pn.Network, positions: dict):
    """
    Écrit les positions {vl_id: (x, y)} comme propriétés IIDM
    sur les voltage levels correspondants.
    Ces propriétés seront sauvegardées dans le .xiidm et relues au prochain chargement.
    """
    if not positions:
        return
    import pandas as pd
    vl_ids = list(positions.keys())
    df = pd.DataFrame({
        'diagram_x': [str(positions[v][0]) for v in vl_ids],
        'diagram_y': [str(positions[v][1]) for v in vl_ids],
    }, index=pd.Index(vl_ids, name='id'))
    try:
        net.add_elements_properties(df)
    except Exception:
        pass


def extract_topology_from_network(net: pn.Network) -> dict:
    """
    Reconstruit la topologie (NODES, LINES, GENERATORS, LOADS, SHUNTS)
    depuis un réseau pypowsybl chargé depuis l'IIDM.

    Retourne un dict avec les clés :
      nodes, lines, generators, loads, shunts,
      node_by_id, gen_by_id, load_by_id, sh_by_id
    """
    # ── Positions : priorité aux propriétés IIDM diagram_x/diagram_y
    iidm_positions = read_diagram_positions(net)

    vls = net.get_voltage_levels()[['substation_id','nominal_v']]
    vl_list = list(vls.index)
    n_vl = len(vl_list)

    # Fallback : disposition en cercle si positions IIDM absentes ou incomplètes
    import math as _math
    cx, cy, radius = 410, 250, min(280, max(120, n_vl * 35))
    circle_positions = {}
    for i, vl_id in enumerate(vl_list):
        angle = 2 * _math.pi * i / n_vl - _math.pi / 2
        circle_positions[vl_id] = (
            int(cx + radius * _math.cos(angle)),
            int(cy + radius * _math.sin(angle))
        )

    def get_pos(vl_id):
        """Retourne la position IIDM si disponible, sinon la position circulaire."""
        if vl_id in iidm_positions:
            return iidm_positions[vl_id]
        return circle_positions.get(vl_id, (cx, cy))

    # ── NODES : un nœud par voltage level
    nodes = []
    for vl_id in vl_list:
        row = vls.loc[vl_id]
        x, y = get_pos(vl_id)
        from_iidm = vl_id in iidm_positions
        nodes.append({
            "id":   vl_id,
            "name": f"{vl_id} ({row['nominal_v']:.0f} kV)",
            "type": "pq",
            "x":    x, "y": y,
            "vl":   vl_id,
            "bus":  vl_id + "_0",
            "sub":  row['substation_id'],
            "nominal_kv":   float(row['nominal_v']),
            "pos_from_iidm": from_iidm,   # indique si la position vient de l'IIDM
        })
    node_by_vl = {n["vl"]: n["id"] for n in nodes}

    # ── GENERATORS
    generators = []
    try:
        gens_df = net.get_generators()[
            ['name','energy_source','target_p','target_q','target_v',
             'min_p','max_p','voltage_regulator_on','voltage_level_id','bus_id']]
        for gid, row in gens_df.iterrows():
            vl = row['voltage_level_id']
            nid = node_by_vl.get(vl, vl)
            es  = row['energy_source']
            reg = bool(row['voltage_regulator_on'])
            vl_nom = vls.loc[vl, 'nominal_v'] if vl in vls.index else BASE_KV
            generators.append({
                "id":            gid,
                "node":          nid,
                "name":          row.get('name', gid) or gid,
                "type":          "synchronous" if reg else
                                  ("wind"  if es=="WIND"  else
                                   "solar" if es=="SOLAR" else "pq"),
                "energy_source": es,
                "P_mw":    float(row['target_p']),
                "Q_mvar":  float(row['target_q']),
                "V_pu":    float(row['target_v']) / vl_nom if vl_nom else 1.0,
                "P_min":   float(row['min_p']),
                "P_max":   float(row['max_p']),
                "V_min":   0.95, "V_max": 1.05,
                "Q_min":  -9999, "Q_max": 9999,
            })
            # Marquer le type du nœud
            nd = next((n for n in nodes if n["id"]==nid), None)
            if nd:
                nd["type"] = "pv" if reg else "pq"
    except Exception:
        pass

    # ── Identifier le nœud slack (premier générateur PV connecté)
    for nd in nodes:
        if nd["type"] == "pv":
            nd["type"] = "slack"
            break

    # ── LOADS
    loads = []
    try:
        loads_df = net.get_loads()[['name','p0','q0','voltage_level_id']]
        for lid, row in loads_df.iterrows():
            vl  = row['voltage_level_id']
            nid = node_by_vl.get(vl, vl)
            loads.append({
                "id":    lid,
                "node":  nid,
                "name":  row.get('name', lid) or lid,
                "P_mw":  float(row['p0']),
                "Q_mvar":float(row['q0']),
            })
    except Exception:
        pass

    # ── SHUNTS
    shunts = []
    try:
        sh_df = net.get_shunt_compensators()[
            ['name','b','model_type','voltage_level_id']]
        for sid, row in sh_df.iterrows():
            vl  = row['voltage_level_id']
            nid = node_by_vl.get(vl, vl)
            vl_nom = vls.loc[vl, 'nominal_v'] if vl in vls.index else BASE_KV
            z_base_local = vl_nom**2 / BASE_MVA
            y_base_local = 1.0 / z_base_local if z_base_local else Y_BASE
            B_pu = float(row['b']) / y_base_local if y_base_local else 0.0
            styp = "capacitor" if B_pu >= 0 else "inductor"
            shunts.append({
                "id":    sid,
                "node":  nid,
                "name":  row.get('name', sid) or sid,
                "type":  styp,
                "B_pu":  B_pu,
                "B_min": min(B_pu * 2, -0.5) if styp=="inductor" else 0.0,
                "B_max": max(B_pu * 2,  0.5) if styp=="capacitor" else 0.0,
            })
    except Exception:
        pass

    # ── LINES
    lines = []
    try:
        lines_df = net.get_lines()[
            ['name','r','x','b1','b2','g1','g2',
             'voltage_level1_id','voltage_level2_id']]
        for lid, row in lines_df.iterrows():
            vl1 = row['voltage_level1_id']
            vl2 = row['voltage_level2_id']
            nd1 = node_by_vl.get(vl1, vl1)
            nd2 = node_by_vl.get(vl2, vl2)
            # Chercher la tension nominale pour la base
            vl_nom = vls.loc[vl1, 'nominal_v'] if vl1 in vls.index else BASE_KV
            z_base_local = vl_nom**2 / BASE_MVA
            y_base_local = 1.0/z_base_local if z_base_local else Y_BASE
            R_pu  = float(row['r']) / z_base_local
            X_pu  = float(row['x']) / z_base_local
            Bc_pu = (float(row['b1']) + float(row['b2'])) / y_base_local
            Gc_pu = (float(row['g1']) + float(row['g2'])) / y_base_local
            lines.append({
                "id":   lid,
                "from": nd1,
                "to":   nd2,
                "name": row.get('name', lid) or lid,
                "R_pu":    R_pu,
                "X_pu":    X_pu,
                "Bc_pu":   Bc_pu,
                "Gc_pu":   Gc_pu,
                "rating_mva": 100.0,   # valeur par défaut si absent de l'IIDM
            })
    except Exception:
        pass

    return {
        "nodes":      nodes,
        "lines":      lines,
        "generators": generators,
        "loads":      loads,
        "shunts":     shunts,
        "node_by_id": {n["id"]: n for n in nodes},
        "gen_by_id":  {g["id"]: g for g in generators},
        "load_by_id": {l["id"]: l for l in loads},
        "sh_by_id":   {s["id"]: s for s in shunts},
    }


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
        self.node_results       = {}
        self.line_results       = {}
        self.transformer_results= {}
        self.converged    = False

        # Topologie courante — pointe sur les constantes globales par défaut,
        # remplacée par _apply_topology() lors du chargement d'un IIDM externe
        self._nodes      = NODES
        self._lines      = LINES
        self._generators = GENERATORS
        self._loads      = LOADS
        self._shunts     = SHUNTS
        self._node_by_id = NODE_BY_ID
        self.lf_status    = ""
        self.gen_vars     = {}
        self.load_vars    = {}
        self.shunt_vars   = {}
        self._show        = {}
        self._after_id    = None
        self._zoom        = 1.0
        self._pan_x       = 0.0; self._pan_y = 0.0
        self._drag_start  = None
        self._dragging_node = None   # nœud en cours de déplacement
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
        self._prod_scroll_inner = inner   # référence pour _apply_topology
        self._sep(inner,"Machines Synchrones")
        for g in self._generators:
            if g["type"]=="synchronous": self._sync_widget(inner,g)
        self._sep(inner,"Sources Renouvelables")
        for g in self._generators:
            if g["type"] in ("wind","solar"): self._ren_widget(inner,g)

    def _build_conso_tab(self, parent):
        tk.Label(parent,text="CHARGES  &  COMPENSATION",font=mono(9,True),
                 fg=RED,bg=PANEL).pack(pady=(8,2))
        inner = self._scrollable(parent)
        self._conso_scroll_inner = inner   # référence pour _apply_topology
        self._sep(inner,"Charges")
        for l in self._loads: self._load_widget(inner,l)
        self._sep(inner,"Elements Shunt (reglage tension)")
        for sh in self._shunts: self._shunt_widget(inner,sh)

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
        self._vframe = vf   # référence pour _apply_topology
        self._vlbls={}
        for nd in self._nodes:
            fr=tk.Frame(vf,bg=CARD); fr.pack(fill='x',padx=6,pady=2)
            tk.Label(fr,text=f"{nd['id']} {nd['name'].split('-')[0].strip()}:",
                     font=mono(7),fg=T_SEC,bg=CARD,width=16,anchor='w').pack(side='left')
            v=tk.Label(fr,text="--",font=mono(7,True),fg=T_PRI,bg=CARD)
            v.pack(side='right',padx=2); self._vlbls[nd["id"]]=v

        self._sep(inner,"Flux sur les Lignes")
        lf=tk.Frame(inner,bg=CARD,highlightbackground=BORDER,highlightthickness=1)
        lf.pack(fill='x',padx=8,pady=3)
        self._lf_frame_widget = lf   # référence pour _apply_topology
        self._lflbls={}
        for line in self._lines:
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
        # Clic gauche : drag nœud si sur un nœud, sinon pan
        self.canvas.bind('<ButtonPress-1>',   self._on_left_press)
        self.canvas.bind('<B1-Motion>',       self._on_left_motion)
        self.canvas.bind('<ButtonRelease-1>', self._on_left_release)
        # Clic droit → menu contextuel ouvrage
        self.canvas.bind('<Button-3>',       self._on_right_click)

        # Légende
        leg=tk.Frame(parent,bg=PANEL,height=34,
                     highlightbackground=BORDER,highlightthickness=1)
        leg.pack(fill='x',pady=(4,0)); leg.pack_propagate(False)
        for txt,col in [("[SM-PV] NUCLEAR slack",BLUE),("[SM-PV] NUCLEAR",GREEN),
                         ("[Eo-PQ] WIND",PURPLE),("[PV-PQ] SOLAR",AMBER),
                         ("[Ch] Charge",RED),("[C]Capa",CYAN),("[L]Ind",PINK),
                         ("PV=reg.V",GREEN),("PQ=P+Q",TEAL),
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
        for g in self._generators:
            gid=g["id"]; sp[gid]={}
            if gid in self.gen_vars:
                if 'P' in self.gen_vars[gid]: sp[gid]["P_mw"]=self.gen_vars[gid]['P'].get()
                if 'V' in self.gen_vars[gid]: sp[gid]["V_pu"]=self.gen_vars[gid]['V'].get()
                if 'Q' in self.gen_vars[gid]: sp[gid]["Q_mvar"]=self.gen_vars[gid]['Q'].get()
        return sp

    def _get_load_sp(self):
        sp={}
        for l in self._loads:
            lid=l["id"]; sp[lid]={}
            if lid in self.load_vars:
                if 'P' in self.load_vars[lid]: sp[lid]["P_mw"]=self.load_vars[lid]['P'].get()
                if 'Q' in self.load_vars[lid]: sp[lid]["Q_mvar"]=self.load_vars[lid]['Q'].get()
        return sp

    def _get_shunt_sp(self):
        sp={}
        for sh in self._shunts:
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
            self.node_results, self.line_results, self.transformer_results, \
                self.converged, iters, status = run_loadflow(net)
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
        for g in self._generators:
            gid=g["id"]; nid=g["node"]
            if gid in self.gen_vars and 'rlbl' in self.gen_vars[gid]:
                P=self.node_results.get(nid,{}).get("P_gen_mw",  gen_sp.get(gid,{}).get("P_mw", g["P_mw"]))
                Q=self.node_results.get(nid,{}).get("Q_gen_mvar",gen_sp.get(gid,{}).get("Q_mvar",g.get("Q_mvar",0)))
                self.gen_vars[gid]['rlbl'].config(
                    text=f"P:{P:+.1f} MW  Q:{Q:+.1f} Mvar",fg=GREEN)
                P_gen+=P; Q_gen+=Q

        # Résultats shunts
        Q_sh_tot=0.0
        for sh in self._shunts:
            sid=sh["id"]; nid=sh["node"]
            B=shunt_sp.get(sid, sh["B_pu"])
            V=self.node_results.get(nid,{}).get("V_pu",1.0)
            Qs=B*V**2*BASE_MVA; Q_sh_tot+=Qs
            if sid in self.shunt_vars and 'rlbl' in self.shunt_vars[sid]:
                self.shunt_vars[sid]['rlbl'].config(
                    text=f"Q shunt: {Qs:+.2f} Mvar",
                    fg=CYAN if Qs>=0 else PINK)

        P_load=sum(load_sp.get(l["id"],{}).get("P_mw", l["P_mw"]) for l in self._loads)
        Q_load=sum(load_sp.get(l["id"],{}).get("Q_mvar",l["Q_mvar"]) for l in self._loads)
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
            # Écrire les positions canvas actuelles dans le réseau
            # (coordonnées dans l'espace de design 820×500)
            positions = {nd["vl"]: (nd["x"], nd["y"])
                         for nd in self._nodes if "vl" in nd}
            write_diagram_positions(self._last_net, positions)
            save_iidm(self._last_net, path)
            self.iidm_path = path
            n_pos = len(positions)
            messagebox.showinfo("Sauvegardé",
                f"Réseau sauvegardé :\n{path}\n\n"
                f"{n_pos} positions de nœuds incluses (propriétés diagram_x/diagram_y).")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def _open_iidm(self):
        path = filedialog.askopenfilename(
            filetypes=[("IIDM réseau","*.xiidm *.iidm"),("Tous","*.*")],
            title="Ouvrir un fichier IIDM")
        if not path:
            return
        try:
            net = load_iidm(path)
            self._last_net  = net
            self.iidm_path  = path

            # ── 1. Extraire la topologie depuis le réseau IIDM
            topo = extract_topology_from_network(net)
            self._apply_topology(topo)

            # ── 2. Load flow
            self.node_results, self.line_results, self.transformer_results, \
                self.converged, iters, status = run_loadflow(net)

            msg = "convergé" if self.converged else "non convergé"
            self.status_lbl.config(
                text=f"  IIDM chargé — LF {msg} ({iters} iter)",
                fg=GREEN if self.converged else AMBER)
            if hasattr(self, '_conv_lbl'):
                self._conv_lbl.config(
                    text=f"{'OK' if self.converged else 'WARN'}  {status}  {iters} iter",
                    fg=GREEN if self.converged else AMBER)

            # ── 3. Redessiner avec la nouvelle topologie
            self._open_lines = set()
            self._open_nodes = set()
            self.draw_network()

            messagebox.showinfo("IIDM chargé",
                f"Fichier : {os.path.basename(path)}\n"
                f"Noeuds : {len(self._nodes)}  "
                f"Lignes : {len(self._lines)}  "
                f"Transfo : {len(self.transformer_results)}\n"
                f"Load flow : {msg} en {iters} iter.")
        except Exception as e:
            import traceback
            messagebox.showerror("Erreur ouverture IIDM",
                                 f"{e}\n\n{traceback.format_exc()[-400:]}")

    def _apply_topology(self, topo: dict):
        """
        Remplace la topologie courante par celle extraite d'un fichier IIDM.
        Met à jour : les données internes, l'onglet Résultats ET les onglets
        Production / Conso & Comp (curseurs générateurs, charges, shunts).
        """
        self._nodes      = topo["nodes"]
        self._lines      = topo["lines"]
        self._generators = topo["generators"]
        self._loads      = topo["loads"]
        self._shunts     = topo["shunts"]
        self._node_by_id = topo["node_by_id"]

        # Réinitialiser les variables de curseurs (elles ne correspondent plus)
        self.gen_vars   = {}
        self.load_vars  = {}
        self.shunt_vars = {}

        # ── Onglet 1 : Production ─────────────────────────────────────────
        if hasattr(self, '_prod_scroll_inner'):
            for w in self._prod_scroll_inner.winfo_children():
                w.destroy()
            self._sep(self._prod_scroll_inner, "Machines Synchrones")
            for g in self._generators:
                if g["type"] == "synchronous":
                    self._sync_widget(self._prod_scroll_inner, g)
            self._sep(self._prod_scroll_inner, "Sources Renouvelables")
            for g in self._generators:
                if g["type"] in ("wind","solar"):
                    self._ren_widget(self._prod_scroll_inner, g)
            # Si pas de groupes connus, afficher tous les générateurs
            if not any(g["type"] in ("synchronous","wind","solar")
                       for g in self._generators):
                self._sep(self._prod_scroll_inner, "Générateurs")
                for g in self._generators:
                    self._ren_widget(self._prod_scroll_inner, g)

        # ── Onglet 2 : Conso & Comp ───────────────────────────────────────
        if hasattr(self, '_conso_scroll_inner'):
            for w in self._conso_scroll_inner.winfo_children():
                w.destroy()
            self._sep(self._conso_scroll_inner, "Charges")
            for l in self._loads:
                self._load_widget(self._conso_scroll_inner, l)
            self._sep(self._conso_scroll_inner, "Elements Shunt (reglage tension)")
            for sh in self._shunts:
                self._shunt_widget(self._conso_scroll_inner, sh)

        # ── Onglet 3 : Résultats — tensions ──────────────────────────────
        if hasattr(self, '_vframe'):
            for w in self._vframe.winfo_children():
                w.destroy()
            self._vlbls = {}
            for nd in self._nodes:
                fr = tk.Frame(self._vframe, bg=CARD)
                fr.pack(fill='x', padx=6, pady=2)
                tk.Label(fr, text=f"{nd['id']} ({nd.get('nominal_kv',0):.0f}kV):",
                         font=mono(7), fg=T_SEC, bg=CARD,
                         width=18, anchor='w').pack(side='left')
                v = tk.Label(fr, text="--", font=mono(7,True), fg=T_PRI, bg=CARD)
                v.pack(side='right', padx=2)
                self._vlbls[nd["id"]] = v

        # ── Onglet 3 : Résultats — flux lignes ────────────────────────────
        if hasattr(self, '_lf_frame_widget'):
            for w in self._lf_frame_widget.winfo_children():
                w.destroy()
            self._lflbls = {}
            for line in self._lines:
                fr = tk.Frame(self._lf_frame_widget, bg=CARD)
                fr.pack(fill='x', padx=6, pady=2)
                tk.Label(fr, text=f"{line['id']}:",
                         font=mono(7), fg=T_SEC, bg=CARD,
                         width=10, anchor='w').pack(side='left')
                v = tk.Label(fr, text="--", font=mono(7,True), fg=T_PRI, bg=CARD)
                v.pack(side='right', padx=2)
                self._lflbls[line["id"]] = v
            for tid in self.transformer_results:
                fr = tk.Frame(self._lf_frame_widget, bg=CARD)
                fr.pack(fill='x', padx=6, pady=2)
                tk.Label(fr, text=f"[TR]{tid}:",
                         font=mono(7), fg="#e0a020", bg=CARD,
                         width=10, anchor='w').pack(side='left')
                v = tk.Label(fr, text="--", font=mono(7,True), fg=T_PRI, bg=CARD)
                v.pack(side='right', padx=2)
                self._lflbls[tid] = v

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
        """Détecte l'ouvrage cliqué (nœud, ligne, transformateur) et affiche un menu contextuel."""
        tx, ty, scale = self._transform()
        nd_pos = {nd["id"]: (tx(nd["x"]), ty(nd["y"])) for nd in self._nodes}
        r = max(20, min(40, int(scale * 20)))
        spacing = max(12, 16*scale)

        # Pré-calculer les groupes parallèles pour avoir les offsets corrects
        rank_index, _ = self._build_parallel_groups(nd_pos)

        hit_node      = None
        hit_line      = None
        hit_transfo   = None

        # Test sur les nœuds
        for nd in self._nodes:
            nx, ny = nd_pos[nd["id"]]
            if math.hypot(event.x - nx, event.y - ny) <= r + 8:
                hit_node = nd["id"]
                break

        # Test sur les lignes (avec offset parallèle)
        if hit_node is None:
            for line in self._lines:
                x1,y1 = nd_pos[line["from"]]; x2,y2 = nd_pos[line["to"]]
                n_tot, rank = rank_index.get(line["id"], (1,0))
                dx,dy = self._perp_offset(x1,y1,x2,y2, rank, n_tot, spacing)
                d = self._dist_point_segment(event.x, event.y,
                                             x1+dx, y1+dy, x2+dx, y2+dy)
                if d < 12:
                    hit_line = line["id"]
                    break

        # Test sur les transformateurs (avec offset parallèle)
        if hit_node is None and hit_line is None:
            for tid, tr in self.transformer_results.items():
                nd1 = next((n["id"] for n in self._nodes if n["vl"]==tr["vl1"]), None)
                nd2 = next((n["id"] for n in self._nodes if n["vl"]==tr["vl2"]), None)
                if not nd1 or not nd2 or nd1 not in nd_pos or nd2 not in nd_pos:
                    continue
                x1,y1 = nd_pos[nd1]; x2,y2 = nd_pos[nd2]
                n_tot, rank = rank_index.get(tid, (1,0))
                dx,dy = self._perp_offset(x1,y1,x2,y2, rank, n_tot, spacing)
                d = self._dist_point_segment(event.x, event.y,
                                             x1+dx, y1+dy, x2+dx, y2+dy)
                if d < 12:
                    hit_transfo = tid
                    break

        if hit_node is None and hit_line is None and hit_transfo is None:
            return

        menu = tk.Menu(self.root, tearoff=0,
                       bg=CARD, fg=T_PRI,
                       activebackground=BORDER, activeforeground=T_PRI,
                       font=mono(8), bd=0, relief='flat')

        if hit_node:
            nd    = next(n for n in self._nodes if n["id"]==hit_node)
            open_ = hit_node in self._open_nodes
            menu.add_command(label=f"Noeud {hit_node} — {nd['name'].split('-')[-1].strip()}",
                             state='disabled', font=mono(8,True))
            menu.add_separator()
            if open_:
                menu.add_command(label="  Remettre sous tension", foreground=GREEN,
                                 command=lambda n=hit_node: self._toggle_node(n))
            else:
                menu.add_command(label="  Mettre hors tension (ouvrir DJ)", foreground=RED,
                                 command=lambda n=hit_node: self._toggle_node(n))
            connected = [l for l in self._lines if l["from"]==hit_node or l["to"]==hit_node]
            connected_tr = [(tid,tr) for tid,tr in self.transformer_results.items()
                            if (next((n["id"] for n in self._nodes if n["vl"]==tr["vl1"]),None)==hit_node
                             or next((n["id"] for n in self._nodes if n["vl"]==tr["vl2"]),None)==hit_node)]
            if connected or connected_tr:
                menu.add_separator()
                menu.add_command(label="  Ouvrages connectes :", state='disabled')
                for l in connected:
                    st = "  [H.T.]" if l["id"] in self._open_lines else ""
                    menu.add_command(
                        label=f"    {l['id']} — {l['name']}{st}",
                        foreground=T_SEC if st else T_PRI,
                        command=lambda lid=l["id"]: self._toggle_line(lid))
                for tid, tr in connected_tr:
                    st = "  [H.T.]" if tid in self._open_lines else ""
                    menu.add_command(
                        label=f"    [TR] {tid}  {tr.get('rated_u1',0):.0f}/{tr.get('rated_u2',0):.0f}kV{st}",
                        foreground=T_SEC if st else "#e0a020",
                        command=lambda t=tid: self._toggle_line(t))

        elif hit_line:
            line  = next(l for l in self._lines if l["id"]==hit_line)
            open_ = hit_line in self._open_lines
            menu.add_command(label=f"Ligne {hit_line} — {line['name']}",
                             state='disabled', font=mono(8,True))
            menu.add_separator()
            lf = self.line_results.get(hit_line, {})
            if lf:
                P=lf.get("P_from",0); Q=lf.get("Q_from",0); lp=lf.get("loading_pct",0)
                menu.add_command(label=f"  P={P:+.1f} MW  Q={Q:+.1f} Mvar  ({lp:.0f}%)",
                                 state='disabled')
                menu.add_command(label=f"  Pertes : {lf.get('P_loss',0):.3f} MW",
                                 state='disabled')
            menu.add_separator()
            if open_:
                menu.add_command(label="  Reenclencher", foreground=GREEN,
                                 command=lambda lid=hit_line: self._toggle_line(lid))
            else:
                menu.add_command(label="  Ouvrir les disjoncteurs (H.T.)", foreground=RED,
                                 command=lambda lid=hit_line: self._toggle_line(lid))

        elif hit_transfo:
            tr    = self.transformer_results[hit_transfo]
            open_ = hit_transfo in self._open_lines
            u1    = tr.get("rated_u1",0); u2 = tr.get("rated_u2",0)
            menu.add_command(
                label=f"Transformateur {hit_transfo}  {u1:.0f}/{u2:.0f} kV",
                state='disabled', font=mono(8,True))
            menu.add_separator()
            P=tr.get("P_from",0); Q=tr.get("Q_from",0); lp=tr.get("loading_pct",0)
            if P==P:   # not NaN
                menu.add_command(label=f"  P={P:+.1f} MW  Q={Q:+.1f} Mvar  ({lp:.0f}%)",
                                 state='disabled')
                menu.add_command(label=f"  Pertes : {tr.get('P_loss',0):.3f} MW",
                                 state='disabled')
            X_pu = tr.get("X_pu",0)
            z_base = (u1**2/BASE_MVA) if u1 else Z_BASE
            menu.add_command(label=f"  X = {X_pu/z_base:.4f} pu", state='disabled')
            menu.add_separator()
            if open_:
                menu.add_command(label="  Reenclencher le transformateur", foreground=GREEN,
                                 command=lambda t=hit_transfo: self._toggle_line(t))
            else:
                menu.add_command(label="  Ouvrir le transformateur (H.T.)", foreground=RED,
                                 command=lambda t=hit_transfo: self._toggle_line(t))

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
            for line in self._lines:
                if (line["from"] == node_id or line["to"] == node_id):
                    self._open_lines.discard(line["id"])
        else:
            self._open_nodes.add(node_id)
            # Ouvrir toutes les lignes connectées
            for line in self._lines:
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
    # ── Clic gauche : drag nœud ou pan ───────────────────────

    def _hit_node(self, ex, ey):
        """Retourne l'id du nœud sous le curseur (x,y) canvas, ou None."""
        tx, ty, scale = self._transform()
        r = max(20, min(40, int(scale * 20))) + 8
        for nd in self._nodes:
            nx, ny = tx(nd["x"]), ty(nd["y"])
            if math.hypot(ex - nx, ey - ny) <= r:
                return nd["id"]
        return None

    def _canvas_to_design(self, cx, cy):
        """Convertit des coordonnées canvas en coordonnées espace design (820×500)."""
        _, _, scale = self._transform()
        W = self.canvas.winfo_width(); H = self.canvas.winfo_height()
        margin = 60
        x = (cx - margin - self._pan_x) / scale
        y = (cy - margin - self._pan_y) / scale
        return x, y

    def _on_left_press(self, e):
        nid = self._hit_node(e.x, e.y)
        if nid:
            # Drag nœud
            self._dragging_node = nid
            self._drag_start    = None
            self.canvas.config(cursor='fleur')
        else:
            # Pan
            self._dragging_node = None
            self._drag_start    = (e.x, e.y)
            self.canvas.config(cursor='hand2')

    def _on_left_motion(self, e):
        if self._dragging_node:
            # Déplacer le nœud dans l'espace design
            dx, dy = self._canvas_to_design(e.x, e.y)
            # Clamp dans l'espace de design
            dx = max(20, min(self.DW - 20, dx))
            dy = max(20, min(self.DH - 20, dy))
            nd = next((n for n in self._nodes if n["id"] == self._dragging_node), None)
            if nd:
                nd["x"] = int(dx)
                nd["y"] = int(dy)
                self.draw_network()
        elif self._drag_start:
            ddx = e.x - self._drag_start[0]
            ddy = e.y - self._drag_start[1]
            self._pan_x += ddx; self._pan_y += ddy
            self._drag_start = (e.x, e.y)
            self.draw_network()

    def _on_left_release(self, e):
        self._dragging_node = None
        self._drag_start    = None
        self.canvas.config(cursor='fleur')

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

    @staticmethod
    def _perp_offset(x1,y1,x2,y2,rank,n_total,spacing=16):
        """
        Décalage perpendiculaire centré pour l'ouvrage de rang `rank`
        dans un groupe de `n_total` ouvrages parallèles.
        Retourne (dx, dy).
        """
        length = math.hypot(x2-x1, y2-y1)
        if length < 1e-6 or n_total <= 1:
            return 0.0, 0.0
        nx = -(y2-y1)/length
        ny =  (x2-x1)/length
        offset = (rank - (n_total-1)/2.0) * spacing
        return nx*offset, ny*offset

    def _build_parallel_groups(self, nd_pos):
        """
        Construit un index {equipment_id: (n_total, rank)} pour toutes
        les lignes et transformateurs, en regroupant ceux qui relient
        les mêmes deux nœuds canvas (position identique → même paire).
        Retourne aussi {equipment_id: (x1,y1,x2,y2)} pour le hit-test clic droit.
        """
        from collections import defaultdict

        # Regrouper lignes + transformateurs par paire de positions (arrondie)
        pair_to_equip = defaultdict(list)

        # Lignes statiques (self._lines)
        for line in self._lines:
            x1,y1 = nd_pos[line["from"]]
            x2,y2 = nd_pos[line["to"]]
            # Clé normalisée (nœud le plus petit en premier)
            key = tuple(sorted([line["from"], line["to"]]))
            pair_to_equip[key].append(("line", line["id"], x1,y1,x2,y2))

        # Transformateurs lus depuis IIDM
        for tid, tr in self.transformer_results.items():
            # Retrouver les nœuds par voltage_level_id
            nd1 = next((nd["id"] for nd in self._nodes if nd["vl"]==tr["vl1"]), None)
            nd2 = next((nd["id"] for nd in self._nodes if nd["vl"]==tr["vl2"]), None)
            if nd1 and nd2 and nd1 in nd_pos and nd2 in nd_pos:
                x1,y1 = nd_pos[nd1]; x2,y2 = nd_pos[nd2]
                key = tuple(sorted([nd1, nd2]))
                pair_to_equip[key].append(("transformer", tid, x1,y1,x2,y2))
            elif nd1 and nd2:
                # nœuds pas dans self._nodes — cas réseau IIDM externe : placer en (0,0) temporaire
                pair_to_equip[("_ext",tid)].append(("transformer",tid,0,0,0,0))

        # Construire index rank + positions avec offset
        rank_index  = {}   # equip_id → (n_total, rank)
        coord_index = {}   # equip_id → (x1,y1,x2,y2)  avant offset

        for key, items in pair_to_equip.items():
            n_total = len(items)
            for rank, (etype, eid, x1,y1,x2,y2) in enumerate(items):
                rank_index[eid]  = (n_total, rank)
                coord_index[eid] = (x1,y1,x2,y2)

        return rank_index, coord_index

    def draw_network(self):
        c=self.canvas; c.delete('all')
        W=c.winfo_width(); H=c.winfo_height()
        if W<80 or H<80: return
        tx,ty,scale=self._transform()
        c.create_text(W-6,H-8,text=f"zoom {self._zoom*100:.0f}%",
                      font=mono(7),fill=T_SEC,anchor='se')

        # Positions canvas de chaque nœud
        nd_pos={nd["id"]:(tx(nd["x"]),ty(nd["y"])) for nd in self._nodes}

        # ── Calcul des groupes parallèles (lignes + transformateurs)
        rank_index, coord_index = self._build_parallel_groups(nd_pos)
        spacing = max(12, 16*scale)   # espacement adaptatif au zoom

        # ── Lignes
        for line in self._lines:
            x1,y1 = nd_pos[line["from"]]; x2,y2 = nd_pos[line["to"]]
            n_tot, rank = rank_index.get(line["id"], (1,0))
            dx, dy = self._perp_offset(x1,y1,x2,y2, rank, n_tot, spacing)
            ox1,oy1 = x1+dx, y1+dy
            ox2,oy2 = x2+dx, y2+dy

            is_open = line["id"] in self._open_lines
            if is_open:
                self._draw_open_line(c, ox1,oy1,ox2,oy2, line)
            else:
                lf = self.line_results.get(line["id"],{})
                loading = lf.get("loading_pct",0)
                lcol = RED if loading>90 else AMBER if loading>70 else "#2a3a5c"
                lw   = 3.5 if loading>90 else 2.5 if loading>70 else 2
                self._draw_pi_line(c, ox1,oy1,ox2,oy2, line, lf, lcol, lw, scale,
                                   n_tot=n_tot, rank=rank)

        # ── Transformateurs (lus depuis l'IIDM)
        for tid, tr in self.transformer_results.items():
            nd1 = next((nd["id"] for nd in self._nodes if nd["vl"]==tr["vl1"]), None)
            nd2 = next((nd["id"] for nd in self._nodes if nd["vl"]==tr["vl2"]), None)
            if not nd1 or not nd2 or nd1 not in nd_pos or nd2 not in nd_pos:
                continue
            x1,y1 = nd_pos[nd1]; x2,y2 = nd_pos[nd2]
            n_tot, rank = rank_index.get(tid, (1,0))
            dx, dy = self._perp_offset(x1,y1,x2,y2, rank, n_tot, spacing)
            ox1,oy1 = x1+dx, y1+dy
            ox2,oy2 = x2+dx, y2+dy

            is_open = tid in self._open_lines
            self._draw_transformer(c, ox1,oy1,ox2,oy2, tid, tr, scale, is_open)

        # ── Shunts
        sh_by_node={}
        for sh in self._shunts: sh_by_node.setdefault(sh["node"],[]).append(sh)

        # ── Nœuds
        r=max(20,min(40,int(scale*20)))
        for nd in self._nodes:
            nx,ny=nd_pos[nd["id"]]; nid=nd["id"]
            gn=next((g for g in self._generators if g["node"]==nid),None)
            ln=next((l for l in self._loads       if l["node"]==nid),None)

            es    = self.node_results.get(nid,{}).get("energy_source",None)
            is_pv = self.node_results.get(nid,{}).get("is_pv",None)

            if es == "NUCLEAR":
                col = BLUE if (is_pv and nid=="N1") else GREEN
                sym = "[SM-PV]"; ctrl = "PV"
            elif es == "WIND":
                col=PURPLE; sym="[Eo-PQ]"; ctrl="PQ"
            elif es == "SOLAR":
                col=AMBER;  sym="[PV-PQ]"; ctrl="PQ"
            elif es == "HYDRO":
                col=CYAN;   sym="[HY-PV]"; ctrl="PV"
            elif es == "THERMAL":
                col=ORANGE; sym="[TH-PV]"; ctrl="PV"
            elif gn:
                if gn["type"]=="synchronous":
                    col=BLUE if nid=="N1" else GREEN; sym="[SM]"; ctrl="PV"
                elif gn["type"]=="wind":
                    col=PURPLE; sym="[Eo]"; ctrl="PQ"
                else:
                    col=AMBER; sym="[PV]"; ctrl="PQ"
            elif ln:
                col=RED; sym="[Ch]"; ctrl=""
            else:
                col=T_SEC; sym="[?]"; ctrl=""

            if self._show['shunts'].get() and nid in sh_by_node:
                self._draw_shunts(c,nx,ny,r,sh_by_node[nid])

            is_open_node = nid in self._open_nodes
            node_col = "#444444" if is_open_node else col

            c.create_oval(nx-r-5,ny-r-5,nx+r+5,ny+r+5,
                          fill='',outline=node_col,width=1,dash=(4,4))
            c.create_oval(nx-r,ny-r,nx+r,ny+r,
                          fill=CARD if not is_open_node else "#1a1a1a",
                          outline=node_col,width=2.5)
            c.create_text(nx,ny-9,text=sym,font=mono(7,True),fill=node_col)
            c.create_text(nx,ny+4,text=nid,font=mono(8,True),
                          fill=T_PRI if not is_open_node else T_SEC)
            if ctrl:
                ctrl_col=GREEN if ctrl=="PV" else TEAL
                c.create_text(nx,ny+16,text=ctrl,font=mono(6,True),fill=ctrl_col)
            if is_open_node:
                d=r*0.55
                c.create_line(nx-d,ny-d,nx+d,ny+d,fill=RED,width=3)
                c.create_line(nx+d,ny-d,nx-d,ny+d,fill=RED,width=3)
                c.create_text(nx,ny-r-14,text="H.T.",font=mono(7,True),fill=RED)

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

        Pl=sum(self.load_vars[l["id"]]['P'].get() for l in self._loads
               if l["id"] in self.load_vars and 'P' in self.load_vars[l["id"]])
        Ql=sum(self.load_vars[l["id"]]['Q'].get() for l in self._loads
               if l["id"] in self.load_vars and 'Q' in self.load_vars[l["id"]])
        c.create_text(W/2,H-10,
                      text=f"Total load: {Pl:.0f} MW  /  {Ql:.0f} Mvar",
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

    def _draw_pi_line(self,c,x1,y1,x2,y2,line,lf,lcol,lw,scale,n_tot=1,rank=0):
        """Dessine une ligne avec schéma en π. Les coords passées incluent déjà l'offset parallèle."""
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

        # Étiquette numéro de ligne si parallèles
        if n_tot > 1:
            mx0=(x1+x2)/2; my0=(y1+y2)/2
            c.create_text(mx0+perp_x*8, my0+perp_y*8,
                          text=line["id"], font=mono(6), fill=lcol, anchor='center')

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

    def _draw_transformer(self, c, x1,y1,x2,y2, tid, tr, scale, is_open):
        """
        Dessine un transformateur deux enroulements avec :
          ─── (segment HT) ─ (O)(O) ─ (segment BT) ───
          Deux cercles accolés au centre représentent les enroulements.
          Si ouvert : tirets + carré barré rouge.
          Labels : rapport de transformation, P/Q transit, impédance.
        """
        TCOL  = "#e0a020"   # couleur dédiée transformateurs
        TGRAY = "#444455"

        angle = math.atan2(y2-y1, x2-x1)
        cos_a = math.cos(angle); sin_a = math.sin(angle)
        perp_x = -sin_a;         perp_y = cos_a
        mx = (x1+x2)/2;          my = (y1+y2)/2
        lw = 2.5

        if is_open:
            # Tirets gris + symbole ouvert
            c.create_line(x1,y1,x2,y2, fill=TGRAY, width=2, dash=(6,5))
            sz=10
            pts=[mx-cos_a*sz-sin_a*sz, my-sin_a*sz+cos_a*sz,
                 mx+cos_a*sz-sin_a*sz, my+sin_a*sz+cos_a*sz,
                 mx+cos_a*sz+sin_a*sz, my+sin_a*sz-cos_a*sz,
                 mx-cos_a*sz+sin_a*sz, my-sin_a*sz-cos_a*sz]
            c.create_polygon(*pts, fill=BG, outline=RED, width=2)
            c.create_line(mx-cos_a*sz+sin_a*sz, my-sin_a*sz-cos_a*sz,
                          mx+cos_a*sz-sin_a*sz, my+sin_a*sz+cos_a*sz,
                          fill=RED, width=2)
            c.create_text(mx+perp_x*18, my+perp_y*18,
                          text=f"{tid}\nH.T.", font=mono(6,True), fill=RED)
            return

        # ── Rayon des cercles proportionnel au zoom
        rcirc = max(8, min(18, int(12*scale)))

        # Points de tangence des cercles sur la ligne
        t1x = mx - cos_a*rcirc;  t1y = my - sin_a*rcirc   # centre cercle 1 (côté 1)
        t2x = mx + cos_a*rcirc;  t2y = my + sin_a*rcirc   # centre cercle 2 (côté 2)

        # Segments de connexion nœud → tangence extérieure du cercle
        c.create_line(x1,y1, t1x-cos_a*rcirc, t1y-sin_a*rcirc,
                      fill=TCOL, width=lw)
        c.create_line(t2x+cos_a*rcirc, t2y+sin_a*rcirc, x2,y2,
                      fill=TCOL, width=lw)

        # Les deux cercles représentant les enroulements
        loading = tr.get("loading_pct", 0)
        ring_col = RED if loading>90 else AMBER if loading>70 else TCOL
        for cx,cy in ((t1x,t1y),(t2x,t2y)):
            c.create_oval(cx-rcirc, cy-rcirc, cx+rcirc, cy+rcirc,
                          fill=CARD, outline=ring_col, width=2.5)

        # ── Labels rapport de transformation
        u1 = tr.get("rated_u1", 0); u2 = tr.get("rated_u2", 0)
        lx = mx + perp_x*22; ly = my + perp_y*22
        ratio_txt = f"{tid}"
        if u1 and u2:
            ratio_txt += f"  {u1:.0f}/{u2:.0f}kV"
        for ddx,ddy in ((1,0),(-1,0),(0,1),(0,-1)):
            c.create_text(lx+ddx,ly-8+ddy, text=ratio_txt,
                          font=mono(6), fill=BG)
        c.create_text(lx, ly-8, text=ratio_txt,
                      font=mono(6,True), fill=TCOL)

        # ── Impédance si activée
        if self._show['impedances'].get():
            X_pu = tr.get("X_pu", 0)
            z_base = (u1**2 / BASE_MVA) if u1 else Z_BASE
            x_pu_norm = X_pu / z_base if z_base else 0
            c.create_text(lx, ly+5, text=f"X={x_pu_norm:.4f}pu",
                          font=mono(6), fill=ORANGE)

        # ── Flux P/Q
        if self._show['flux'].get():
            P = tr.get("P_from", 0); Q = tr.get("Q_from", 0)
            if P==P:   # not NaN
                fx = mx - perp_x*26; fy = my - perp_y*26
                for ddx,ddy in ((1,0),(-1,0),(0,1),(0,-1)):
                    c.create_text(fx+ddx,fy-8+ddy,text=f"P:{P:+.0f}MW",font=mono(7),fill=BG)
                    c.create_text(fx+ddx,fy+5+ddy,text=f"Q:{Q:+.0f}Mvar",font=mono(7),fill=BG)
                c.create_text(fx,fy-8, text=f"P:{P:+.0f}MW",  font=mono(7,True),fill=BLUE)
                c.create_text(fx,fy+5, text=f"Q:{Q:+.0f}Mvar",font=mono(7),     fill=TEAL)

        # ── Flèche de direction
        if self._show['fleches'].get():
            P = tr.get("P_from", 0)
            if P==P and abs(P)>0.5:
                fa = angle if P>0 else angle+math.pi
                ax = x1+(x2-x1)*0.55; ay = y1+(y2-y1)*0.55
                c.create_line(ax-math.cos(fa)*8, ay-math.sin(fa)*8,
                              ax+math.cos(fa)*8, ay+math.sin(fa)*8,
                              fill=ring_col, width=2.5,
                              arrow='last', arrowshape=(8,10,4))

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
