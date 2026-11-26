import sys,inspect,textwrap,unittest
sys.path.insert(0,'/home/ubuntu/multica_workspaces/titan-q0u7-aa9ba699e3d3/tita-86-8c4eebd1bbc1/workdir/parent-completion')
from tests.v2 import test_image_descriptions as m
source=textwrap.dedent(inspect.getsource(m.Descriptions.run_wire))
assert 'await peer.generation\n' in source
source=source.replace('        await peer.generation\n','')
source=source.replace('while peer.visual_task and not peer.visual_task.done():','while not peer.generation.done() or (peer.visual_task and not peer.visual_task.done()):')
namespace=dict(vars(m));exec(source,namespace);m.Descriptions.run_wire=namespace['run_wire']
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(m.Descriptions))
raise SystemExit(not result.wasSuccessful())
