"""Offline checked image configuration and real provider composition."""
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path

from backend.v2.dynamic_images import ImageConfig, QwenImages
from backend.v2.files import ConfigurationError, read_checked
from backend.v2.image_review import ModelImageReview, unique_object

PROMPT_POLICY = 'wali-image-prompt-v1'
IMAGE_POLICY = 'wali-image-png-v1'


@dataclass(frozen=True)
class ImageRuntime:
    config: ImageConfig
    image_key: str = field(repr=False)
    review_key: str = field(repr=False)


def read_image_runtime(path, credential_directory, expected_workspace):
    if path is None:
        return None
    try:
        value = json.loads(read_checked(path, 'image_config', limit=4096), object_pairs_hook=unique_object)
        if value == {'enabled': False} and type(value['enabled']) is bool:
            return None
        names = {'enabled', 'region', 'workspace', 'model', 'review_model', 'resource_review_id',
                 'prompt_policy', 'image_policy', 'width', 'height', 'timeout', 'result_ttl'}
        if (type(value) is not dict or set(value) != names or value['enabled'] is not True or
            value['workspace'] != expected_workspace or value['review_model'] != 'qwen3.8-flash' or
            value['prompt_policy'] != PROMPT_POLICY or value['image_policy'] != IMAGE_POLICY):
            raise ValueError()
        config = ImageConfig(**{k: v for k, v in value.items() if k != 'review_model'})
        directory = Path(credential_directory)
        image_key = read_checked(directory / 'dashscope-image-key', 'image_key', limit=4097).rstrip('\r\n')
        review_key = read_checked(directory / 'dashscope-review-key', 'image_review_key', limit=4097).rstrip('\r\n')
        reviewer = ModelImageReview(None, workspace=config.workspace, region=config.region,
            api_key=review_key, prompt_policy=config.prompt_policy, image_policy=config.image_policy,
            width=config.width, height=config.height)
        # Validate the same concrete production objects without sending any request.
        adapter = QwenImages(object(), config=config, api_key=image_key,
            prompt_reviewer=reviewer.prompt, image_reviewer=reviewer.image)
        if adapter.availability() != 'configured':
            raise ValueError()
        return ImageRuntime(config, image_key, review_key)
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError('image_configuration_invalid') from None


@asynccontextmanager
async def configured_images(http, runtime):
    if runtime is None:
        yield None
        return
    config = runtime.config
    review = ModelImageReview(http, workspace=config.workspace, region=config.region,
        api_key=runtime.review_key, prompt_policy=config.prompt_policy, image_policy=config.image_policy,
        width=config.width, height=config.height)
    images = QwenImages(http, config=config, api_key=runtime.image_key,
        prompt_reviewer=review.prompt, image_reviewer=review.image)
    try:
        yield images
    finally:
        await images.aclose()
