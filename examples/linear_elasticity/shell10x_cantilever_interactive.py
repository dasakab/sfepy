#!/usr/bin/env python
"""
The bending of a long thin cantilever beam computed using the dw_shell10x term.
"""
from optparse import OptionParser
import numpy as nm

import sys
sys.path.append('.')

from sfepy.base.base import output, IndexedStruct
from sfepy.discrete import (FieldVariable, Material, Integral,
                            Equation, Equations, Problem)
from sfepy.discrete.fem import Mesh, FEDomain, Field
from sfepy.terms import Term
from sfepy.discrete.conditions import Conditions, EssentialBC
from sfepy.solvers.ls import ScipyDirect
from sfepy.solvers.nls import Newton
from sfepy.mesh.mesh_generators import gen_block_mesh
import sfepy.mechanics.shell10x as sh

def make_domain(dims, shape):
    """
    Generate a 2D rectangle domain in 3D space, define regions.
    """
    _mesh = gen_block_mesh(dims, shape, [0, 0], name='shell100', verbose=False)

    coors = nm.c_[_mesh.coors, nm.zeros(_mesh.n_nod, dtype=nm.float64)]
    coors = nm.ascontiguousarray(coors)

    conns = [_mesh.get_conn(_mesh.descs[0])]

    mesh = Mesh.from_data(_mesh.name, coors, _mesh.cmesh.vertex_groups, conns,
                          [_mesh.cmesh.cell_groups], _mesh.descs)

    xmin = (-0.5 + 1e-8) * dims[0]
    xmax = (0.5 - 1e-8) * dims[0]

    domain = FEDomain('domain', mesh)
    domain.create_region('Omega', 'all')
    domain.create_region('Gamma1', 'vertices in (x < %.10f)' % xmin, 'facet')
    domain.create_region('Gamma2', 'vertices in (x > %.10f)' % xmax, 'facet')

    return domain

def solve_problem(shape, dims, young, poisson, force):
    domain = make_domain(dims[:2], shape)

    omega = domain.regions['Omega']
    gamma1 = domain.regions['Gamma1']
    gamma2 = domain.regions['Gamma2']

    field = Field.from_args('fu', nm.float64, 6, omega, approx_order=1,
                            poly_space_base='shell10x')
    u = FieldVariable('u', 'unknown', field)
    v = FieldVariable('v', 'test', field, primary_var_name='u')

    thickness = dims[2]
    pload = [[0.0, 0.0, force / shape[1], 0.0, 0.0, 0.0]] * shape[1]

    m = Material('m', D=sh.create_elastic_tensor(young=210e9, poisson=0.3),
                 values={'.drill' : 1e-7})
    load = Material('load', values={'.val' : pload})

    aux = Integral('i', order=3)
    qp_coors, qp_weights = aux.get_qp('3_8')
    qp_coors[:, 2] = thickness * (qp_coors[:, 2] - 0.5)
    qp_weights *= thickness

    integral = Integral('i', coors=qp_coors, weights=qp_weights, order='custom')

    t1 = Term.new('dw_shell10x(m.D, m.drill, v, u)',
                  integral, omega, m=m, v=v, u=u)
    t2 = Term.new('dw_point_load(load.val, v)',
                  integral, gamma2, load=load, v=v)
    eq = Equation('balance', t1 - t2)
    eqs = Equations([eq])

    fix_u = EssentialBC('fix_u', gamma1, {'u.all' : 0.0})

    ls = ScipyDirect({})

    nls_status = IndexedStruct()
    nls = Newton({}, lin_solver=ls, status=nls_status)

    pb = Problem('elasticity with shell10x', equations=eqs, nls=nls, ls=ls)
    pb.time_update(ebcs=Conditions([fix_u]))

    state = pb.solve()

    return pb, state, u, gamma2

def get_analytical_displacement(dims, young, force):
    """
    Returns the analytical value of the max. displacement according to
    Euler-Bernoulli theory.
    """
    l, b, h = dims
    moment = b * h**3 / 12.0
    u = force * l**3 / (3 * young * moment)
    return u

usage = """%prog [options]"""
help = {
    'plot' : 'plot the max. displacement w.r.t. number of cells',
    'show' : 'show the results figure',
}

def main():
    parser = OptionParser(usage=usage, version='%prog')
    parser.add_option('-p', '--plot',
                      action="store_true", dest='plot',
                      default=False, help=help['plot'])
    parser.add_option('-s', '--show',
                      action="store_true", dest='show',
                      default=False, help=help['show'])
    options, args = parser.parse_args()

    dims = (0.2, 0.01, 0.001)
    young = 210e9
    poisson = 0.3
    force = -1.0

    u_exact = get_analytical_displacement(dims, young, force)

    log = []
    for nx in xrange(2, 203, 8):
        shape = (nx, 2)

        pb, state, u, gamma2 = solve_problem(shape, dims, young, poisson, force)

        dofs = u.get_state_in_region(gamma2)
        output('DOFs along the loaded edge:')
        output('\n%s' % dofs)

        log.append((nx - 1, dofs[0, 2]))

    pb.save_state('shell10x_cantilever.vtk', state)

    log = nm.array(log)

    output('max. u3 displacements w.r.t. number of cells:')
    output('\n%s' % log)
    output('analytical value:', u_exact)

    if options.plot:
        import matplotlib.pyplot as plt

        plt.rcParams.update({
            'lines.linewidth' : 3,
            'font.size' : 16,
        })

        fig, ax1 = plt.subplots()
        fig.suptitle('max. $u_3$ displacement')

        ax1.plot(log[:, 0], log[:, 1], 'b', label=r'$u_3$')
        ax1.set_xlabel('# of cells')
        ax1.set_ylabel(r'$u_3$')
        ax1.grid(which='both')
        ax1.hlines(u_exact, log[0, 0], log[-1, 0],
                   'r', 'dotted', label=r'$u_3^{analytical}$')

        ax2 = ax1.twinx()
        ax2.semilogy(log[:, 0], nm.abs(log[:, 1] - u_exact), 'g',
                     label=r'$|u_3 - u_3^{analytical}|$')
        ax2.set_ylabel(r'$|u_3 - u_3^{analytical}|$')

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()

        ax2.legend(lines1 + lines2, labels1 + labels2)

        plt.tight_layout()
        ax1.set_xlim([log[0, 0] - 2, log[-1, 0] + 2])

        plt.show()

    if options.show:
        from sfepy.postprocess.viewer import Viewer
        from sfepy.postprocess.domain_specific import DomainSpecificPlot

        scaling = 1.0

        ds = {'uu' : DomainSpecificPlot('plot_displacements',
                                        ['rel_scaling=%s' % scaling])}
        view = Viewer('shell10x_cantilever.vtk')
        view(domain_specific=ds, is_scalar_bar=True, is_wireframe=True,
             opacity={'wireframe' : 0.5})

if __name__ == '__main__':
    main()
