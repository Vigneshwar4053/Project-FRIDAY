"""Operation cards/details and a bounded embedded console; no terminal launcher."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QGridLayout,QHBoxLayout,QLabel,QPushButton,
    QPlainTextEdit,QDialog,QLineEdit,QCheckBox,QComboBox,QMessageBox,QFileDialog,QApplication)
from zorvyq.operations.contracts import Permission
from zorvyq.operations.registry import resolve_tool
from zorvyq.operations.reporting import export_json, export_markdown, markdown
from zorvyq.diagnostics import explanation

class OperationsPanel(QWidget):
    def __init__(self,window,engine,security=False):
        super().__init__();self.window=window;self.engine=engine;self.report=None;self.details=None;self.dialog=None
        layout=QVBoxLayout(self)
        title=QLabel('CYBERSECURITY OPERATIONS' if security else 'ZORVYQ SYSTEM OPERATIONS')
        title.setObjectName('heading');layout.addWidget(title)
        notice=QLabel('Read-only local checks require exact scope approval. Network discovery requires separate target authorization. '
            'Experimental adapters — mocked tests do not establish live success. No automatic repairs or diagnosis at startup.')
        notice.setWordWrap(True);layout.addWidget(notice)
        grid=QGridLayout();layout.addLayout(grid);self.cards={}
        operations=[op for op in engine.registry.operations.values() if op.implemented and
                    (not security or op.operation_id in ('security.overview','network.overview','network.discovery','logs.overview'))]
        for index,op in enumerate(operations):
            card=QWidget();body=QVBoxLayout(card)
            body.addWidget(QLabel(op.name))
            state=QLabel(engine.registry.availability(op.operation_id)+'\n'+str(op.permission)+'\nLast successful execution: none in this session')
            state.setWordWrap(True);body.addWidget(state);self.cards[op.operation_id]=state
            action=QPushButton('Configure Scan' if op.permission==Permission.NETWORK else 'Inspect / Preview')
            action.setProperty('runtimeAction',True)
            action.clicked.connect(lambda checked=False,identity=op.operation_id:self.open_details(identity))
            body.addWidget(action);grid.addWidget(card,index//2,index%2)
        self.status=QLabel('Idle — no operations run automatically');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.console=QPlainTextEdit();self.console.setReadOnly(True);self.console.setMaximumBlockCount(400)
        self.console.setPlaceholderText('Embedded execution console — bounded sanitized output');layout.addWidget(self.console)
        cancel=QPushButton('Cancel current operation');cancel.clicked.connect(engine.cancel);layout.addWidget(cancel)
        self.output=QPlainTextEdit();self.output.setReadOnly(True);self.output.setPlaceholderText('Structured report and limitations');layout.addWidget(self.output)
        actions=QHBoxLayout()
        analyze=QPushButton('Analyze normalized metrics with selected model')
        analyze.setProperty('runtimeAction',True);analyze.clicked.connect(self.analyze);actions.addWidget(analyze)
        export=QPushButton('Export report…');export.clicked.connect(self.export);actions.addWidget(export)
        copy=QPushButton('Copy command output');copy.clicked.connect(lambda:QApplication.clipboard().setText(self.console.toPlainText()));actions.addWidget(copy)
        layout.addLayout(actions)
        future=QPlainTextEdit();future.setReadOnly(True);future.setMaximumHeight(160)
        future.setPlainText('\n'.join(op.name+' — NOT IMPLEMENTED; individual design/approval required' for op in engine.registry.operations.values() if not op.implemented))
        layout.addWidget(QLabel('Future registry modules — unavailable'));layout.addWidget(future)

    def open_details(self,operation_id):
        if self.window.busy:return
        if self.dialog is not None:
            self.dialog.close()
        op=self.engine.registry.operations[operation_id]
        dialog=QDialog(self.window);dialog.setWindowTitle(op.name);dialog.resize(760,640)
        layout=QVBoxLayout(dialog)
        purpose=QLabel(op.purpose+'\nPermission: '+str(op.permission)+'\n'+op.privacy)
        purpose.setWordWrap(True);layout.addWidget(purpose)
        target=QLineEdit();purpose_input=QLineEdit();project=QComboBox()
        authorized=QCheckBox('I am authorized to assess this exact network target for the stated purpose')
        if op.permission==Permission.NETWORK:
            target.setPlaceholderText('Explicit private IP/CIDR, maximum 256 addresses')
            purpose_input.setPlaceholderText('Assessment purpose')
            layout.addWidget(target);layout.addWidget(purpose_input);layout.addWidget(authorized)
        elif operation_id in ('storage.overview','developer.environment'):
            project.addItem('Local system only — no project files',None)
            for path in self.engine.registry.projects():project.addItem(path.name,str(path))
            layout.addWidget(QLabel('Optional owner-selected project scope'));layout.addWidget(project)
        else:layout.addWidget(QLabel('Target: local system metadata only'))
        preview=QPlainTextEdit();preview.setReadOnly(True);preview.setMaximumHeight(230);layout.addWidget(preview)
        progress=QPlainTextEdit();progress.setReadOnly(True);progress.setMaximumBlockCount(150);layout.addWidget(progress)
        def make_plan():
            inputs={}
            if op.permission==Permission.NETWORK:inputs={'target':target.text(),'purpose':purpose_input.text()}
            elif project.currentData():inputs={'project':project.currentData()}
            return self.engine.registry.plan(operation_id,inputs)
        def dry_run():
            try:preview.setPlainText(json.dumps(self.engine.preview(make_plan()),indent=2))
            except (ValueError,OSError,KeyError) as error:preview.setPlainText(str(error))
        dry=QPushButton('Dry-run preview');dry.clicked.connect(dry_run);layout.addWidget(dry)
        run=QPushButton('Approve exact scope and Run…')
        stages=op.stages
        possible=(bool(resolve_tool('nmap') and resolve_tool('prlimit')) if op.permission==Permission.NETWORK else
                  any(s.collector or (resolve_tool(s.tool) and resolve_tool('prlimit')) for s in stages))
        run.setEnabled(possible);run.setProperty('runtimeAction',possible)
        def execute():
            if self.window.busy:return
            try:
                plan=make_plan();proposal=self.engine.preview(plan)
                preview.setPlainText(json.dumps(proposal,indent=2))
                if op.permission==Permission.NETWORK and not authorized.isChecked():
                    raise PermissionError('Confirm authorization for this exact target first.')
                reply=QMessageBox.question(dialog,'Approve exact operation scope',
                    'Execute this reviewed plan once?\nTarget: '+plan.target+'\nPermission: '+str(plan.permission)+'\n\n'+json.dumps(proposal,indent=2),
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if reply!=QMessageBox.StandardButton.Yes:return
                ticket=self.engine.approve(plan,confirmed=True,authorized_target=authorized.isChecked())
                self.console.clear();self.status.setText('Running '+op.name)
                self.on_progress('Operation: '+op.name+'\nApproved planned command sequence:\n'+json.dumps(proposal['stages'],indent=2))
                self.window.run_task('operation',lambda:self.engine.run(plan,ticket,self.window.worker.progress.emit),self)
            except (ValueError,OSError,PermissionError,KeyError) as error:
                preview.setPlainText(str(error))
        run.clicked.connect(execute);layout.addWidget(run)
        cancel=QPushButton('Cancel');cancel.clicked.connect(self.engine.cancel);layout.addWidget(cancel)
        close=QPushButton('Close details');close.clicked.connect(dialog.close);layout.addWidget(close)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.details=progress
        self.dialog=dialog
        def closed():
            if self.dialog is dialog:
                self.details=None;self.dialog=None
        dialog.destroyed.connect(closed)
        dry_run();dialog.show()

    def on_progress(self,text):
        self.console.appendPlainText(text)
        if self.details is not None:
            try:self.details.appendPlainText(text)
            except RuntimeError:self.details=None

    def finished(self,value):
        self.report=value;self.output.setPlainText(markdown(value))
        self.status.setText(value.get('execution_status','Completed')+' — inspect limitations and NOT CHECKED items')
        for identity,label in self.cards.items():
            label.setText(self.engine.registry.availability(identity)+'\n'+str(self.engine.registry.operations[identity].permission)+
                '\nLast successful execution: '+self.engine.last_verified.get(identity,'none in this session'))
        self.on_progress('Report ready; AI interpretation is optional. No report saved automatically.')

    def analyze(self):
        if self.window.busy or self.report is None:return
        model=self.window.chat_model.currentData()
        mode=self.window.preferences.values['response_mode']
        self.window.active_model=model
        self.window.run_task('analysis',lambda:self.window.controller.analyze_operation(self.report,model,mode),self)

    def analyzed(self,value):
        if self.report is not None:
            self.report['ai_analysis']=value
            self.output.setPlainText(markdown(self.report))
        self.status.setText('AI hypotheses added — unverified; deterministic measurements remain authoritative')

    def export(self):
        if self.report is None or self.window.busy:return
        path,selected=QFileDialog.getSaveFileName(self,'Export local report (review sensitive metadata)','zorvyq-report.json','JSON (*.json);;Markdown (*.md)')
        if not path:return
        try:(export_markdown if selected.startswith('Markdown') else export_json)(self.report,path)
        except (OSError,ValueError):
            QMessageBox.information(self,'Export','Choose a new writable file; existing files and symlink targets are not overwritten.')
