"""Fixed local-help protocol. No model text, user input, or provider messages cross it."""
PROMPT_ID = 'safety_support_v1'
REASONS = frozenset({'review_unavailable', 'content_blocked'})


class SafetyFault(Exception):
    code = 'safety'

    def __init__(self, reason):
        if reason not in REASONS:
            raise ValueError('help reason')
        self.reason = reason
        super().__init__('safety')


def local_help(reason):
    if reason not in REASONS:
        raise ValueError('help reason')
    return dict(v=1, prompt_id=PROMPT_ID, reason=reason)
