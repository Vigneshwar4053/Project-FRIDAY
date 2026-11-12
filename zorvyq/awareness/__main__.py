"""Owner controls and a model-free background consumer. No collection by default."""
import argparse
import json
from threading import Event
import signal
from zorvyq.preferences import Preferences
from .store import ActivityStore
from .monitor import MonitoringManager
from .runtime import LocalRuntime, discover, session_type


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',choices=['status','pause','resume','disable'],default='status')
    parser.add_argument('--daemon',action='store_true')
    args=parser.parse_args()
    store=ActivityStore(Preferences().path.parent/'activity.sqlite3')
    if not args.daemon:
        if args.action in ('pause','resume','disable'):
            store.configure(**({'enabled':False,'metrics':False} if args.action=='disable' else {'paused':args.action=='pause'}))
        manager=MonitoringManager(store)
        if args.action=='status':
            print(json.dumps(dict(session=session_type(),executables={k:str(v) for k,v in discover().items()},
                monitoring=manager.snapshot()['state'],preferences={k:store.preferences()[k] for k in ('enabled','paused','browser','start_at_login','background')}),indent=2))
        return
    if not (store.preferences()['background'] and store.preferences()['start_at_login']):return
    runtime=LocalRuntime(store.path.parent/'activitywatch')
    manager=MonitoringManager(store,runtime=runtime)
    halt=Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:halt.set())
    # The GUI owns startup as usual. The separate service stays opt-in and exits at logout.
    try:
        while not halt.is_set() and store.preferences()['background']:
            if manager.thread is None or not manager.thread.is_alive():manager.start()
            halt.wait(3)
    finally:manager.stop()


if __name__=='__main__':main()
