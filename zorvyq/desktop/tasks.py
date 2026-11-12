"""Explicit local task editing and in-app reminder delivery."""
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,
    QPushButton,QListWidget,QDialog,QFormLayout,QDialogButtonBox,QMessageBox)
import sqlite3
from datetime import datetime
from zorvyq.tasks import STATUSES, PRIORITIES, now

class TasksPanel(QWidget):
    def __init__(self, window, store):
        super().__init__(); self.window=window; self.store=store
        layout=QVBoxLayout(self);layout.addWidget(QLabel('My Tasks'))
        self.summary=QLabel();layout.addWidget(self.summary)
        self.search=QLineEdit();self.search.setPlaceholderText('Task Search');layout.addWidget(self.search)
        self.filter=QComboBox();self.filter.addItems(['All','Active','Today','Upcoming','Overdue',*STATUSES]);layout.addWidget(self.filter)
        shortcuts=QHBoxLayout();layout.addLayout(shortcuts)
        for title,view in [("Today's Tasks",'Today'),('Upcoming Tasks','Upcoming'),('Completed Tasks','Completed')]:
            control=QPushButton(title);control.clicked.connect(lambda checked=False,v=view:self.filter.setCurrentText(v));shortcuts.addWidget(control)
        self.list=QListWidget();layout.addWidget(self.list)
        self.search.textChanged.connect(self.refresh);self.filter.currentTextChanged.connect(self.refresh)
        actions=QHBoxLayout();layout.addLayout(actions)
        for title, callback in [('Add Task',lambda:self.edit()),('Edit Task',lambda:self.selected('edit')),
                                ('Complete Task',lambda:self.selected('complete')),('Delete Task',lambda:self.selected('delete'))]:
            control=QPushButton(title);control.clicked.connect(callback);actions.addWidget(control)
        layout.addWidget(QLabel('Reminders run while ZORVYQ is open. Missed reminders appear on next launch.\nDates use local time unless an ISO timezone offset is entered.'))
        self.refresh()

    def refresh(self):
        self.rows=self.store.rows(self.search.text(),self.filter.currentText());self.list.clear()
        for row in self.rows:
            self.list.addItem(f"{row['title']} · {row['status']} · {row['priority']} · due {row['due'] or 'none'} · reminder {row['reminder'] or 'none'}")
        self.summary.setText(self.store.summary())
        if hasattr(self.window,'awareness_panel'):self.window.awareness_panel.refresh()
        if hasattr(self.window,'task_summary'):self.window.task_summary.setText(self.store.summary())
        if hasattr(self.window,'task_reminders'):
            upcoming=sorted((r for r in self.store.rows(view='Active') if r['reminder'] and not r['notified'] and datetime.fromisoformat(r['reminder']) > now()),key=lambda r:r['reminder'])[:3]
            self.window.task_reminders.setText('Upcoming reminders: '+('; '.join(r['title']+' at '+r['reminder'] for r in upcoming) or 'none'))

    def selected(self, action):
        index=self.list.currentRow()
        if index<0:return
        row=self.rows[index]
        if action=='edit':self.edit(row);return
        if self.confirm(action,row):
            self.store.delete(row['id']) if action=='delete' else self.store.change_status(row,'Completed')
            self.refresh()

    def confirm(self,action,row):
        return QMessageBox.question(self,'Confirm task change',action.capitalize()+' task: '+row['title']+'?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def edit(self,row=None,initial=None):
        row=row or {};initial=initial or {}
        dialog=QDialog(self);dialog.setWindowTitle('Edit Task' if row else 'Add Task');form=QFormLayout(dialog);fields={}
        for key,title in [('title','Title'),('description','Description'),('project','Project association'),('due','Due (ISO date/time)'),('reminder','Reminder (ISO date/time)')]:
            field=QLineEdit(row.get(key) or initial.get(key) or '');fields[key]=field;form.addRow(title,field)
        for key,values in [('status',STATUSES),('priority',PRIORITIES)]:
            field=QComboBox();field.addItems(values);field.setCurrentText(row.get(key,'Pending' if key=='status' else 'Normal'));fields[key]=field;form.addRow(key.capitalize(),field)
        error=QLabel();form.addRow(error)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);form.addRow(controls)
        def save():
            try:
                self.store.save(identity=row.get('id'),**{k:(f.currentText() if isinstance(f,QComboBox) else f.text()) for k,f in fields.items()})
            except (ValueError,OSError,sqlite3.Error) as exc:error.setText(str(exc));return
            dialog.accept()
        controls.accepted.connect(save);controls.rejected.connect(dialog.reject)
        accepted=dialog.exec()==QDialog.DialogCode.Accepted;self.refresh();return accepted

    def handle(self, request):
        action=request['action']
        if action=='list':
            self.filter.setCurrentText('Active');self.refresh();self.window.navigate('My Tasks')
            return f"You have {len(self.store.rows(view='Active'))} pending or in progress tasks. Review them in My Tasks."
        if action=='add':
            return 'Task saved.' if self.edit(initial=request) else 'Task creation cancelled.'
        matches=self.store.rows(query=request['query'],view='Completed' if request.get('completed_only') else 'All')
        if not matches:return 'No matching task found. Review My Tasks.'
        if len(matches)>1:
            from PySide6.QtWidgets import QInputDialog
            options=[f"{r['title']} · {r['status']} · {r['id']}" for r in matches]
            selected,accepted=QInputDialog.getItem(self,'Choose exact task','Multiple tasks match:',options,0,False)
            if not accepted:return 'Task change cancelled.'
            row=matches[options.index(selected)]
        else:row=matches[0]
        if not self.confirm(action,row):return 'Task change cancelled.'
        self.store.delete(row['id']) if action=='delete' else self.store.change_status(row,'Completed')
        self.refresh();return 'Task deleted.' if action=='delete' else 'Task completed.'
