"""Closed-form references used only to validate the solver."""
import math

def microstrip_hammerstad(w, h, er, t=0.0):
    """Hammerstad-Jensen microstrip Z0 and eps_eff (thin strip, t correction from Hammerstad 1975)."""
    u = w / h
    if t > 0:
        # Hammerstad & Jensen thickness correction (eq. 6-7, 1980)
        th = t / h
        du1 = th / math.pi * math.log(1 + 4 * math.e / th / (1 / math.tanh(math.sqrt(6.517 * u))) ** 2)
        dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * du1
        u1, ur = u + du1, u + dur
    else:
        u1 = ur = u
    def z01(u):
        f = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / u) ** 0.7528)
        return 60 * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))
    a = 1 + math.log((ur ** 4 + (ur / 52) ** 2) / (ur ** 4 + 0.432)) / 49 + math.log(1 + (ur / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    ee = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / ur) ** (-a * b)
    # thickness correction for eps_eff
    ee = ee * (z01(u1) / z01(ur)) ** 2
    z0 = z01(ur) / math.sqrt(ee)
    return z0, ee

def stripline_cohn(w, b, er, t=0.0):
    """Symmetric stripline, IPC-2141 / Cohn (zero thickness when t=0)."""
    if t == 0:
        k = 1 / math.cosh(math.pi * w / (2 * b))
        return 30 * math.pi / math.sqrt(er) * ellipk(math.sqrt(1 - k * k)) / ellipk(k)
    # Wheeler with thickness (Wadell)
    m = 6 * (b - t) / (3 * b - t)
    x = t / b
    w_eff = w + x / math.pi * (1 - 0.5 * math.log((x / (2 - x)) ** 2 + (0.0796 * x / (w / b + 1.1 * x)) ** m)) * b
    return 30 / math.sqrt(er) * math.log(1 + 4 * (b - t) / (math.pi * w_eff) * (8 * (b - t) / (math.pi * w_eff) + math.sqrt((8 * (b - t) / (math.pi * w_eff)) ** 2 + 6.27)))

def ellipk(k):
    from scipy.special import ellipk as K
    return K(k * k)

def cpw_wen(w, s, er):
    """Infinitely thick substrate CPW (Wen), no ground."""
    k = w / (w + 2 * s)
    kp = math.sqrt(1 - k * k)
    ee = (er + 1) / 2
    return 30 * math.pi / math.sqrt(ee) * ellipk(kp) / ellipk(k), ee

def cpwg(w, s, h, er):
    """Grounded CPW, conformal mapping (Ghione & Naldi)."""
    k = w / (w + 2 * s)
    kp = math.sqrt(1 - k * k)
    k3 = math.tanh(math.pi * w / (4 * h)) / math.tanh(math.pi * (w + 2 * s) / (4 * h))
    k3p = math.sqrt(1 - k3 * k3)
    r = ellipk(k) / ellipk(kp) + ellipk(k3) / ellipk(k3p)
    ee = (1 + er * ellipk(k3) / ellipk(k3p) / (ellipk(k) / ellipk(kp))) / (1 + ellipk(k3) / ellipk(k3p) / (ellipk(k) / ellipk(kp)))
    return 60 * math.pi / math.sqrt(ee) / r, ee
