"""Optional, USB-path-bound input relay for identical-name touch controllers.

Copies input events without coordinate transformation. Exclusive grabs prevent
duplicate input; closing the process releases the originals. Requires evdev.
"""
import json
from pathlib import Path
import selectors
import signal
import sys
import time

from evdev import InputDevice, UInput, ecodes


def main():
    config = json.loads(Path('/etc/pi-setting/touch-map.json').read_text())
    if config.get('version') != 1:
        raise ValueError('Unsupported touch map configuration')
    selector = selectors.DefaultSelector()
    devices = {}
    running = True

    def stop(*_):
        nonlocal running
        running = False

    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, stop)

    def close(port):
        source, virtual = devices.pop(port)
        selector.unregister(source)
        virtual.close()
        try:
            source.ungrab()
        except OSError:
            pass
        source.close()

    def attach(port, entry):
        link = Path('/dev/input/by-path')/entry['by_path']
        if not link.exists():
            return
        source = InputDevice(str(link))
        virtual = None
        try:
            if (source.info.vendor, source.info.product) != (entry['vendor'], entry['product']):
                raise ValueError(f'USB device identity changed at {link}')
            if ecodes.INPUT_PROP_DIRECT not in source.input_props():
                raise ValueError(f'{link} is not a direct touch input')
            virtual = UInput.from_device(source, name=f'PiSetting Touch HDMI{port}',
                                        phys=f'pi-setting/HDMI-A-{port+1}',
                                        vendor=0xfeed, product=0x7200+port,
                                        input_props=source.input_props())
            source.grab()
            devices[port] = (source, virtual)
            selector.register(source, selectors.EVENT_READ, port)
            print(f'HDMI{port}: relaying {link.name} as {virtual.name}', flush=True)
        except Exception:
            if virtual:
                virtual.close()
            source.close()
            raise

    last_attach = 0
    try:
        while running:
            if time.monotonic() - last_attach > 1:
                for key, entry in config['ports'].items():
                    port = int(key)
                    if port in devices:
                        continue
                    try:
                        attach(port, entry)
                    except (OSError, ValueError) as error:
                        print(f'HDMI{port}: {error}', file=sys.stderr, flush=True)
                last_attach = time.monotonic()
            for key, _ in selector.select(timeout=.2):
                port = key.data
                source, virtual = devices[port]
                try:
                    for event in source.read():
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                            raise OSError('Input overrun; recreating virtual device to release touch slots')
                        virtual.write_event(event)
                except BlockingIOError:
                    pass
                except OSError as error:
                    print(f'HDMI{port}: input disconnected/reset: {error}', flush=True)
                    close(port)
    finally:
        for port in list(devices):
            close(port)
        selector.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
