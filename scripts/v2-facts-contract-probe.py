"""One existing-account synthetic FACTS compatibility call; never body logging."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.animal.cloud import disable_core_dumps
from backend.dashscope import DashScope, http_client
from backend.v2.companion import ModelError, UnifiedProviders, DashScopeModel
from backend.v2 import schemas


async def main():
    disable_core_dumps()
    row = dict(sample='R99-new-FACTS-synthetic-only', attempts=0, real_child=False,
               schema_source_sha256=hashlib.sha256(Path('backend/v2/schemas.py').read_bytes()).hexdigest(),
               facts_schema_sha256=hashlib.sha256(json.dumps(schemas.FACTS, sort_keys=True).encode()).hexdigest())
    async with http_client() as http:
        speech = DashScope.from_environment(http)
        model = DashScopeModel(speech)
        providers = UnifiedProviders(speech, model)
        text = '合成测试：我喜欢猫，也喜欢蓝色。'
        try:
            async with asyncio.timeout(10):
                facts = await providers.facts(text)
            row.update(accepted=model.last_status==200,
                       dimension_legal=all(f['dimension'] in {
                           'unspecified','animal','color','food','sport','activity',
                           'music','place','person','object','other'} for f in facts),
                       provenance_valid=all(f['value']==text[f['start']:f['end']] for f in facts),
                       nonempty=bool(facts), facts_count=len(facts))
        except Exception as failure:
            row.update(accepted=False, failure=type(failure).__name__)
        row.update(attempts=model.usage['requests'], status=model.last_status,
                   code=model.last_code, usage=model.usage, model=model.model)
    # Zero remote calls for the adversarial source guard counterpart.
    class Fabrication:
        async def complete(self, *args, **kwargs):
            return json.dumps(dict(facts=[dict(key='preference', value='根本没有的内容',dimension='animal')]))
    try:
        await UnifiedProviders(None,Fabrication()).facts('我喜欢猫')
        row['fabrication_rejected']=False
    except ModelError:
        row['fabrication_rejected']=True
    row['passed']=all(row.get(k,False) for k in (
        'accepted','dimension_legal','provenance_valid','nonempty','fabrication_rejected'))
    print(json.dumps(row,ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
