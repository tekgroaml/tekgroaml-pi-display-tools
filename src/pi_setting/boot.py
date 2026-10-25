"""Apply saved, identity-bound EDID profiles before starting the desktop."""
import sys
import time
from . import edid, store
from .config_cli import change_override


def main():
    entries = store.load()['ports']
    profiles = {p: item for p, item in entries.items() if item.get('profile') == edid.PROFILE}
    failed = False
    for key, item in profiles.items():
        port = int(key)
        # Wait for KMS enumeration, not for a disconnected monitor to appear indefinitely.
        for attempt in range(15):
            try:
                path = edid.connector(port)
                break
            except Exception:
                if attempt == 14:
                    path = None
                else:
                    time.sleep(1)
        if path is None or (path/'status').read_text().strip() != 'connected':
            print(f'HDMI{port}: disconnected; no override applied.')
            continue
        try:
            raw = edid.raw_edid(port)
            if not store.matches(item, edid.identity(raw)):
                print(f'HDMI{port}: display identity changed; profile skipped.')
                continue
            with store.locked():
                change_override(port, edid.corrected(raw), desktop=False)
            print(f'HDMI{port}: saved compatibility profile applied.')
        except Exception as error:
            failed = True
            print(f'HDMI{port}: {error}', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
