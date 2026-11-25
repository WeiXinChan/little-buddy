"""Approved local artwork tool. No remote URL, generation, or private conversation export."""
import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class DefaultImage:
    asset_id: str
    name: str
    sha256: str
    width: int
    height: int
    fallback_reason: str | None = None

    def __post_init__(self):
        if (not re.fullmatch('[a-z0-9-]{1,64}',self.asset_id) or
            not re.fullmatch('[a-f0-9]{64}',self.sha256) or self.width!=512 or self.height!=512 or
            self.fallback_reason not in {None,'dynamic_unavailable','unknown_asset','asset_invalid'}):
            raise ValueError('default image receipt')

    def payload(self):
        return dict(asset_id=self.asset_id, sha256=self.sha256, width=self.width, height=self.height,
                    source='default', fallback_reason=self.fallback_reason)


class DefaultImages:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[2] / 'assets/v2-default'
        self.entries = {}
        try:
            raw = json.loads((self.root/'manifest.json').read_text())
            if not isinstance(raw,list) or len(raw)>1000:
                return
            for entry in raw:
                name=entry.get('id')
                if (isinstance(name,str) and re.fullmatch('[a-z0-9-]{1,64}',name) and
                    entry.get('png') == 'png/'+name+'.png' and entry.get('width')==512 and entry.get('height')==512 and
                    re.fullmatch('[a-f0-9]{64}',entry.get('png_sha256','')) and isinstance(entry.get('name'),str)):
                    self.entries[name]=entry
        except (OSError,ValueError,TypeError):
            self.entries.clear()

    def catalogue(self):
        return [dict(id=k,name=v['name']) for k,v in self.entries.items()]

    def _read(self, asset_id, reason):
        entry=self.entries.get(asset_id)
        if entry is None: return None
        path=self.root/entry['png']
        try:
            if path.is_symlink() or path.stat().st_size>1024*1024: return None
            content=path.read_bytes()
            if not content.startswith(b'\x89PNG\r\n\x1a\n') or sha256(content).hexdigest()!=entry['png_sha256']: return None
            return DefaultImage(asset_id,entry['name'],entry['png_sha256'],512,512,reason)
        except OSError:
            return None

    def candidate(self, request):
        asset_id=request.get('asset_id','garden')
        reason='dynamic_unavailable' if request['kind']=='generate_image' else None
        if asset_id not in self.entries: asset_id='garden';reason=reason or 'unknown_asset'
        entry=self.entries.get(asset_id)
        if entry is None:return None
        return DefaultImage(asset_id,entry['name'],entry['png_sha256'],512,512,reason)

    def accepts(self, image):
        if not isinstance(image,DefaultImage):return False
        entry=self.entries.get(image.asset_id)
        return entry is not None and entry['name']==image.name and entry['png_sha256']==image.sha256

    async def prepare(self, request):
        candidate=self.candidate(request)
        if candidate is None:return None
        result=await asyncio.to_thread(self._read,candidate.asset_id,candidate.fallback_reason)
        if result is not None:return result
        return await asyncio.to_thread(self._read,'garden',candidate.fallback_reason or 'asset_invalid')


def revealable(plan, context, image):
    """The visual can disclose a riddle only after this exact final spoken answer is ACKed."""
    if plan['action']=='private' or context.get('private'):
        return False,False
    protected=context.get('unrevealed') or plan.get('secrets')
    if protected:
        answer=protected.get('answer') if set(protected)=={'answer'} else None
        spoken=plan['sentences'][-1]
        explicit=(isinstance(answer,str) and answer in {image.name,image.asset_id} and
                  any(prefix+answer in spoken for prefix in ('答案是','谜底是')))
        return bool(explicit),bool(explicit)
    return True,False
