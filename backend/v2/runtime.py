"""Reuse reviewed project speech/model configuration without modifying V1 or shell sourcing.

Configuration presence is not evidence of quota, current provider availability, a
V2 device identity, or a feedback platform. No credential appears in a manifest.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import platform
from importlib.metadata import version, PackageNotFoundError

from backend.v2.speech import V2Speech
from backend.v2.companion import DashScopeModel, UnifiedProviders
from backend.v2.files import read_checked

FIELDS = {'workspace': 'DASHSCOPE_WORKSPACE', 'region': 'DASHSCOPE_REGION',
          'asr': 'DASHSCOPE_ASR_MODEL', 'llm': 'DASHSCOPE_LLM_MODEL',
          'tts': 'DASHSCOPE_TTS_MODEL', 'voice': 'DASHSCOPE_TTS_VOICE'}


def settings(*, environment=None, service_env=None):
    environment = os.environ if environment is None else environment
    values = {key: environment.get(key, '') for key in FIELDS.values()}
    if service_env is not None:
        values={key:'' for key in FIELDS.values()}
        try:
            seen=set()
            # Literal allowlist only: never execute/source an EnvironmentFile.
            for line in read_checked(service_env,'service_env').splitlines():
                key, separator, value = line.partition('=')
                key = key.strip()
                if separator and key in FIELDS.values():
                    if key in seen:raise ValueError()
                    seen.add(key)
                    parsed = shlex.split(value, comments=True)
                    if len(parsed) != 1 or any(c in parsed[0] for c in ('$', '`', '\n', '\r')):
                        raise ValueError()
                    values[key] = parsed[0]
        except (OSError, UnicodeError, ValueError):
            raise ValueError('V2 service settings unavailable or invalid') from None
    result = {name: values[key] for name, key in FIELDS.items()}
    if any(not isinstance(v, str) or not v or len(v) > 256 or not v.isascii() or
           any(c.isspace() for c in v) for v in result.values()):
        raise ValueError('V2 service settings incomplete')
    return result


def providers(http, *, environment=None, service_env=None, credential_directory=None):
    environment = os.environ if environment is None else environment
    config = settings(environment=environment, service_env=service_env)
    directory = credential_directory or environment.get('CREDENTIALS_DIRECTORY')
    if not directory:
        raise ValueError('V2 provider credential directory required')
    try:
        key = read_checked(Path(directory)/'dashscope-api-key','provider_key',limit=4097).rstrip('\r\n')
        if not key or len(key) > 4096:
            raise ValueError()
        speech = V2Speech(http, key=key, **config)
    except (OSError, UnicodeError, ValueError):
        raise ValueError('V2 provider credential unavailable or invalid') from None
    return UnifiedProviders(speech, DashScopeModel(speech))


def manifest(config):
    # Deliberately excludes workspace ID, credentials, TLS private paths and child content.
    dependencies={}
    for name in ('httpx','websockets'):
        try:dependencies[name]=version(name)
        except PackageNotFoundError:dependencies[name]='not_installed'
    return dict(region=config['region'], models={k: config[k] for k in ('asr', 'llm', 'tts', 'voice')},
                model_revision='provider_alias_not_immutable_revision',
                runtime=dict(python=platform.python_version(),dependencies=dependencies),
                deployment=dict(bind='127.0.0.1',default_port=19483,tls_minimum='1.2',
                    max_tokens=1400,thinking=False,speech_rate=24000,context_bytes=65536,
                    device_token='explicit_v2_scope_required'),
                transports=['regional_https_chat', 'regional_wss_asr_tts'],
                device_credential='separately_required', feedback_provider='not_configured',
                prices='not_verified', new_cloud_samples=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--service-env')
    args = parser.parse_args()
    try:
        print(json.dumps(manifest(settings(service_env=args.service_env)), ensure_ascii=False))
    except ValueError as failure:
        parser.exit(2, str(failure) + '\n')
