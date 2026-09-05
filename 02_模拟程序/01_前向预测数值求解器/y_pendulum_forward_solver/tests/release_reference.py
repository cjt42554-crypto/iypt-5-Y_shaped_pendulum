"""Synthetic longitudinal release fixtures and independent linear references."""
from copy import deepcopy
import numpy as np
from scipy.linalg import eigh
from scipy.integrate import quad
from y_pendulum_forward.contracts import THEORY_SHA256


def wave_config(elements=32, max_step=1e-4, *, duration=0., start=0., final_time=.02, output_dt=.005):
    def branch(length):
        return {'L0':length,'mu':.01,'EA':4.,'Ca':0.,'delta':1e-7,
                'c_parallel':0.,'c_perp':0.,'d_parallel':0.,'d_perp':0.,
                'material_domain':{'kind':'open_box','lambda_lower':.005,'lambda_upper':2.,'rate_lower':-100.,'rate_upper':100.}}
    return {'schema_version':'YPS-FWD-CONFIG-1.0','model_id':'FWD-CABLE-1.0','theory_sha256':THEORY_SHA256,'units':'SI',
            'physical':{'g':1e-8,'e_z':[0.,0.,1.],'junction_mass':1e6,'bob_mass':.02,'rho_air':0.,'bob_volume':0.,'bob_c1':0.,'bob_c2':0.,'lambda_min':.005,'T':final_time,'branches':{'A':branch(.1),'B':branch(.1),'lower':branch(1.)}},
            'inputs':{'support_A':{'kind':'constant','value':[-.1025,0.,0.]},'support_B':{'kind':'constant','value':[.1025,0.,0.]},'air_velocity':{'kind':'zero'},'distributed_forces':{k:{'kind':'zero'} for k in ('A','B','lower')},'junction_force':{'kind':'zero'},'bob_force':{'kind':'zero'},'hold_release':{'source':'initial_static_reaction','start':start,'duration':duration,'history':'instantaneous' if duration==0 else 'smoothstep_c1'},'exit_guards':[]},
            'initial_state':{'mode':'STATIC_HOLD_RELEASE','hold':{'fixed_nodes':{'junction':[0.,0.,0.],'bob':[1.0025,0.,0.]}},'seed':{'r_J':[0.,0.,0.],'r_m':[1.0025,0.,0.]}},
            'numerics':{'elements':{'A':1,'B':1,'lower':elements},'quadrature_order':2,'method':'DOP853','rtol':2e-9,'atol':2e-12,'max_step':max_step,'output_dt':output_dt,'event_cluster_tolerance':1e-10,'static_multistart':3,'static_maxiter':500,'static_gradient_tolerance':1e-7,'static_energy_tolerance':1e-10,'static_uniqueness_tolerance':1e-4},'observation':None}


def semi_infinite_wave(xi, time):
    """Positive displacement/velocity point back toward the root; xi starts there."""
    xi=np.asarray(xi)
    delay=time-(1-xi)/20.
    active=np.maximum(delay,0.)
    velocity=.05*(-np.expm1(-active/.1))
    displacement=.05*(active+.1*np.expm1(-active/.1))
    tension=.01*np.exp(-active/.1)
    return displacement,velocity,tension


def hold_fraction(time, start, duration):
    value=np.asarray(time,dtype=float)
    if duration==0:
        return (value<start).astype(float)
    u=np.clip((value-start)/duration,0.,1.)
    return 1-3*u*u+2*u*u*u


def modal_chain(elements):
    """1D scalar P1 mass/stiffness from local quadratic energies, no cable imports."""
    n=elements+1
    M=np.zeros((n,n));K=np.zeros((n,n));M[0,0]=1e6;M[-1,-1]=.02
    h=1/elements
    for i in range(elements):
        ix=np.ix_([i,i+1],[i,i+1])
        M[ix]+=.01*h/6*np.array([[2.,1.],[1.,2.]])
        K[ix]+=4/h*np.array([[1.,-1.],[-1.,1.]])
    # Each anchored upper element contributes its free endpoint coefficient.
    M[0,0]+=2*.01*.1/3;K[0,0]+=2*4/.1
    eigenvalues,V=eigh(K,M)
    force=np.zeros(n);force[0]=.01;force[-1]=-.01
    return np.sqrt(eigenvalues),V,V.T@force,M,K


def modal_release(elements, times, start, duration, *, quadrature=128):
    omega,V,projection,M,K=modal_chain(elements)
    nodes,weights=np.polynomial.legendre.leggauss(quadrature)
    q=[];v=[]
    for time in times:
        modal_q=np.zeros_like(omega);modal_v=np.zeros_like(omega)
        breaks=sorted({0.,float(time),*[x for x in (start,start+duration) if 0.<x<time]})
        for left,right in zip(breaks,breaks[1:]):
            s=(right+left)/2+(right-left)/2*nodes
            load=1-hold_fraction(s,start,duration)
            phase=omega[:,None]*(time-s)
            modal_q+=(right-left)/2*(np.sin(phase)/omega[:,None])@(weights*load)
            modal_v+=(right-left)/2*np.cos(phase)@(weights*load)
        q.append(V@(projection*modal_q));v.append(V@(projection*modal_v))
    return np.asarray(q),np.asarray(v)
