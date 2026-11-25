"""Local OS-authorized maintenance only. No device-accessible admin route."""
import argparse
import base64
import json
from getpass import getpass

from backend.v2.feedback_store import FeedbackStore, FeedbackError


def cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('operation', choices=['list', 'show', 'processing', 'reply', 'sweep'])
    parser.add_argument('--device')
    parser.add_argument('--id')
    args = parser.parse_args(argv)
    store = None
    try:
        store = FeedbackStore(args.database)
        if args.operation == 'list':
            result = store.pending() # routing/status metadata only
        elif args.operation == 'show':
            result = store.read(args.device, args.id)
            result['logs'] = base64.b64encode(result['logs']).decode()
        elif args.operation == 'processing':
            store.maintain(args.device, args.id); result = {'updated': True}
        elif args.operation == 'reply':
            # No material staging file or shell-history argument is created.
            reply = getpass('Reply (not echoed): ')
            store.maintain(args.device, args.id, reply=reply); result = {'updated': True}
        else:
            store.sweep(); result = {'swept': True}
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (FeedbackError, TypeError, ValueError, EOFError):
        print('{"feedback_admin":"failed_closed"}'); return 2
    finally:
        if store is not None:store.close()


if __name__ == '__main__':
    raise SystemExit(cli())
