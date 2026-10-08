"""Narrow read-only Linux APIs; explicit registration, no command execution."""
import math
import os
import re
import stat
import sys

from friday.tools.base import Tool
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.models import ArgumentSpec, ArgumentType, RiskLevel, ToolSpec

_PROC_LIMIT = 65536
_PROCESS_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,14}\Z', re.ASCII)


def _read_proc(path):
    """Internal fixed-source reader, never called with request paths."""
    with open(path, 'rb') as source:
        data = source.read(_PROC_LIMIT + 1)
    if len(data) > _PROC_LIMIT:
        raise ValueError('Pseudo-file exceeds the limit.')
    return data.decode('ascii', errors='strict')


def _memory_values(text):
    wanted = {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition(':')
        if key not in wanted:
            continue
        fields = value.split()
        if (not separator or key in values or len(fields) != 2 or
                not fields[0].isascii() or not fields[0].isdigit() or fields[1] != 'kB'):
            raise ValueError('Invalid memory data.')
        values[key] = int(fields[0]) * 1024
    if 'MemTotal' not in values or values['MemTotal'] <= 0:
        raise ValueError('Missing memory total.')
    total = values['MemTotal']
    available = values.get('MemAvailable')
    swap_total, swap_free = values.get('SwapTotal'), values.get('SwapFree')
    if available is not None and available > total:
        raise ValueError('Invalid available memory.')
    if swap_total is None or swap_free is None:
        swap_total = swap_free = None
    elif swap_free > swap_total:
        raise ValueError('Invalid swap data.')
    return {'total': total, 'available': available,
            'used': total - available if available is not None else None,
            'swap_total': swap_total, 'swap_free': swap_free,
            'swap_used': swap_total - swap_free if swap_total is not None else None,
            'unit': 'bytes'}


def _cpu_model():
    # Only the beginning is needed for a model label, regardless of CPU count.
    with open('/proc/cpuinfo', 'rb') as source:
        text = source.read(_PROC_LIMIT).decode('utf-8', errors='replace')
    for line in text.splitlines():
        key, separator, value = line.partition(':')
        if separator and key.strip() in {'model name', 'Hardware', 'Processor'}:
            value = value.strip()
            if value and all(character.isprintable() for character in value):
                return value[:256]
    return None


class _SystemTool(Tool):
    def __init__(self, name, description, arguments=None):
        super().__init__(ToolSpec(name, description, arguments or {}, RiskLevel.READ_ONLY))


class SystemInfoTool(_SystemTool):
    def __init__(self):
        super().__init__('system_info', 'Basic operating system and Python runtime information.')

    def execute(self, arguments):
        info = os.uname()
        return {'operating_system': info.sysname, 'kernel': info.release,
                'architecture': info.machine, 'hostname': info.nodename,
                'python_version': '.'.join(map(str, sys.version_info[:3])),
                'python_implementation': sys.implementation.name}


class MemoryInfoTool(_SystemTool):
    def __init__(self):
        super().__init__('memory_info', 'Memory and swap counters in bytes.')

    def execute(self, arguments):
        return _memory_values(_read_proc('/proc/meminfo'))


class CpuInfoTool(_SystemTool):
    def __init__(self):
        super().__init__('cpu_info', 'Logical CPUs, architecture, bounded model label and load averages.')

    def execute(self, arguments):
        try:
            model = _cpu_model()
        except (OSError, UnicodeError):
            model = None
        try:
            load = os.getloadavg()
            if len(load) != 3 or any(not math.isfinite(value) or value < 0 for value in load):
                load = None
        except OSError:
            load = None
        return {'logical_count': os.cpu_count(), 'architecture': os.uname().machine,
                'model_name': model, 'load_average': load}


class DiskUsageTool(_SystemTool):
    def __init__(self, filesystem_policy):
        if not isinstance(filesystem_policy, FileSystemPolicy):
            raise ValueError('An explicit filesystem policy is required.')
        super().__init__('disk_usage', 'Filesystem capacity for a path inside allowed roots.',
                         {'path': ArgumentSpec(ArgumentType.STRING)})
        self.filesystem_policy = filesystem_policy

    def execute(self, arguments):
        with self.filesystem_policy.open(arguments['path'], os.O_RDONLY) as (fd, path):
            mode = os.fstat(fd).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError('A file or directory is required.')
            usage = os.fstatvfs(fd)
        return {'path': path, 'total': usage.f_blocks * usage.f_frsize,
                'used': (usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                'free': usage.f_bavail * usage.f_frsize, 'unit': 'bytes'}


def _process_counts(name):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root = os.open('/proc', flags)
    count, incomplete = 0, False
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.name.isascii() or not entry.name.isdigit():
                    continue
                try:
                    process = os.open(entry.name, flags, dir_fd=root)
                    try:
                        comm = os.open('comm', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                       dir_fd=process)
                        try:
                            data = os.read(comm, 64)
                        finally:
                            os.close(comm)
                    finally:
                        os.close(process)
                    if data == (name + '\n').encode('ascii'):
                        count += 1
                except OSError:
                    incomplete = True
    finally:
        os.close(root)
    return count, incomplete


class ProcessStatusTool(_SystemTool):
    def __init__(self):
        super().__init__('process_status', 'Exact short process-name status from visible Linux processes.',
                         {'name': ArgumentSpec(ArgumentType.STRING)})

    def execute(self, arguments):
        name = arguments['name']
        if not _PROCESS_NAME.fullmatch(name):
            raise ValueError('Invalid process name.')
        count, incomplete = _process_counts(name)
        return {'name': name, 'running': count > 0, 'count': count,
                'incomplete': incomplete, 'scope': 'visible_processes'}


def register_system_tools(registry, filesystem_policy):
    """Explicit composition only; does not enable tools in chat."""
    tools = (SystemInfoTool(), MemoryInfoTool(), CpuInfoTool(),
             DiskUsageTool(filesystem_policy), ProcessStatusTool())
    for tool in tools:
        registry.register(tool)
