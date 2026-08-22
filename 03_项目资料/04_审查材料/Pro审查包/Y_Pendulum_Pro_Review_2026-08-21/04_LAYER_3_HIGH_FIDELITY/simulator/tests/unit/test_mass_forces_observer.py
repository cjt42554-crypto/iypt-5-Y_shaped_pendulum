import numpy as np
from ypendulum.elements import CableElementBatch, assemble_mass_matrix
from ypendulum.forces import bob_drag
from ypendulum.observers import PinholeCamera, add_gaussian_noise, sample_with_exposure

def test_mass_matrix_symmetric_positive():
    e=CableElementBatch(node_i=np.array([0]),node_j=np.array([1]),rest_length=np.array([1.]),ea=np.array([1.]),eta_a=np.array([0.]),area=np.array([1e-4]),density=np.array([1000.]),diameter=np.array([.01]),drag_cd_normal=np.array([1.2]),cable_id=np.array([0]))
    m=assemble_mass_matrix(2,e,{1:.2},kind="consistent").toarray(); assert np.allclose(m,m.T); assert np.min(np.linalg.eigvalsh(m))>0

def test_bob_drag_opposes_relative_velocity():
    f,j,d=bob_drag(np.array([1.,-.5,.2]),np.zeros(3),air_density=1.2,radius=.01,cd=.47,linear_coefficient=.03,enabled=True)
    assert np.dot(f,np.array([1.,-.5,.2]))<0; assert d>0; assert np.max(np.linalg.eigvalsh(.5*(j+j.T)))<=1e-12

def test_camera_projection_and_exposure():
    c=PinholeCamera(intrinsic=np.array([[1000.,0,320.],[0,1000.,240.],[0,0,1.]]),rotation_world_to_camera=np.eye(3),translation_world_to_camera=np.zeros(3))
    assert np.allclose(c.project(np.array([[.1,-.2,2.]]))[0],[370.,140.])
    t=np.linspace(0,1,1001); x=t[:,None]**2; ft,a=sample_with_exposure(t,x,frame_rate=10.,exposure_time=.02,sub_samples=101)
    assert np.max(np.abs(a[:,0]-(ft**2+.01**2/3)))<2e-7

def test_synthetic_noise_is_seed_reproducible():
    x=np.zeros((5,2)); assert np.array_equal(add_gaussian_noise(x,.1,np.random.default_rng(42)),add_gaussian_noise(x,.1,np.random.default_rng(42)))
