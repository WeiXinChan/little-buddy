"""Explicit V2 operator selections; candidates are never an automatic fallback chain."""
TEXT_MODEL = 'deepseek-v4.1-flash-1017'
TEXT_MODELS = frozenset({TEXT_MODEL, 'deepseek-v4.1-flash', 'qwen4-max'})
IMAGE_REVIEW_MODEL = 'qwen4-max'
SCHEMA_MODELS = frozenset({'qwen4-max'})


class UnsupportedTextModel(ValueError):
    def __init__(self):super().__init__("V2 text model not allowed")


def model_policy():
    return dict(default_text=TEXT_MODEL, allowed_text=sorted(TEXT_MODELS),
                image_review=IMAGE_REVIEW_MODEL, thinking=False, automatic_fallback=False,
                response_formats={model:('json_schema' if model in SCHEMA_MODELS else 'json_object')
                                  for model in sorted(TEXT_MODELS)},
                validation='strict_local_for_all_models', account_quota='not_proven_by_configuration')
