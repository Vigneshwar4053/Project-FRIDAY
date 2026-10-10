"""Explicit managed project metadata in the existing MemoryManager database."""
from datetime import datetime,timedelta,timezone
import time


def yesterday_window(now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('An aware clock is required.')
    today=now.astimezone().date()
    def boundary(day):
        # mktime resolves the local timezone/DST for EACH midnight, rather than
        # carrying today's fixed UTC offset across calendar-day boundaries.
        stamp=time.mktime((day.year,day.month,day.day,0,0,0,0,0,-1))
        return datetime.fromtimestamp(stamp,timezone.utc).isoformat(timespec='microseconds')
    return boundary(today-timedelta(days=1)),boundary(today)


class DesktopSessionStore:
    def __init__(self,memory): self.memory=memory
    def record(self,project_id,path,identity,application_id,status):
        if self.memory is None: return False
        self.memory.record_project_interaction(project_id,str(path),identity,application_id,status)
        return True
    def yesterday(self,projects, *, now=None):
        if self.memory is None: return ()
        start,end=yesterday_window(now)
        rows=self.memory.project_interactions_between(start,end)
        selected={}
        for row in rows:
            # Stored metadata is not authority: validate against current trusted
            # registry again, and preserve original inode for later preflight.
            if (row['schema_version']!=1 or row['source']!='friday_managed' or
                    row['status']!='launch_accepted' or row['application_id']!='vscode' or
                    row['project_id'] not in projects or
                    row['trusted_project_path']!=str(projects[row['project_id']])):
                continue
            selected[row['project_id']]=(row['project_id'],(row['device'],row['inode']))
        return tuple(selected.values())
