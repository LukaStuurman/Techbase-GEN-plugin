"""Compare exact compact MILP against the unreduced independent solver model."""
import os,sys,time
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    import numpy as np
    from scipy.optimize import milp,Bounds,LinearConstraint
    from scipy.sparse import csr_matrix,vstack
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib import maak_clustering_engine as e
    rng=np.random.default_rng(4031)
    for repeat in range(12):
        n,m=18,6;loads=rng.integers(1,6,n).astype(float)
        allowed=rng.random((n,m))<.2
        allowed[np.arange(n),np.arange(n)%m]=True
        objective=rng.random(n*m);upper=allowed.ravel().astype(float)
        matrix=vstack([e.assignment_matrix(n,m),e.station_load_matrix(loads,m)],format='csr')
        lower=np.r_[np.ones(n),np.zeros(m)];bounds=np.r_[np.ones(n),np.full(m,30.)]
        integer=np.ones(n*m,dtype=np.uint8);options=e.milp_options(10,0.)
        original=milp(c=objective,integrality=integer,bounds=Bounds(np.zeros(n*m),upper),constraints=LinearConstraint(matrix,lower,bounds),options=options)
        compact=e.compact_assignment_milp(objective,integer,upper,matrix,lower,bounds,options)
        assert original.success and compact.success
        assert abs(original.fun-compact.fun)<1e-8
        assert compact.x.shape==(n*m,) and np.all(compact.x[upper==0]==0)
        assert np.all(matrix@compact.x<=bounds+1e-7) and np.all(matrix@compact.x>=lower-1e-7)
    # An empty existing station cannot reach its minimum utilization: no solver
    # call is permitted for those impossible levels, but zero remains valid.
    calls=[];solver=e.compact_assignment_milp
    def counted(*args,**kwargs):calls.append(1);return solver(*args,**kwargs)
    e.compact_assignment_milp=counted
    result,minimum=e.solve_fixed_assignment(np.array([[1.,np.inf],[2.,np.inf]]),np.array([3.,4.]),np.array([10.,10.]),np.array(['A','A']),['A','B'])
    assert list(result)==[0,0] and minimum==0 and len(calls)==1
    print('COMPACT_ASSIGNMENT_TEST_OK (12 independent full/reduced MILP optima equal, capacity/assignment bounds, zero-variable restoration, impossible utilization skipped)',flush=True)
    os._exit(0)


if __name__=='__main__':main()
