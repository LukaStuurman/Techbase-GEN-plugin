from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import networkx as nx
from ls_netontwerp_wizard.new_feeder_validation import validate_new_directions

def test():
    g=nx.Graph();g.add_edge('S','T',weight=100.,physical_length=100.,calculation_factor=1.,is_planned=True,planned_cable_id='NEW',cable_type='150AL')
    def check(demand,generation):return validate_new_directions(g,['S','T'],[0,0],['S'],['T','T'],[0,0],demand,generation,0)
    rows=check([100.,100.],[0.,0.]);assert len(rows)==1 and rows[0]['passed'] and rows[0]['load_a']==200.
    assert not check([100.,100.],[200.,100.])[0]['passed']
    g['S']['T'].update(weight=500.,physical_length=500.)
    rows=check([50.,50.],[0.,0.]);assert not rows[0]['passed'] and rows[0]['max_design_a']==90.
    g['S']['T'].update(source_asset_id='UNKNOWN',rating_available=False,is_planned=False)
    assert not check([1.,1.],[0.,0.])[0]['passed']
    print('NEW_FEEDER_VALIDATION_OK (whole-direction current, generation, actual length, unreachable unrated cable)')
if __name__=='__main__':test()
