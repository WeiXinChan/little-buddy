"""Explicit isolated V2 listener. No V1 defaults, deployment, credential writes."""
import argparse
import asyncio
from pathlib import Path
import ssl
from backend.dashscope import http_client
from backend.v2.companion import CompanionPolicy
from backend.v2.runtime import providers as configured_providers
from backend.v2.server import voice_server


async def main(args):
    from backend.animal.cloud import disable_core_dumps
    disable_core_dumps()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert, args.key)
    token = Path(args.token_file).read_text().strip()
    async with http_client() as http:
        providers = configured_providers(http, service_env=getattr(args, 'service_env', None),
                                         credential_directory=getattr(args, 'credential_directory', None))
        async with voice_server('127.0.0.1', args.port, tls, token, providers, CompanionPolicy()):
            await asyncio.Event().wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--port', type=int, default=19483)
    parser.add_argument('--service-env', help='Read only reviewed model fields; never shell-source the file')
    parser.add_argument('--credential-directory', help='Existing systemd credential directory; no copying or generation')
    asyncio.run(main(parser.parse_args()))
