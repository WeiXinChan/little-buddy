"""Two independent gates from one model review. No child text in errors."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ReviewDecision:
    safety_allowed: bool
    quality_allowed: bool
    def __post_init__(self):
        if type(self.safety_allowed) is not bool or type(self.quality_allowed) is not bool:
            raise ValueError('invalid review decision')

class QualityFault(Exception):
    def __init__(self,phase='unknown'):
        super().__init__('quality_rejected')
        if phase in ('whole','segment'):self.contract_detail='quality_'+phase
