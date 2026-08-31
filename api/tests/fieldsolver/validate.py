"""Compare the FEM with closed-form results on plain geometries (custom stackups, no mask)."""
import sys, time
sys.path.insert(0, ".")
from app.services.fieldsolver.templates import Params, build
from app.services.fieldsolver.analysis import solve, SolveOptions
from tests.reference import microstrip_hammerstad, stripline_cohn, cpwg

def stack(layers):
    return {"id": "x", "name": "x", "manufacturer": "-", "layers": layers, "soldermask": None}

opts = SolveOptions(f_sweep=[], return_field=False, eps_model="constant")

def run(p):
    t = time.time(); r = solve(build(p), opts); return r["summary"], r["mesh"], time.time() - t

er = 4.4
# microstrip, thin copper
for w in (0.2, 0.4, 0.8):
    st = stack([{"type":"copper","name":"L1","thickness_mm":0.005},
                {"type":"dielectric","material":None,"thickness_mm":0.2, "label":"d"},
                {"type":"copper","name":"L2","thickness_mm":0.035}])
    st["layers"][1]["material"] = "isola_370hr_7628"  # placeholder, overridden below
    p = Params(template="microstrip", custom_stackup=st, w=w, soldermask=False, reference_layers=["L2"])
    # constant er: use a synthetic material via eps override
    from app.services.fieldsolver import materials
    materials.LIB.materials["const44"] = materials.Material({"id":"const44","manufacturer":"-","name":"c","kind":"dielectric","points":[{"f_hz":1e9,"dk":er,"tand":0}]})
    st["layers"][1]["material"] = "const44"
    s, m, dt = run(p)
    z, ee = microstrip_hammerstad(w, 0.2, er, t=0.005)
    print(f"microstrip w={w} t=5um: FEM Z0={s['Z0']:.2f} eeff={s['eps_eff']:.3f} | H-J Z0={z:.2f} eeff={ee:.3f} | {m['nodes']} nodes {dt:.1f}s")

# stripline
for w in (0.15, 0.3):
    st = stack([{"type":"copper","name":"L1","thickness_mm":0.035},
                {"type":"dielectric","material":"const44","thickness_mm":0.5,"label":"d"},
                {"type":"copper","name":"L2","thickness_mm":0.005},
                {"type":"dielectric","material":"const44","thickness_mm":0.5,"label":"d"},
                {"type":"copper","name":"L3","thickness_mm":0.035}])
    p = Params(template="microstrip", custom_stackup=st, signal_layer="L2", reference_layers=["L1","L3"], w=w, soldermask=False)
    s, m, dt = run(p)
    z = stripline_cohn(w, 1.005, er, t=0.005)
    print(f"stripline w={w} b=1.005: FEM Z0={s['Z0']:.2f} eeff={s['eps_eff']:.3f} | Wheeler Z0={z:.2f} | {m['nodes']} nodes {dt:.1f}s")

# grounded CPW, thin copper
for w, g in ((0.3, 0.2), (0.5, 0.15)):
    st = stack([{"type":"copper","name":"L1","thickness_mm":0.005},
                {"type":"dielectric","material":"const44","thickness_mm":0.2,"label":"d"},
                {"type":"copper","name":"L2","thickness_mm":0.035}])
    p = Params(template="cpw", custom_stackup=st, w=w, gap=g, soldermask=False, reference_layers=["L2"])
    s, m, dt = run(p)
    z, ee = cpwg(w, g, 0.2, er)
    print(f"cpwg w={w} g={g}: FEM Z0={s['Z0']:.2f} eeff={s['eps_eff']:.3f} | conformal Z0={z:.2f} eeff={ee:.3f} | {m['nodes']} nodes {dt:.1f}s")
