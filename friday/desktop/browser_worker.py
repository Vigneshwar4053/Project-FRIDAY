"""Fixed GTK renderer: no folder reads, file activation, writes or public IPC."""
import json
import socket
import sys

MAX_PACKET = 65536

def diagnostic(code):
    # Fixed codes only: never report paths, contents, exception text or FDs.
    print('FRIDAY_BROWSER_DIAGNOSTIC:'+code,file=sys.stderr,flush=True)


def validate_command(value, previous_id=0):
    if type(value) is not dict or type(value.get('id')) is not int or value['id'] < 1:
        raise ValueError('Invalid request.')
    if value['id']<=previous_id: raise ValueError('Replayed request.')
    op=value.get('op')
    if op in {'ping','close'}:
        if set(value)!={'id','op'}: raise ValueError('Unexpected fields.')
    elif op=='navigate':
        if set(value)!={'id','op','location'}: raise ValueError('Unexpected fields.')
        text=value['location']
        if type(text) is not str or not text.startswith('/') or len(text)>4096 or any(not c.isprintable() for c in text):
            raise ValueError('Unsafe location display.')
    elif op=='contents':
        if set(value)!={'id','op','location','rows'}: raise ValueError('Unexpected fields.')
        if (type(value['location']) is not str or not value['location'].startswith('/') or
                len(value['location'])>4096 or any(not c.isprintable() for c in value['location'])):
            raise ValueError('Invalid location.')
        rows=value['rows']
        if type(rows) is not list or len(rows)>100 or any(type(row) is not str or len(row)>512 or any(not c.isprintable() for c in row) for row in rows):
            raise ValueError('Unsafe rows.')
    else: raise ValueError('Unsupported operation.')
    return value


def main():
    # Isolated system Python imports installed GTK only here; headless protocol
    # tests can import this module without GTK or a display.
    import gi
    gi.require_version('Gtk','4.0')
    from gi.repository import Gtk, GLib
    if not Gtk.init_check(): raise RuntimeError('No local GTK display.')
    channel=socket.socket(fileno=int(sys.argv[1]));channel.setblocking(False)
    loop=GLib.MainLoop()
    window=Gtk.Window(title='FRIDAY Browser')
    window.set_default_size(680,480)
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
    box.set_margin_top(16);box.set_margin_bottom(16);box.set_margin_start(16);box.set_margin_end(16)
    location=Gtk.Label(label='Awaiting approved location',xalign=0);location.set_selectable(True);location.set_wrap(True)
    notice=Gtk.Label(label='Contents hidden. Request list browser contents in the FRIDAY terminal.',xalign=0);notice.set_wrap(True)
    guidance=Gtk.Label(label='Navigate in FRIDAY: open downloads in friday browser · open documents in friday browser · go back · go forward',xalign=0);guidance.set_wrap(True)
    listing=Gtk.Label(label='',xalign=0,yalign=0);listing.set_selectable(True);listing.set_wrap(True)
    scroll=Gtk.ScrolledWindow();scroll.set_vexpand(True);scroll.set_child(listing)
    for widget in (location,notice,guidance,scroll): box.append(widget)
    window.set_child(box)
    current=None;last_id=0;pending=[]
    def closed(*_):
        loop.quit()
        return False
    window.connect('close-request',closed)

    def respond(command):
        # Called on the GTK main context after layout/map, never a process-only
        # inference. Visibility means mapped within GTK, not compositor focus.
        # Health is independent of compositor mapping/minimization. Only a
        # navigation acknowledgment waits for the managed widget to be mapped.
        if command['op']!='ping' and not window.get_mapped():
            return True
        if current is not None and location.get_text()!=current:
            diagnostic('label_mismatch')
            loop.quit();return False
        response={'id':command['id'],'op':command['op'],'window':'managed',
                  'location':current,'mapped':bool(window.get_mapped())}
        try: channel.send(json.dumps(response,separators=(',',':')).encode())
        except OSError: diagnostic('ipc_send_failed');loop.quit()
        return False

    def receive():
        nonlocal current,last_id
        if pending: return True
        try: packet=channel.recv(MAX_PACKET+1)
        except BlockingIOError: return True
        except OSError: diagnostic('ipc_receive_failed');loop.quit();return False
        if not packet or len(packet)>MAX_PACKET: loop.quit();return False
        try:
            command=validate_command(json.loads(packet),last_id)
            last_id=command['id']
            if command['op']=='close': loop.quit();return False
            if command['op']=='navigate':
                current=command['location'];location.set_text(current)
                listing.set_text('');notice.set_text('Contents hidden. Request list browser contents in the FRIDAY terminal.')
                window.present()
            if command['op']=='contents':
                if command['location']!=current: raise ValueError('Stale listing.')
                listing.set_text('\n'.join(command['rows']))
                notice.set_text('Authorized bounded directory listing. Files cannot be opened or modified here.')
            pending.append(command)
            def finish():
                keep=respond(command)
                if not keep: pending.clear()
                return keep
            GLib.timeout_add(20,finish)
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
            diagnostic('protocol_rejected');loop.quit();return False
        return True
    GLib.timeout_add(20,receive)
    try: loop.run()
    finally: window.destroy();channel.close()


if __name__=='__main__':
    try: main()
    except Exception:
        diagnostic('startup_or_event_loop_failed')
        sys.exit(1)
