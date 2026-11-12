"""Async local history, dashboard cards, and explicit privacy decisions."""
from datetime import datetime, timedelta
from pathlib import Path
from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QComboBox,QListWidget,QMessageBox,QInputDialog,QFileDialog,QSpinBox,QCheckBox)
from zorvyq.awareness.store import EMPTY


def text(value):
    label=QLabel(str(value));label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);return label

def action(layout,title,callback):
    b=QPushButton(title);b.clicked.connect(callback);layout.addWidget(b);return b

class Query(QThread):
    ready=Signal(object)
    def __init__(self, owner, filters):
        super().__init__(owner);self.owner=owner;self.filters=filters
    def run(self):
        try:
            self.ready.emit(dict(activities=self.owner.store.last_three(),
                tasks=self.owner.window.tasks.recent_completed(),history=self.owner.store.search(**self.filters)))
        except (ValueError,OSError, __import__('sqlite3').Error):
            self.ready.emit(dict(error='Local activity query unavailable.'))

class ServiceChange(QThread):
    ready=Signal(bool)
    def __init__(self,owner,enable):super().__init__(owner);self.enable=enable
    def run(self):
        from zorvyq.awareness.background import BackgroundService
        try:BackgroundService().apply(self.enable,approved=True)
        except (OSError,ValueError,__import__('subprocess').TimeoutExpired):self.ready.emit(False)
        else:self.ready.emit(True)

class AwarenessPanel(QWidget):
    def __init__(self,window,store,manager):
        super().__init__();self.window=window;self.store=store;self.manager=manager
        self.worker=None;self.pending=False;self.rows=[];self.revision=-1;self.closing=False
        self.service_worker=None
        self.dashboard=QWidget();dash=QVBoxLayout(self.dashboard)
        self.dashboard_state=text(manager.status);dash.addWidget(self.dashboard_state)
        dash.addWidget(text('CURRENT ACTIVITY'))
        self.current=text('Current application unavailable.');dash.addWidget(self.current)
        self.website=text('Browser monitoring OFF');dash.addWidget(self.website)
        self.metrics=text('Stored system metrics OFF');dash.addWidget(self.metrics)
        action(dash,'Pause monitoring',self.pause)
        dash.addWidget(text('YOUR LAST 3 ACTIVITIES'));self.recent=QVBoxLayout();dash.addLayout(self.recent)
        dash.addWidget(text('RECENTLY COMPLETED TASKS'));self.completed=QVBoxLayout();dash.addLayout(self.completed)
        self.controls=QWidget();settings=QVBoxLayout(self.controls)
        settings.addWidget(text('Activity & Privacy'))
        self.state=text('Monitoring OFF · Browser monitoring OFF');settings.addWidget(self.state)
        action(settings,'Pause monitoring immediately',self.pause)
        self.switches={}
        for key,title in [('enabled','Enable activity monitoring'),('browser','Enable Firefox monitoring'),
                          ('titles','Collect safe window/page titles'),('urls','Retain sanitized full URLs'),('metrics','Enable system metrics'),
                          ('managed_runtime','Manage local ActivityWatch server and GNOME watcher'),
                          ('start_at_login','Start Monitoring at Login'),
                          ('background','Independent background monitoring'),
                          ('processes','Record bounded own-process metadata'),('network','Record connection counts')]:
            box=QCheckBox(title);box.setChecked(store.preferences()[key]);settings.addWidget(box)
            box.toggled.connect(lambda value,k=key:self.change(k,value));self.switches[key]=box
        action(settings,'Resume monitoring',self.resume)
        action(settings,'Start monitoring now',self.start_now)
        action(settings,'Stop monitoring',self.stop_now)
        action(settings,'Set website category',self.website_category)
        settings.addWidget(text('Retention days (7 / 30 / 90 or custom)'))
        self.retention=QSpinBox();self.retention.setRange(1,3650);self.retention.setValue(store.preferences()['retention']);settings.addWidget(self.retention)
        action(settings,'Save retention',lambda:self.configure(retention=self.retention.value()))
        self.metric_days=QSpinBox();self.metric_days.setRange(1,3650);self.metric_days.setValue(store.preferences()['metrics_retention']);settings.addWidget(text('System metric retention days'));settings.addWidget(self.metric_days)
        action(settings,'Save metric retention',lambda:self.configure(metrics_retention=self.metric_days.value()))
        for key,title in [('applications','Approved application identifiers'),('domains','Approved browser domains'),('exclusions','Excluded applications / domains / sensitive terms')]:
            action(settings,title,lambda checked=False,k=key,t=title:self.edit_list(k,t))
        settings.addWidget(text('Collection runs while ZORVYQ is open unless independent background monitoring is approved. '
            'Managed GNOME collection needs the Focused Window D-Bus extension, enabled by you. '
            'Managed titles are stripped before ActivityWatch storage. Pausing stops owned watchers and ZORVYQ ingestion. '
            'ActivityWatch and Firefox own their upstream recording: stop their watchers separately. '
            'Configure upstream title/URL filtering before starting watchers. No watcher is installed or launched here.'))
        action(settings,'Clear stored activity history',self.clear)
        action(settings,'Export selected history',self.export)
        action(settings,'Open Activity History',lambda:window.navigate('Activity History'))
        layout=QVBoxLayout(self);layout.addWidget(text('Activity History'))
        self.status=text('');layout.addWidget(self.status)
        self.search=QLineEdit();self.search.setPlaceholderText('Search local activity');layout.addWidget(self.search)
        self.app=QLineEdit();self.app.setPlaceholderText('Application identifier (optional)');layout.addWidget(self.app)
        self.category=QComboBox()
        from zorvyq.awareness.privacy import WEBSITE_CATEGORIES
        with store.db() as db:custom=[r[0] for r in db.execute('SELECT DISTINCT category FROM website_categories LIMIT 100')]
        self.category.addItems(['']+sorted(set(['Programming','Browsing','Terminal','Files','Studying','Other',*WEBSITE_CATEGORIES.values(),*custom])));layout.addWidget(self.category)
        self.start=QLineEdit();self.start.setPlaceholderText('From date YYYY-MM-DD (local time)');layout.addWidget(self.start)
        self.end=QLineEdit();self.end.setPlaceholderText('Through date YYYY-MM-DD (local time)');layout.addWidget(self.end)
        action(layout,'Search / Refresh history',self.refresh)
        self.list=QListWidget();self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection);layout.addWidget(self.list)
        self.list.itemDoubleClicked.connect(lambda item:self.details(self.rows[self.list.row(item)]))
        action(layout,'View selected activity details',self.selected_details)
        action(layout,'Associate selected activity with approved project',self.associate)
        action(layout,'Delete selected records',self.delete_selected)
        action(layout,'Export selected history',self.export)
        action(layout,'Clear stored history',self.clear)
        action(layout,'Summarize today with selected local model…',self.summarize)
        self.summary=text('Optional summaries require separate approval.');layout.addWidget(self.summary)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.check);self.timer.start()
        self.refresh()

    def check(self):
        live=self.manager.snapshot()
        label={'WATCHER UNAVAILABLE':'Watcher unavailable','SERVICE UNAVAILABLE':'Service unavailable'}.get(live['state'],live['state'])
        self.state.setText(label);self.dashboard_state.setText(label)
        app=live['application']
        self.current.setText((f"{app['name']} · since {app['start']} · {app['elapsed']:.0f}s observed · Active")
            if app else 'Idle' if live['idle'] else 'Current application unavailable.')
        site=live['website']
        self.website.setText((f"Website: {site['domain']} · {site['category']} · {site['elapsed']:.0f}s observed"+
            (' · '+site['title'] if site['title'] else '')+(' · '+site['url'] if site['url'] else '')) if site else live['browser'])
        m=live['metrics']
        self.metrics.setText((f"CPU: {m.get('system_cpu_used_percent','Unavailable')} · RAM: {m.get('system_memory_used_percent','Unavailable')}% · "
            f"Disk: {m.get('root_used_percent','Unavailable')}% · Uptime: {m.get('uptime_seconds','Unavailable')}s · Battery: {m.get('batteries',[])} · Sample: {m.get('at','')}") if m else 'Stored system metrics OFF / awaiting sample')
        revision=(live['scope'],live['revision'])
        if self.revision!=revision:
            self.revision=revision;self.refresh()

    def filters(self):
        start=datetime.fromisoformat(self.start.text()).astimezone() if self.start.text() else None
        end=(datetime.fromisoformat(self.end.text())+timedelta(days=1)).astimezone() if self.end.text() else None
        if start and end and end<=start:raise ValueError('Invalid date range')
        return dict(query=self.search.text(),app=self.app.text(),category=self.category.currentText(),start=start,end=end)

    def refresh(self):
        if self.closing:return
        if self.worker is not None:
            self.pending=True;return
        try:filters=self.filters()
        except ValueError:self.status.setText('Enter a valid ISO date range.');return
        self.worker=Query(self,filters);self.worker.ready.connect(self.render);self.worker.finished.connect(self.finished);self.worker.start()

    def finished(self):
        self.worker.deleteLater();self.worker=None
        if self.pending:self.pending=False;self.refresh()

    def clear_layout(self,layout):
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():
                widget=item.widget();widget.hide();widget.setParent(None);widget.deleteLater()

    def render(self,result):
        if 'error' in result:self.status.setText(result['error']);return
        self.clear_layout(self.recent);self.clear_layout(self.completed)
        for row in result['activities']:
            title=f"{row['name']} · {row['project'] or row['domain']} · {row['end']} · {row['duration']:.0f}s · {row['category']}"
            self.recent.addWidget(text(title));action(self.recent,'View / Resume activity',lambda checked=False,r=row:self.details(r))
        if not result['activities']:self.recent.addWidget(text(EMPTY))
        for row in result['tasks']:
            self.completed.addWidget(text(f"{row['title']} · {row['completed']} · {row['project']}"))
            action(self.completed,'View task',lambda checked=False,r=row:self.view_task(r))
        if not result['tasks']:self.completed.addWidget(text('No completed tasks yet.'))
        self.rows=result['history'];self.list.clear();previous=None
        for row in self.rows:
            day=row['end'][:10];prefix=(day+' — ') if day!=previous else '';previous=day
            self.list.addItem(prefix+f"{row['name']} · {row['domain']} · {row['duration']:.0f}s · {row['category']} · {row['state']}")
        self.status.setText(f'{len(self.rows)} records shown (maximum 200).' if self.rows else EMPTY)

    def view_task(self,row):
        self.window.navigate('My Tasks');panel=self.window.tasks_panel
        panel.filter.setCurrentText('All');panel.search.setText(row['title']);panel.refresh()

    def selected_details(self):
        if self.list.currentRow()>=0:self.details(self.rows[self.list.currentRow()])

    def details(self,row):
        # Reload to honor deletion/privacy changes since the UI snapshot.
        current=next((r for r in self.store.search(limit=1000) if r['id']==row['id']),None)
        if not current:return
        row=current
        box=QMessageBox(self);box.setWindowTitle('Activity details');box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText('\n'.join(f'{k}: {row[k]}' for k in ('name','start','end','duration','category','state','domain','title','url','project')))
        resume=None
        if row['app']=='code' and row['project']:
            resume=box.addButton('Resume approved project',QMessageBox.ButtonRole.ActionRole)
        elif row['kind']=='browser' and row['url'] and self.store.preferences()['urls']:
            resume=box.addButton('Open retained website',QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close);box.exec()
        if resume is not None and box.clickedButton() is resume:
            if row['app']=='code':
                try:self.window.projects.validate(row['project'])
                except (OSError,ValueError):QMessageBox.information(self,'Unavailable','Approved directory no longer exists.');return
                if self.confirm('Open this exact approved directory?\n'+row['project']):
                    self.window.run_task('project',lambda:self.window.projects.open(row['project']))
            else:
                from zorvyq.awareness.privacy import browser_metadata
                safe=browser_metadata({'url':row['url'],'incognito':False},self.store.preferences())
                if safe and safe['url']:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl(safe['url']))

    def confirm(self,message):
        return QMessageBox.question(self,'Activity privacy',message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def configure(self,**changes):
        self.manager.configure(**changes);self.refresh()

    def change(self,key,value):
        descriptions={'enabled':'Record approved application names, timestamps, active durations and categories locally. Default retention: 30 days. No screenshots, keystrokes, clipboard or commands. Watcher installation and upstream privacy configuration require separate approval.',
            'browser':'Read Firefox watcher events for approved domains only. Private and sensitive pages are excluded. Domain metadata is stored locally. ActivityWatch may store more upstream: configure its extension before starting it.',
            'titles':'Retain safe window and page titles. Titles can expose private information; configure upstream title filters first.',
            'urls':'Retain approved website URLs after removing query strings, fragments and credentials. Paths can contain private information.',
            'metrics':'Record CPU, RAM, disk, battery, interface state and uptime locally once per minute. No network scans or packet contents.',
            'managed_runtime':'Permit ZORVYQ to start the verified local ActivityWatch server and reviewed GNOME Wayland watcher while monitoring is enabled. The GNOME extension must be manually approved and enabled. Only approved application identifiers are reported upstream; window titles are stripped. Owned children stop on pause/disable/shutdown. Independently running watchers remain your responsibility.',
            'start_at_login':'Start previously approved monitoring automatically when the existing ZORVYQ GUI opens after login. Your GUI autostart entry is unchanged.',
            'background':'Install and enable only ~/.config/systemd/user/zorvyq-awareness.service. It starts the same single-instance consumer after graphical login and keeps approved collection running after the GUI closes. It stops at logout. No system service or GUI autostart change. Disable this switch to stop the service.',
            'processes':'Record a bounded selection of your own process names, PIDs, RSS and CPU usage. No executable paths or command lines.',
            'network':'Record bounded TCP/UDP connection counts only, without peer addresses, ports, packet contents or credentials.'}
        allowed=not value or self.confirm(descriptions[key]+'\n\nEnable this collection?')
        if allowed and key=='background':
            if self.service_worker is not None:return
            self.manager.stop()
            changes={'background':value}
            if value:changes['start_at_login']=True
            self.store.configure(consent=value,**changes)
            box=self.switches['start_at_login'];box.blockSignals(True);box.setChecked(self.store.preferences()['start_at_login']);box.blockSignals(False)
            self.service_worker=ServiceChange(self,value)
            self.service_worker.ready.connect(self.service_changed)
            self.service_worker.finished.connect(self.service_finished)
            self.service_worker.start()
        elif allowed:self.manager.configure(consent=value,**{key:value})
        else:
            box=self.switches[key];box.blockSignals(True);box.setChecked(False);box.blockSignals(False)
        self.check()

    def service_changed(self,success):
        if not success:
            self.store.configure(background=False)
            box=self.switches['background'];box.blockSignals(True);box.setChecked(False);box.blockSignals(False)
            QMessageBox.information(self,'Background monitoring unavailable','The user service could not be changed. Review systemctl --user status zorvyq-awareness.service. Monitoring remains opt-in; no GUI autostart change was made.')
        if not self.store.preferences()['background']:self.manager.start()
        self.check()

    def service_finished(self):self.service_worker.deleteLater();self.service_worker=None
    def start_now(self):
        if not self.store.preferences()['enabled']:
            self.switches['enabled'].setChecked(True)
        else:self.manager.start()
    def stop_now(self):
        self.manager.configure(enabled=False,metrics=False)
        for key in ('enabled','metrics'):
            self.switches[key].blockSignals(True);self.switches[key].setChecked(False);self.switches[key].blockSignals(False)
        self.check()

    def website_category(self):
        domain,ok=QInputDialog.getText(self,'Website category','Exact domain:')
        if not ok:return
        category,ok=QInputDialog.getText(self,'Website category','Category (including custom categories):')
        if not ok:return
        try:self.store.set_website_category(domain,category)
        except ValueError:QMessageBox.information(self,'Invalid category','Enter an exact domain and a short plain category name.');return
        if self.category.findText(category)<0:self.category.addItem(category)
        self.manager.revision+=1;self.refresh()

    def pause(self):self.configure(paused=True);self.check()
    def resume(self):self.configure(paused=False);self.check()

    def edit_list(self,key,title):
        value,ok=QInputDialog.getText(self,title,'Comma-separated exact entries (domains permit subdomains):',text=', '.join(self.store.preferences()[key]))
        if ok:self.configure(**{key:[s.strip().casefold() for s in value.split(',') if s.strip()]})

    def associate(self):
        rows=self.selected_rows()
        if len(rows)!=1:return
        path=QFileDialog.getExistingDirectory(self,'Select approved project',str(self.window.projects.root))
        if not path:return
        category,ok=QInputDialog.getItem(self,'Activity category','Category',
            ['Programming','Browsing','Terminal','Files','Studying','Other'],0,False)
        if not ok:return
        try:self.store.associate(rows[0]['id'],path,self.window.projects,category)
        except (ValueError,OSError):QMessageBox.information(self,'Unavailable','Select an existing approved project directory.');return
        self.refresh()

    def summarize(self):
        if self.window.busy:return
        if not self.confirm('Allow the selected local model to summarize numeric category totals for today once? No browser domains, URLs, window titles or task titles are sent. Deterministic facts remain separate from unverified model interpretation.'):
            return
        queries=self.window.activity_queries;plan=queries.summary_plan()
        ticket=queries.permissions.approve(plan,confirmed=True);model=self.window.chat_model.currentData()
        self.window.run_task('activity_summary',lambda:queries.summarize(plan,ticket,self.window.controller,model),self)

    def selected_rows(self):return [self.rows[self.list.row(i)] for i in self.list.selectedItems()]
    def delete_selected(self):
        rows=self.selected_rows()
        if rows and self.confirm('Delete selected activity records?'):
            self.manager.delete([r['id'] for r in rows]);self.refresh()
    def clear(self):
        if self.confirm('Permanently clear ZORVYQ activity and metric history? My Tasks and upstream ActivityWatch history remain separate.'):
            self.manager.delete();self.refresh()
    def export(self):
        rows=self.selected_rows()
        if not rows:return
        path,_=QFileDialog.getSaveFileName(self,'Export selected activity','','JSON (*.json)')
        if path:
            try:self.store.export(path,rows)
            except (OSError,ValueError):QMessageBox.information(self,'Export unavailable','Choose a new owner-writable file.')
    def stop(self):
        self.closing=True;self.pending=False;self.timer.stop()
        if self.worker is not None:self.worker.wait(5000)
        if self.service_worker is not None:self.service_worker.wait(30000)
