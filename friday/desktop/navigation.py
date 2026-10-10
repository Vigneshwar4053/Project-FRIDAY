"""Conservative Files controller for Nautilus' unsupported window navigation API.

Open/ShowFolders cannot address a particular window. A launch receipt is never
a window handle. Until a reviewed target-window API exists, do not dispatch a
second implicit open, even for a different location or after a cooldown.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FilesActivity:
    application_id: str
    requested_directory: str
    directory_identity: tuple
    launch_outcome: str
    verified_navigation_outcome: object = None
    managed_window_identity: object = None


class FileManagerNavigationController:
    supports_reuse = False
    supports_window_replacement = False

    def __init__(self):
        self.last_activity = None  # One bounded, session-local launch receipt.

    def blocked(self, lease, *, retry):
        if self.last_activity is None or retry:
            return None
        folder = lease['record_arguments']['folder_id']
        command = ('retry open my ' + folder[8:] + ' project folder in ubuntu files'
                   if folder.startswith('project_') else
                   'retry open ubuntu files' if folder == 'home' else 'retry open ' + folder+' in ubuntu files')
        return {'status':'navigation_unsupported',
                'message':'Same-window Files navigation is unavailable: Nautilus has no reviewed target-window navigation API. '
                          'Safe window replacement is also unavailable: the API cannot establish which exact window FRIDAY created. No window was closed. '
                          'An earlier Files launch may still be open; its window and current folder cannot be verified, even if you closed it. '
                          'No navigation or new process was requested. Navigate manually in Files, or type "' + command +
                          '" for a fresh-approved launch that may create another window.'}

    def record_launch(self, lease, outcome):
        self.last_activity = FilesActivity('files', str(lease['path']),
                                          lease['identity'], outcome)

    def clear(self):
        self.last_activity = None
