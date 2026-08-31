"""P1 finite element assembly and solution of div(eps grad phi) = 0."""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .mesh import Mesh


def gradients(mesh: Mesh):
    """Per-element basis gradients b, c (shape (m,3) each) and areas."""
    p = mesh.nodes[mesh.tris]           # (m,3,2)
    x, y = p[..., 0], p[..., 1]
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    return b, c, mesh.area


def assemble(mesh: Mesh, eps_e: np.ndarray) -> sp.csr_matrix:
    """Stiffness matrix K with K_ij = sum_e eps_e int grad N_i . grad N_j.

    Dimensionless in 2D: the same K serves in mm or m. eps_e is relative.
    """
    b, c, A = gradients(mesh)
    m = len(mesh.tris)
    Ke = (b[:, :, None] * b[:, None, :] + c[:, :, None] * c[:, None, :]) / (4 * A)[:, None, None]
    Ke *= eps_e[:, None, None]
    rows = np.repeat(mesh.tris, 3, axis=1).reshape(m, 9)
    cols = np.tile(mesh.tris, (1, 3)).reshape(m, 9)
    K = sp.coo_matrix((Ke.reshape(-1), (rows.reshape(-1), cols.reshape(-1))),
                      shape=(mesh.n_nodes, mesh.n_nodes)).tocsr()
    return K


class Solver:
    """Factor K once for the free nodes, then solve for many conductor voltage sets.

    A frequency sweep changes K only through the dispersion of Dk - a few percent over
    decades - so factoring it again at every frequency is wasteful in time and, because
    a sparse LU of this size holds hundreds of megabytes, brutal on memory. Pass `pre`
    (a Solver built at the design frequency) and the new system is solved by conjugate
    gradients with that LU as the preconditioner instead: one factorisation per run.
    """

    def __init__(self, mesh: Mesh, K: sp.csr_matrix, pre: "Solver | None" = None):
        self.mesh = mesh
        self.K = K
        self.fixed = np.where(mesh.node_conductor >= 0)[0]
        self.free = np.where(mesh.node_conductor < 0)[0]
        self.Kff = K[self.free][:, self.free].tocsc()
        self.Kfc = K[self.free][:, self.fixed].tocsr()
        if pre is None or pre.lu is None or len(pre.free) != len(self.free):
            self.lu = spla.splu(self.Kff)
            self.M = None
        else:
            self.lu = None
            n = self.Kff.shape[0]
            self.M = spla.LinearOperator((n, n), matvec=pre.lu.solve, dtype=float)

    def _solve_free(self, rhs: np.ndarray) -> np.ndarray:
        if self.lu is not None:
            return self.lu.solve(rhs)
        x, info = spla.cg(self.Kff, rhs, rtol=1e-11, atol=0.0, M=self.M, maxiter=300)
        if info != 0:                       # preconditioner too far off: fall back honestly
            self.lu = spla.splu(self.Kff)
            self.M = None
            return self.lu.solve(rhs)
        return x

    def solve(self, volt_by_conductor: np.ndarray) -> np.ndarray:
        """volt_by_conductor[k] = potential of conductor k. Returns phi (n,)."""
        phi = np.zeros(self.mesh.n_nodes)
        phi[self.fixed] = volt_by_conductor[self.mesh.node_conductor[self.fixed]]
        rhs = -self.Kfc @ phi[self.fixed]
        phi[self.free] = self._solve_free(rhs)
        return phi


def element_grad(mesh: Mesh, phi: np.ndarray) -> np.ndarray:
    """grad phi per element (m,2), units V/mm when nodes are in mm."""
    b, c, A = gradients(mesh)
    ph = phi[mesh.tris]
    gx = (b * ph).sum(axis=1) / (2 * A)
    gy = (c * ph).sum(axis=1) / (2 * A)
    return np.stack([gx, gy], axis=1)


def element_energy(mesh: Mesh, phi: np.ndarray) -> np.ndarray:
    """int |grad phi|^2 per element (scale invariant in 2D), (m,)."""
    g = element_grad(mesh, phi)
    return (g ** 2).sum(axis=1) * mesh.area


def conductor_boundary_edges(mesh: Mesh):
    """Edges of dielectric elements lying on a conductor.

    Returns arrays: element index, conductor id, edge length (mm), outward
    normal (from conductor into the element, unit).
    """
    tris, nc = mesh.tris, mesh.node_conductor
    els, conds, lens, normals = [], [], [], []
    diel = np.where(mesh.conductor_of < 0)[0]
    for ei in diel:
        t = tris[ei]
        for a, b_, opp in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
            ca, cb = nc[t[a]], nc[t[b_]]
            if ca >= 0 and ca == cb:
                pa, pb, po = mesh.nodes[t[a]], mesh.nodes[t[b_]], mesh.nodes[t[opp]]
                d = pb - pa
                L = np.hypot(*d)
                n = np.array([-d[1], d[0]]) / L
                if np.dot(n, po - pa) < 0:
                    n = -n
                els.append(ei); conds.append(ca); lens.append(L); normals.append(n)
    if not els:
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0), np.zeros((0, 2))
    return np.array(els), np.array(conds), np.array(lens), np.array(normals)
