"""Algebraic regression for linearized validity/error formulas; not a PDE theorem."""
import math
import random
import unittest
from pathlib import Path

def dot(a,b): return sum(x*y for x,y in zip(a,b))

class TheoryChecks(unittest.TestCase):
    def test_activation_tangent(self):
        f=lambda x:4*x-3*x*x
        self.assertAlmostEqual(f(2/3),4/3)
        self.assertEqual(f(0),0.)
        self.assertEqual(f(1),1.)
        self.assertLessEqual(max(f(i/1000) for i in range(1001)),4/3)
    def test_taut_elastic_tangent(self):
        rng=random.Random(5)
        for unused in range(40):
            t=[rng.uniform(-1,1) for i in range(3)]
            norm=math.sqrt(dot(t,t)); t=[x/norm for x in t]
            v=[rng.uniform(-1,1) for i in range(3)]
            ka,kt=3.,.4
            q=ka*dot(t,v)**2+kt*(dot(v,v)-dot(t,v)**2)
            self.assertGreaterEqual(q,min(ka,kt)*dot(v,v)-1e-13)
    def test_axial_viscosity_is_not_uniformly_elliptic(self):
        t=[1.,0.,0.]; transverse=[0.,1.,0.]
        self.assertEqual(2*dot(t,transverse)**2,0.)
        self.assertGreater(2*dot(t,t)**2,0.)
    def test_schur_complement_keeps_internal_forcing(self):
        a,b,c,d=3.,.4,.4,2.
        fq,fz=1.,.7
        q=(fq-b*fz/d)/(a-b*c/d)
        z=(fz-c*q)/d
        self.assertAlmostEqual(a*q+b*z,fq)
        self.assertAlmostEqual(c*q+d*z,fz)
        self.assertNotAlmostEqual(q,fq/(a-b*c/d))
    def test_resolvent_bound(self):
        masses=[2.,1.]; stiffness=[8.,9.]
        wint=min(math.sqrt(k/m) for k,m in zip(stiffness,masses))
        for r in (0.,.01,.2,.7,.95):
            w=r*wint
            error=max(abs(k/(k-w*w*m)-1) for k,m in zip(stiffness,masses))
            self.assertLessEqual(error,r*r/(1-r*r)+1e-12)
    def test_small_mass_does_not_imply_small_internal_energy(self):
        for eps in (1e-1,1e-3,1e-6):
            self.assertAlmostEqual(.5*eps**2*(1/eps)**2,.5)
    def test_eigenfrequency_perturbation(self):
        k,m,dk,dm=8.,2.,.3,.2
        f=lambda e:math.sqrt((k+e*dk)/(m+e*dm))
        h=1e-5; omega=f(0)
        rel=(f(h)-f(-h))/(2*h)/omega
        self.assertAlmostEqual(rel,(dk-omega**2*dm)/(2*omega**2*m),places=9)
    def test_phase_horizon_and_position_error(self):
        rng=random.Random(27)
        for unused in range(40):
            phi=rng.uniform(-20,20); delta=rng.uniform(-1,1); amplitude=.3
            error=abs(amplitude*(math.cos(phi+delta)-math.cos(phi)))
            self.assertLessEqual(error,amplitude*abs(delta)+1e-14)
        self.assertAlmostEqual(100*.002,.2)
    def test_document_invariants(self):
        s=Path('01_最终理论/01-前向预测理论.md').read_text()
        tags=[v.split('}',1)[0] for v in s.split(chr(92)+'tag{')[1:]]
        self.assertGreater(len(tags),55)
        self.assertEqual(len(tags),len(set(tags)))
        self.assertEqual(sum(line.strip()=='$$' for line in s.splitlines())%2,0)
        for tag in ['F.16a','F.16b','F.16c','F.16d','T.22','T.23','T.24','T.25','T.26','T.27','T.28']:
            self.assertIn(tag,tags)
        self.assertIn('不是整个非线性轨迹的误差界',s)
        self.assertIn('不能在同一条轨迹中临时互换',s)
if __name__=='__main__': unittest.main(verbosity=2)
