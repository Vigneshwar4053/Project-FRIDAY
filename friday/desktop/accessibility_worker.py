"""Reviewed observation-only system-GI worker. Never sends desktop input."""
import hashlib
import json
import os
import re
import sys
from time import monotonic

MAX_PACKET = 65536
METADATA_ONLY = 'METADATA_ONLY'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def validate_command(data):
    if (type(data) is not dict or set(data) != {'operation', 'application_id', 'window', 'executables', 'mode'} or
            data['mode'] != METADATA_ONLY or
            data['operation'] not in {'list', 'observe'} or
            data['application_id'] not in {'vscode', 'firefox', 'files'} or
            type(data['executables']) is not list or not 1 <= len(data['executables']) <= 4 or
            any(type(e) is not list or len(e) != 4 or any(type(n) is not int or n < 0 for n in e)
                for e in data['executables'])):
        raise ValueError('Invalid command.')
    if data['operation'] == 'list':
        if data['window'] is not None:
            raise ValueError('Unexpected target.')
    else:
        window = data['window']
        if (type(window) is not dict or set(window) != {'application_id', 'window_id', 'identity'} or
                window['application_id'] != data['application_id'] or
                any(type(window[k]) is not str or not re.fullmatch(r'[a-f0-9]{64}', window[k])
                    for k in ('window_id', 'identity'))):
            raise ValueError('Invalid target.')
    return data


def inspect_command(command):
    expires = monotonic() + 10
    def check():
        if monotonic() >= expires:
            raise TimeoutError('Observation deadline exceeded.')

    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi, Gio, GLib
    Atspi.set_timeout(800, 3000)
    session = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(connection, name, path, interface, method, args):
        return connection.call_sync(name, path, interface, method, args, None,
                                    Gio.DBusCallFlags.NONE, 800, None).unpack()

    enabled = call(session, 'org.a11y.Bus', '/org/a11y/bus',
                   'org.freedesktop.DBus.Properties', 'Get',
                   GLib.Variant('(ss)', ('org.a11y.Status', 'IsEnabled')))[0]
    if enabled is not True:
        return {'status': 'unsupported'}
    address = call(session, 'org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Bus', 'GetAddress', None)[0]
    expected = 'unix:path=' + os.environ['XDG_RUNTIME_DIR'] + '/at-spi/bus'
    if address != expected and not re.fullmatch(re.escape(expected) + r',guid=[a-f0-9]+', address):
        return {'status': 'unsupported'}
    bus = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
                                                  Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    desktop = Atspi.get_desktop(0)
    if desktop is None or desktop.get_child_count() > 200:
        return {'status': 'unsupported'}
    candidates = []
    # No names or text from unrelated applications; attribution precedes UI data.
    for i in range(desktop.get_child_count()):
        check()
        app = desktop.get_child_at_index(i)
        bus_name = getattr(getattr(app, 'app', None), 'bus_name', None)
        if type(bus_name) is not str or not bus_name.startswith(':'):
            continue
        pid = call(bus, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                   'org.freedesktop.DBus', 'GetConnectionUnixProcessID', GLib.Variant('(s)', (bus_name,)))[0]
        if type(pid) is not int or pid <= 0 or app.get_process_id() != pid:
            continue
        try:
            metadata = os.stat('/proc/' + str(pid) + '/exe')
            fingerprint = [metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns]
            if fingerprint not in command['executables']:
                continue
            # Process incarnation, not just PID or title; no environment/content.
            with open('/proc/' + str(pid) + '/stat', encoding='utf-8') as stream:
                proc = stream.read(4097)
            if len(proc) > 4096:
                continue
            start_time = proc[proc.rfind(')') + 2:].split()[19]
        except (OSError, ValueError, IndexError):
            continue
        if app.get_child_count() > 20:
            return {'status': 'unsupported'}
        for j in range(app.get_child_count()):
            check()
            window = app.get_child_at_index(j)
            if window.get_role() not in {Atspi.Role.FRAME, Atspi.Role.WINDOW, Atspi.Role.DIALOG}:
                continue
            path = getattr(window, 'path', None)
            if type(path) is not str or not path.startswith('/'):
                continue
            reference = {'application_id': command['application_id'], 'window_id': digest(bus_name + path),
                         'identity': digest(bus_name + path + str(pid) + start_time + str(fingerprint))}
            states = window.get_state_set()
            if states.contains(Atspi.StateType.DEFUNCT) or not states.contains(Atspi.StateType.SHOWING):
                continue
            # Unknown dialogs may be authentication/security prompts.
            sensitive = window.get_role() == Atspi.Role.DIALOG
            snapshot = {'window': reference, 'revision': 'initial', 'focused': False,
                        'elements': [], 'sensitive': sensitive}
            candidates.append((window, snapshot, bus_name, states.contains(Atspi.StateType.ACTIVE)))
            if len(candidates) > 20:
                return {'status': 'unsupported'}
    if command['operation'] == 'list':
        for root, snapshot, _, active in candidates:
            # ACTIVE alone is not proof that this accessible owns input focus.
            snapshot['focused'] = active and root.get_state_set().contains(Atspi.StateType.FOCUSED)
        check()
        return {'status': 'verified', 'windows': [s for _, s, _, _ in candidates if not s['sensitive']]}
    match = [entry for entry in candidates if entry[1]['window'] == command['window']]
    if len(match) != 1:
        return {'status': 'target_changed'}
    root, snapshot, bus_name, active = match[0]
    if snapshot['sensitive']:
        return {'status': 'unsupported'}
    return observe_metadata(root, snapshot, bus_name, active, Atspi, check)


def observe_metadata(root, snapshot, bus_name, active, atspi, check):
    """Names/values/interfaces are never read. Ambiguous containers are pruned.

    Only explicit chrome containers are descended into. Generic panels/fillers,
    documents, terminal/editor/text regions and dialogs are not safe containers.
    Even permitted controls are leaves: editable widgets may contain documents.
    Roles are untrusted metadata, not proof that a window contains no secrets.
    """
    def roles(names):
        return {getattr(atspi.Role, name) for name in names if hasattr(atspi.Role, name)}
    containers = roles(('FRAME', 'WINDOW', 'TOOL_BAR', 'MENU_BAR', 'MENU', 'POPUP_MENU'))
    leaves = roles(('PUSH_BUTTON', 'TOGGLE_BUTTON', 'CHECK_BOX', 'RADIO_BUTTON',
                    'MENU_ITEM', 'CHECK_MENU_ITEM', 'RADIO_MENU_ITEM', 'ENTRY',
                    'LABEL', 'STATUS_BAR'))
    # No permissive fallback for newly introduced or generic toolkit roles.
    allowed = containers | leaves
    queue = [(root, 0)]
    visited = set()
    count = 0
    focused = False
    while queue:
        check()
        node, depth = queue.pop(0)
        path = getattr(node, 'path', None)
        if type(path) is not str or path in visited:
            continue
        visited.add(path)
        count += 1
        if count > 200:
            return {'status': 'unsupported'}
        role = node.get_role()
        if role not in allowed or (depth > 0 and role in roles(('FRAME', 'WINDOW'))):
            continue  # Exclude BEFORE state, name, value or child access.
        states = node.get_state_set()
        if states.contains(atspi.StateType.DEFUNCT) or not states.contains(atspi.StateType.SHOWING):
            continue
        focused = focused or states.contains(atspi.StateType.FOCUSED)
        # Retain the exact role enum name, not a coarse label such as 'other'.
        role_name = next(name.lower() for name in (
            'FRAME', 'WINDOW', 'TOOL_BAR', 'MENU_BAR', 'MENU', 'POPUP_MENU',
            'PUSH_BUTTON', 'TOGGLE_BUTTON', 'CHECK_BOX', 'RADIO_BUTTON',
            'MENU_ITEM', 'CHECK_MENU_ITEM', 'RADIO_MENU_ITEM', 'ENTRY', 'LABEL', 'STATUS_BAR')
            if getattr(atspi.Role, name, None) == role)
        snapshot['elements'].append({'control_id': digest(bus_name + path), 'role': role_name,
            'label': '', 'text': None, 'enabled': states.contains(atspi.StateType.ENABLED),
            'focusable': states.contains(atspi.StateType.FOCUSABLE), 'showing': True,
            'editable': False, 'sensitive': False, 'actions': [], 'effect': 'unknown'})
        if role not in containers:
            continue
        children = node.get_child_count()
        if children > 200 or count + len(queue) + children > 200 or (depth >= 8 and children):
            return {'status': 'unsupported'}
        queue.extend((node.get_child_at_index(i), depth + 1) for i in range(children))
    check()
    snapshot['focused'] = active and focused
    snapshot['revision'] = digest(json.dumps(snapshot, sort_keys=True))
    if len(json.dumps(snapshot, ensure_ascii=True).encode('utf-8')) > MAX_PACKET:
        return {'status': 'unsupported'}
    return {'status': 'verified', 'snapshot': snapshot}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_PACKET + 1)
        if len(raw) > MAX_PACKET:
            raise ValueError('Oversized request.')
        command = validate_command(json.loads(raw))
        result = inspect_command(command)
        output = json.dumps(result, ensure_ascii=True).encode('utf-8')
        if len(output) > MAX_PACKET:
            output = b'{"status":"unsupported"}'
    except TimeoutError:
        output = b'{"status":"timeout"}'
    except Exception:
        output = b'{"status":"unsupported"}'
    sys.stdout.buffer.write(output)


if __name__ == '__main__':
    main()
