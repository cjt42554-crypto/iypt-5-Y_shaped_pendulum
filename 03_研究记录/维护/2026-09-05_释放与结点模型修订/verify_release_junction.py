#!/usr/bin/env python3
"""Independent checks of the release/J3 theory; not a production solver.

Run from any working directory. Requires numpy, scipy and sympy.
Synthetic parameters and random seed are specified below. No experiment is used.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import platform
import sys
import unittest
import numpy as np
import scipy
from scipy.integrate import quad, solve_ivp
import sympy as sp

ROOT = Path(__file__).resolve().parents[3]
METRICS: dict[str, object] = {}

@dataclass(frozen=True)
class Parameters:
    m: float = 0.1
    mj: float = 0.01
    h: float = 0.25
    ell: float = 0.4
    a: float = 0.2
    b: float = 0.2
    g: float = 9.81

    def __post_init__(self):
        if not all(np.isfinite(v) and v > 0 for v in vars(self).values()):
            raise ValueError('J3 requires finite positive masses and geometry')

    @property
    def sa(self): return float(np.hypot(self.a, self.h))
    @property
    def sb(self): return float(np.hypot(self.b, self.h))

EZ = np.array([0., 0., 1.])
EX = np.array([1., 0., 0.])

def frame(theta):
    return (np.array([0., np.sin(theta), np.cos(theta)]),
            np.array([0., np.cos(theta), -np.sin(theta)]))

def geometry(y, p):
    theta, nu = y[:2]
    n, eta = y[2:5], y[5:8]
    er, et = frame(theta)
    # Intersecting-sphere center chosen as coordinate origin; gravity unchanged.
    j = p.h * er
    bob = j + p.ell * n
    vj = p.h * nu * et
    vb = vj + p.ell * eta
    return j, bob, vj, vb

def j3(y, p):
    theta, nu = y[:2]
    n, eta = y[2:5], y[5:8]
    er, et = frame(theta)
    nt, nr, nz = n @ et, n @ er, n @ EZ
    nudot = (-p.mj*p.g*np.sin(theta) + p.m*nt*(p.g*nz + p.h*nu**2*nr + p.ell*(eta@eta))) / (p.h*(p.mj+p.m*nt**2))
    aj = p.h*(nudot*et-nu**2*er)
    eta_dot = ((np.eye(3)-np.outer(n,n))@(p.g*EZ-aj))/p.ell - (eta@eta)*n
    tl = p.m*(n@(p.g*EZ-aj)+p.ell*(eta@eta))
    w = p.mj*(p.g*EZ-aj)+tl*n
    ta = p.sa/(p.a+p.b)*(w@EX + p.b/p.h*(w@er))
    tb = p.sb/(p.a+p.b)*(p.a/p.h*(w@er)-w@EX)
    return np.r_[nu,nudot,eta,eta_dot], np.array([ta,tb,tl]), aj

def kkt(y, p):
    """Independent Cartesian constraint Hessians, not elimination (J.3)."""
    j, bob, vj, vb = geometry(y, p)
    anchor_a, anchor_b = -p.a*EX, p.b*EX
    delta = bob-j
    gg = np.zeros((3,6))
    gg[0,:3], gg[1,:3] = j-anchor_a, j-anchor_b
    gg[2,:3], gg[2,3:] = -delta, delta
    mm = np.diag([p.mj]*3+[p.m]*3)
    block = np.block([[mm,gg.T],[gg,np.zeros((3,3))]])
    rhs = np.r_[p.mj*p.g*EZ,p.m*p.g*EZ,-vj@vj,-vj@vj,-(vb-vj)@(vb-vj)]
    sol = np.linalg.solve(block,rhs)
    tensions = sol[6:]*np.array([p.sa,p.sb,p.ell])
    return sol[:3],sol[3:6],tensions

def energy(y,p):
    th,nu=y[:2];n=y[2:5]
    _,_,vj,vb=geometry(y,p)
    return .5*p.mj*(vj@vj)+.5*p.m*(vb@vb)+(p.mj+p.m)*p.g*p.h*(1-np.cos(th))+p.m*p.g*p.ell*(1-n@EZ)

def omega(p):
    eta=p.mj/(p.mj+p.m)
    dd=np.sqrt((p.h+p.ell)**2-4*eta*p.h*p.ell)
    return np.sqrt(p.g/p.ell),np.sqrt(2*p.g/(p.h+p.ell+dd)),np.sqrt(p.g*(p.h+p.ell+dd)/(2*eta*p.h*p.ell))

def make_state(th,al,be,nu=0.,aldot=0.,bedot=0.):
    er,et=frame(be)
    n=np.sin(al)*EX+np.cos(al)*er
    eta=aldot*(np.cos(al)*EX-np.sin(al)*er)+bedot*np.cos(al)*et
    return np.r_[th,nu,n,eta]

def rk4(y0,dt,tf,p):
    nsteps=round(tf/dt)
    if abs(nsteps*dt-tf)>1e-12: raise ValueError('tf must be an exact step multiple')
    y=np.array(y0,float)
    for _ in range(nsteps):
        k1=j3(y,p)[0]; k2=j3(y+dt*k1/2,p)[0]
        k3=j3(y+dt*k2/2,p)[0]; k4=j3(y+dt*k3,p)[0]
        y += dt*(k1+2*k2+2*k3+k4)/6
    return y,nsteps

class ReleaseTests(unittest.TestCase):
    def test_01_endpoint_ode_symbolic(self):
        t,m,z,f=sp.symbols('t m z f',positive=True)
        q=f/z*(t-m/z*(1-sp.exp(-z*t/m)))
        self.assertEqual(sp.simplify(m*sp.diff(q,t,2)+z*sp.diff(q,t)-f),0)
        self.assertEqual(q.subs(t,0),0)
        self.assertEqual(sp.diff(q,t).subs(t,0),0)
        self.assertEqual(sp.diff(q,t,2).subs(t,0),f/m)

    def test_02_wave_pde_symbolic(self):
        t,x,c,z,f,m=sp.symbols('t x c z f m',positive=True)
        q=f/z*((t-x/c)-m/z*(1-sp.exp(-z*(t-x/c)/m)))
        self.assertEqual(sp.simplify((z/c)*sp.diff(q,t,2)-(z*c)*sp.diff(q,x,2)),0)
        # The front has no delta term in w_xx or w_tt because q=q'=0 there.
        self.assertEqual(q.subs(t,x/c),0)
        self.assertEqual(sp.diff(q,x).subs(t,x/c),0)

    def test_03_release_energy_not_damping(self):
        f,z,m,t=2.,.8,.12,.31
        tb=m/z
        q=f/z*(t-tb*(1-np.exp(-t/tb)))
        vel=lambda ss:f/z*(-np.expm1(-ss/tb))
        wave_energy=quad(lambda ss:z*vel(ss)**2,0,t,epsabs=1e-13)[0]
        self.assertAlmostEqual(.5*m*vel(t)**2+wave_energy,f*q,places=12)
        METRICS['release_energy_error_J']=abs(.5*m*vel(t)**2+wave_energy-f*q)

    def test_04_velocity_H1_not_H2(self):
        # Analytic v_x has a finite jump at x=c*t. Differentiate this piecewise field.
        m,z,f,c,t=.12,.8,2.,2.,.2
        norms=[]
        for cells in (1000,2000,4000,8000):
            xx=np.linspace(0,1,cells+1);dtau=t-xx/c
            vx=np.where(dtau>0,-f/(m*c)*np.exp(-np.maximum(dtau,0)*z/m),0.)
            h=1/cells
            norms.append((float(np.sqrt(np.trapezoid(vx*vx,xx))),float(np.sqrt(h*np.sum((np.diff(vx)/h)**2)))))
        self.assertLess(abs(norms[-1][0]/norms[-2][0]-1),.002)
        self.assertGreater(norms[-1][1]/norms[-2][1],1.39)
        self.assertLess(norms[-1][1]/norms[-2][1],1.43)
        METRICS['velocity_derivative_norms_H1_H2']=norms

    def test_05_release_ramp_C2_and_nonnegative_weight(self):
        x=sp.symbols('x',real=True)
        chi=1-10*x**3+15*x**4-6*x**5
        self.assertEqual(chi.subs(x,0),1);self.assertEqual(chi.subs(x,1),0)
        for order in (1,2):
            self.assertEqual(sp.diff(chi,x,order).subs(x,0),0)
            self.assertEqual(sp.diff(chi,x,order).subs(x,1),0)
        self.assertEqual(sp.factor(-sp.diff(chi,x)),30*x**2*(x-1)**2)
        self.assertEqual(sp.integrate(-sp.diff(chi,x),(x,0,1)),1)

    def test_06_modal_release_filter_vs_ode(self):
        om,tau=9.2,.6
        chi=lambda t:1-10*(t/tau)**3+15*(t/tau)**4-6*(t/tau)**5
        sol=solve_ivp(lambda t,y:[y[1],om**2*(chi(t)-y[0])],(0,tau),[1.,0.],method='DOP853',rtol=1e-12,atol=1e-14,max_step=.002)
        self.assertTrue(sol.success)
        amp=np.hypot(sol.y[0,-1],sol.y[1,-1]/om)
        w=lambda x:30*x*x*(1-x)**2
        re=quad(lambda x:w(x)*np.cos(om*tau*x),0,1,epsabs=1e-13)[0]
        im=quad(lambda x:w(x)*np.sin(om*tau*x),0,1,epsabs=1e-13)[0]
        self.assertAlmostEqual(amp,np.hypot(re,im),places=11)
        self.assertLessEqual(amp,1)
        METRICS['ramp_modal_amplitude']={'ode':float(amp),'filter':float(np.hypot(re,im))}

    def test_07_dynamic_mass_stiffness_symbolic(self):
        # Endpoint terms of a two-element scalar string: no massless force constraint.
        k,mu,hh,m=sp.symbols('k mu hh m',positive=True)
        mass=sp.diag(mu*hh,mu*hh/2+m)
        stiffness=(k/hh)*sp.Matrix([[2,-1],[-1,1]])
        self.assertEqual(stiffness,stiffness.T)
        self.assertEqual(sp.simplify(stiffness.det()),k**2/hh**2)
        self.assertEqual(sp.simplify((mass.inv()*stiffness)[1,1]),2*k/(hh*(2*m+hh*mu)))

class JunctionTests(unittest.TestCase):
    def test_08_mass_matrix_from_cartesian_kinetic_energy(self):
        th,al,be=sp.symbols('th al be',real=True)
        m,M,h,l=sp.symbols('m M h l',positive=True)
        er=lambda a:sp.Matrix([0,sp.sin(a),sp.cos(a)])
        jj=h*er(th);nn=sp.sin(al)*sp.Matrix([1,0,0])+sp.cos(al)*er(be)
        jacj=jj.jacobian([th,al,be]);jacb=(jj+l*nn).jacobian([th,al,be])
        mat=sp.simplify(M*jacj.T*jacj+m*jacb.T*jacb)
        target=sp.Matrix([[(M+m)*h*h,-m*h*l*sp.sin(al)*sp.sin(be-th),m*h*l*sp.cos(al)*sp.cos(be-th)],[-m*h*l*sp.sin(al)*sp.sin(be-th),m*l*l,0],[m*h*l*sp.cos(al)*sp.cos(be-th),0,m*l*l*sp.cos(al)**2]])
        self.assertEqual(sp.simplify(mat-target),sp.zeros(3))
        det=m*m*h*h*l**4*sp.cos(al)**2*(M+m*sp.cos(al)**2*sp.sin(be-th)**2)
        self.assertEqual(sp.trigsimp(mat.det()-det),0)

    def test_09_randomized_constraint_KKT_acceleration_and_tensions(self):
        rng=np.random.default_rng(520260905)
        errors=[]; force_errors=[]
        for _ in range(120):
            p=Parameters(m=.05+rng.random()*.2,mj=.002+rng.random()*.04,h=.15+rng.random()*.2,ell=.2+rng.random()*.3,a=.1+rng.random()*.2,b=.1+rng.random()*.2)
            y=make_state(*rng.uniform(-.3,.3,3),*rng.uniform(-.4,.4,3))
            dy,tt,aj=j3(y,p);a0,b0,t0=kkt(y,p)
            err=max(np.max(abs(aj-a0)),np.max(abs(aj+p.ell*dy[5:8]-b0)))
            errors.append(err);force_errors.append(np.max(abs(tt-t0)))
        self.assertLess(max(errors),3e-11)
        self.assertLess(max(force_errors),3e-11)
        METRICS['random_KKT_max_acceleration_error_m_s2']=float(max(errors))
        METRICS['random_KKT_max_tension_error_N']=float(max(force_errors))
        METRICS['random_seed']=520260905

    def test_10_geometric_lengths_and_tangent_constraints(self):
        p=Parameters();y=make_state(.21,-.13,.31,.2,-.1,.4)
        j,b,vj,vb=geometry(y,p);dy,_,_=j3(y,p)
        self.assertAlmostEqual(np.linalg.norm(j+p.a*EX),p.sa,places=13)
        self.assertAlmostEqual(np.linalg.norm(j-p.b*EX),p.sb,places=13)
        self.assertAlmostEqual(np.linalg.norm(b-j),p.ell,places=13)
        self.assertAlmostEqual(y[2:5]@dy[2:5],0,places=13)
        self.assertAlmostEqual(y[5:8]@y[5:8]+y[2:5]@dy[5:8],0,places=13)

    def test_11_equilibrium_tensions(self):
        p=Parameters(a=.13,b=.24);dy,tt,_=j3(make_state(0,0,0),p)
        self.assertLess(np.max(abs(dy)),1e-13)
        expected=[(p.m+p.mj)*p.g*p.sa*p.b/((p.a+p.b)*p.h),(p.m+p.mj)*p.g*p.sb*p.a/((p.a+p.b)*p.h),p.m*p.g]
        np.testing.assert_allclose(tt,expected,rtol=1e-13,atol=1e-13)

    def test_12_energy_derivative_random_states(self):
        p=Parameters();rng=np.random.default_rng(55);errs=[]
        for _ in range(60):
            y=make_state(*rng.uniform(-.3,.3,3),*rng.uniform(-.4,.4,3))
            dy,_,aj=j3(y,p);_,_,vj,vb=geometry(y,p);ab=aj+p.ell*dy[5:8]
            edot=p.mj*(vj@(aj-p.g*EZ))+p.m*(vb@(ab-p.g*EZ))
            errs.append(abs(edot))
        self.assertLess(max(errs),1e-12)
        METRICS['max_energy_derivative_residual_W']=float(max(errs))

    def test_13_linear_characteristic_polynomial(self):
        M,m,h,l,g,x=sp.symbols('M m h l g x',positive=True)
        mat=sp.Matrix([[(M+m)*h*h,m*h*l],[m*h*l,m*l*l]])
        stiffness=sp.diag((M+m)*g*h,m*g*l)
        target=(M+m)*m*h*l*(M/(M+m)*h*l*x*x-g*(h+l)*x+g*g)
        self.assertEqual(sp.cancel((stiffness-x*mat).det()-target),0)

    def test_14_linear_frequencies_from_independent_Cartesian_linearization(self):
        p=Parameters();z0=np.zeros(6)
        def reduced(z):
            th,nu,xx,vx,yy,vy=z
            nz=np.sqrt(1-xx*xx-yy*yy)
            n=np.array([xx,yy,nz]);eta=np.array([vx,vy,-(xx*vx+yy*vy)/nz])
            y=np.r_[th,nu,n,eta]
            aj,ab,_=kkt(y,p)
            _,et=frame(th)
            return np.array([nu,aj@et/p.h,vx,(ab-aj)[0]/p.ell,vy,(ab-aj)[1]/p.ell])
        eps=1e-6;eye=np.eye(6)*eps
        jac=np.column_stack([(reduced(z0+ee)-reduced(z0-ee))/(2*eps) for ee in eye])
        eig=np.linalg.eigvals(jac)
        positive=sorted(float(v.imag) for v in eig if v.imag>0)
        np.testing.assert_allclose(positive,sorted(omega(p)),rtol=2e-9,atol=2e-9)
        METRICS['linear_frequencies_rad_s']={'formula':sorted(omega(p)),'KKT_jacobian':positive}

    def test_15_massless_low_mode_limit_and_high_mode(self):
        p=Parameters(mj=1e-9);wx,wm,wp=omega(p)
        self.assertAlmostEqual(wm/np.sqrt(p.g/(p.h+p.ell)),1,places=8)
        self.assertGreater(wp,1000)
        eta=p.mj/(p.mj+p.m)
        self.assertAlmostEqual(wp*wp*eta*p.h*p.ell/(p.g*(p.h+p.ell)),1,places=8)
        p=Parameters();_,wm,wp=omega(p);wt=np.sqrt(p.g/(p.h+p.ell))
        METRICS['synthetic_10_percent_junction_example']={'parameters_SI':vars(p),'relative_low_frequency_change':float(wm/wt-1),'20s_linear_phase_difference_rad':float(20*(wm-wt)),'high_frequency_rad_s':float(wp)}

    def test_16_massless_input_rejected(self):
        with self.assertRaises(ValueError): Parameters(mj=0)
        with self.assertRaises(ValueError): Parameters(mj=float('nan'))

    def test_17_vector_rhs_at_coordinate_pole(self):
        p=Parameters();y=np.r_[.1,.2,1.,0.,0.,0.,.1,0.]
        dy,tt,aj=j3(y,p);aj0,ab0,tt0=kkt(y,p)
        self.assertTrue(np.all(np.isfinite(dy)))
        np.testing.assert_allclose(aj,aj0,atol=1e-12)
        np.testing.assert_allclose(tt,tt0,atol=1e-12)

    def test_18_common_plane_is_not_an_invariant_constraint(self):
        p=Parameters();th=.2;y=make_state(th,0,th)
        dy,_,_=j3(y,p);_,et=frame(th)
        beta_acc=dy[5:8]@et
        self.assertGreater(abs(beta_acc-dy[1]),1.)

    def test_19_nonlinear_trajectory_energy_and_constraints(self):
        p=Parameters();y0=make_state(.05,.04,.045)
        sol=solve_ivp(lambda t,y:j3(y,p)[0],(0,2),y0,method='DOP853',rtol=2e-12,atol=2e-14,max_step=.005,dense_output=True)
        self.assertTrue(sol.success)
        ys=sol.sol(np.linspace(0,2,401)).T
        ee=np.array([energy(y,p) for y in ys]);tensions=np.array([j3(y,p)[1] for y in ys])
        unit_error=max(abs(np.linalg.norm(y[2:5])-1) for y in ys)
        tangent_error=max(abs(y[2:5]@y[5:8]) for y in ys)
        self.assertLess(np.max(abs(ee-ee[0])),1e-11)
        self.assertLess(unit_error,1e-11);self.assertLess(tangent_error,1e-10)
        self.assertGreater(tensions.min(),0)
        METRICS['2s_nonlinear_reference']={'absolute_energy_drift_J':float(np.max(abs(ee-ee[0]))),'unit_constraint_error':float(unit_error),'tangent_constraint_error':float(tangent_error),'minimum_sampled_tension_N':float(tensions.min()),'accepted_steps':int(len(sol.t)-1)}

    def test_20_real_fixed_step_refinement(self):
        p=Parameters();y0=make_state(.05,.04,.045)
        ref=solve_ivp(lambda t,y:j3(y,p)[0],(0,2),y0,method='DOP853',rtol=2e-13,atol=2e-15,max_step=.002)
        self.assertTrue(ref.success)
        errs=[];counts=[]
        for dt in (.01,.005,.0025,.00125):
            y,n=rk4(y0,dt,2,p);counts.append(n);errs.append(float(np.linalg.norm(y-ref.y[:,-1])))
        self.assertEqual(counts,[200,400,800,1600])
        self.assertGreater(errs[0]/errs[1],12);self.assertGreater(errs[1]/errs[2],12)
        self.assertLess(errs[0]/errs[1],20);self.assertLess(errs[1]/errs[2],20)
        METRICS['RK4_refinement']={'steps':counts,'final_state_errors':errs,'observed_orders':[float(np.log2(a/b)) for a,b in zip(errs[:-1],errs[1:])], 'state_scaling':'angles and n dimensionless; angular rates multiplied by 1 second'}

class DocumentTests(unittest.TestCase):
    def test_21_corrected_class_and_new_formulas_present(self):
        s=(ROOT/'01_最终理论/01-前向预测理论.md').read_text()
        self.assertIn(r"C^0([0,t');H^2",s)
        self.assertIn(r"C^1([0,t');H^1",s)
        self.assertNotIn(r"C^1([0,t');H^2",s)
        self.assertIn(r'\boldsymbol v_{i0}\in H^1',s)
        for key in ('F.16e','F.16j','F.31a','F.31g','J.1','J.3','J.13'):
            self.assertEqual(s.count(r'\tag{'+key+'}'),1)
        self.assertIn('m_J+m n_\\theta^2',s)
        self.assertIn('YP-FWD-J3-v1',s)

    def test_22_labels_and_math_blocks(self):
        import re
        s=(ROOT/'01_最终理论/01-前向预测理论.md').read_text()
        labels=re.findall(r'\\tag\{([^{}]+)\}',s)
        self.assertEqual(len(labels),len(set(labels)))
        self.assertEqual(sum(line.strip()=='$$' for line in s.splitlines())%2,0)
        self.assertNotIn('nu_j',s)
        self.assertEqual((ROOT/'00_项目管理/交接说明_history.md').stat().st_size,0)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    METRICS['environment']={'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,'scipy':scipy.__version__,'sympy':sp.__version__}
    theory=ROOT/'01_最终理论/01-前向预测理论.md'
    METRICS['forward_theory_sha256']=hashlib.sha256(theory.read_bytes()).hexdigest()
    METRICS['verification_script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    METRICS['tests']={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}
    Path(__file__).with_name('results.json').write_text(json.dumps(METRICS,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(METRICS,ensure_ascii=False,indent=2))
    sys.exit(not result.wasSuccessful())
