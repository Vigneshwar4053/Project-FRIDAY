"""Bounded graphical smoke check. Opens a window; no inference, audio or private reads."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from zorvyq.desktop.app import build_window

app=QApplication(['zorvyq-smoke', '-platformtheme', 'generic', '-style', 'Fusion'])
app.setApplicationName('ZORVYQ')
app.setDesktopFileName('com.zorvyq.ZORVYQ')
window=build_window()
window.show()
checks={}
attempts=0

def finish():
    global attempts
    attempts+=1
    if window.busy and attempts<20:
        QTimer.singleShot(500,finish)
        return
    checks['window_visible']=window.isVisible()
    checks['all_pages']=len(window.pages)==12
    checks['no_startup_inference']=(window.controller.manager is not None and window.controller.manager.invocation_count==0)
    checks['startup_completed']=not window.busy
    checks['title']=window.windowTitle()=='ZORVYQ — Local AI Assistant'
    window.showMaximized()
    QTimer.singleShot(300,check_maximized)

def check_maximized():
    checks['maximizing']=window.isMaximized()
    window.showNormal()
    QTimer.singleShot(300,request_resize)

def request_resize():
    window.resize(760,580)
    QTimer.singleShot(300,check_resized)

def check_resized():
    checks['resizable']=window.width()==760 and window.height()==580
    if not checks['resizable']:
        print('Observed window size:',window.width(),window.height())
    window.resize(1180,820)
    window.navigate('Dashboard')
    QTimer.singleShot(300,save_and_close)

def save_and_close():
    screenshot=ROOT/'data/migration/phase2b/dashboard.png'
    screenshot.parent.mkdir(parents=True,exist_ok=True)
    window.grab().save(str(screenshot))
    for name,result in checks.items():
        print(('PASS ' if result else 'FAIL ')+name)
    print('Ollama:',window.top_status.text())
    window.close()
    await_shutdown()

def await_shutdown():
    if window.busy or not window.shutdown_complete:
        QTimer.singleShot(100,await_shutdown)
    else:
        app.exit(0 if all(checks.values()) else 1)

QTimer.singleShot(1500,finish)
raise SystemExit(app.exec())
