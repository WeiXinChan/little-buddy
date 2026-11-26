"""Offline release/configuration validation. No network or ownership issuance."""
from contextlib import ExitStack
from dataclasses import dataclass, field
from hashlib import sha256
from importlib.metadata import version,PackageNotFoundError
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

from backend.v2.files import ConfigurationError,checked_file,read_checked,disable_core_dumps
from backend.v2.protocol import CONTRACT
from backend.v2.models import TEXT_MODEL, TEXT_MODELS, UnsupportedTextModel

MODELS=dict(asr='fun-asr-realtime',llm=TEXT_MODEL,tts='cosyvoice-v3-flash',voice='longanyang')
LOCK=Path(__file__).resolve().parents[1]/'requirements-v2.lock'


def unique_object(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate configuration field')
        result[key]=value
    return result


@dataclass
class Prepared:
    tls:ssl.SSLContext=field(repr=False)
    token:str=field(repr=False)
    provider_key:str=field(repr=False)
    config:dict=field(repr=False)
    expires_at:int
    report:dict
    images:object=field(default=None,repr=False)
    feedback:object=field(default=None,repr=False)


def dependencies():
    if sys.version_info<(3,11):raise ConfigurationError('python_version_mismatch')
    try:
        for line in LOCK.read_text().splitlines():
            if not line or line.startswith('#'):continue
            name,expected=line.split('==')
            if version(name)!=expected:raise ValueError()
    except (OSError,ValueError,PackageNotFoundError):
        raise ConfigurationError('dependency_version_mismatch') from None


def prepare(args,*,now=time.time):
    disable_core_dumps()
    if type(args.port) is not int or not 1024<=args.port<=65535:
        raise ConfigurationError('loopback_port_invalid')
    if args.apk_contract!=CONTRACT:raise ConfigurationError('apk_contract_mismatch')
    dependencies()
    from backend.v2.runtime import settings,manifest
    try:config=settings(environment={},service_env=args.service_env)
    except UnsupportedTextModel:raise ConfigurationError('provider_model_contract_mismatch') from None
    except ValueError:raise ConfigurationError('service_env_invalid') from None
    if config['llm'] not in TEXT_MODELS or any(config[k]!=v for k,v in MODELS.items() if k!='llm'):raise ConfigurationError('provider_model_contract_mismatch')
    if config['region']!='cn-beijing':raise ConfigurationError('provider_region_contract_mismatch')
    directory=Path(args.credential_directory)
    provider_key=read_checked(directory/'dashscope-api-key','provider_key',limit=4097).rstrip('\r\n')
    token=read_checked(args.token_file,'device_token',limit=257).rstrip('\r\n')
    if not re.fullmatch('[A-Za-z0-9]{32,256}',token):raise ConfigurationError('device_token_invalid')
    if not provider_key or not provider_key.isascii() or any(c.isspace() for c in provider_key):
        raise ConfigurationError('provider_key_invalid')
    try:
        from backend.dashscope import DashScope
        DashScope(None,key=provider_key,**config)
    except ValueError:raise ConfigurationError('provider_configuration_invalid') from None
    try:
        scope=json.loads(read_checked(args.device_scope,'device_scope',limit=4096),object_pairs_hook=unique_object)
        if (not isinstance(scope,dict) or set(scope)!={'v','purpose','endpoint','token_sha256','not_after','protocol_contract'} or
            type(scope['v']) is not int or scope['v']!=1 or scope['purpose']!='little-buddy-v2-device' or
            scope['protocol_contract']!=CONTRACT or scope['token_sha256']!=sha256(token.encode()).hexdigest() or
            type(scope['not_after']) is not int or scope['not_after']<=now() or not isinstance(scope['endpoint'],str)):raise ValueError()
        endpoint=urlsplit(scope['endpoint'])
        if (endpoint.scheme!='wss' or not endpoint.hostname or endpoint.username or endpoint.password or
            endpoint.path!='/v2/voice' or endpoint.query or endpoint.fragment or
            not endpoint.netloc.isascii() or not re.fullmatch('[A-Za-z0-9.:-]+',endpoint.netloc) or endpoint.port==0):raise ValueError()
    except (ValueError,TypeError,KeyError):raise ConfigurationError('v2_device_scope_invalid') from None
    name=args.tls_name
    if not isinstance(name,str) or not re.fullmatch('[A-Za-z0-9.-]{1,253}',name):
        raise ConfigurationError('tls_name_invalid')
    try:
        with ExitStack() as stack:
            cert=stack.enter_context(checked_file(args.cert,'tls_certificate',secret=False))
            key=stack.enter_context(checked_file(args.key,'tls_private_key',limit=16384))
            ca=stack.enter_context(checked_file(args.ca_file,'trust_anchor',secret=False,limit=1024*1024))
            identity=lambda fd:(os.fstat(fd).st_size,os.fstat(fd).st_mtime_ns,os.fstat(fd).st_ctime_ns)
            before=[identity(fd) for fd in (cert,key,ca)]
            fdpath=lambda fd:'/proc/self/fd/'+str(fd)
            try:ipaddress.ip_address(name);verify='-verify_ip'
            except ValueError:verify='-verify_hostname'
            result=subprocess.run(['openssl','verify','-purpose','sslserver','-CAfile',fdpath(ca),
                '-untrusted',fdpath(cert),verify,name,fdpath(cert)],pass_fds=(cert,ca),
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,check=False)
            if result.returncode:raise ValueError()
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2
            # Hold validated descriptors through OpenSSL loading, avoiding path reopen races.
            tls.load_cert_chain(fdpath(cert),fdpath(key),password=lambda:'')
            if before!=[identity(fd) for fd in (cert,key,ca)]:raise ValueError()
    except ConfigurationError:raise
    except (OSError,ValueError,ssl.SSLError,subprocess.SubprocessError):
        raise ConfigurationError('tls_chain_name_or_key_invalid') from None
    report=manifest(config)
    from backend.v2.image_runtime import read_image_runtime
    images=read_image_runtime(getattr(args,'image_config',None),directory,config['workspace'])
    from backend.v2.feedback_receiver import checked_runtime
    feedback=checked_runtime(getattr(args,'feedback_database',None),getattr(args,'feedback_copies_policy',None))
    report.update(protocol_contract=CONTRACT,checks='offline_pass',
                  device_scope='operator_bound_v2_only_not_family_ownership_proof',
                  ingress_tls='not_probed',new_cloud_samples=0,
                  dynamic_images='configured_not_cloud_verified' if images is not None else 'disabled')
    if feedback is not None:report['feedback_provider']='self_hosted_configured_not_accepted'
    return Prepared(tls,token,provider_key,config,scope['not_after'],report,images,feedback)
