# My Tasks

Tasks use a separate SQLite database beside desktop preferences: normally `~/.config/zorvyq/tasks.sqlite3`, or the corresponding absolute XDG_CONFIG_HOME directory. It is created with mode 0600; no knowledge/provenance table or chat history is used. Each mutation uses a database transaction and parameterized SQL. Every task has a UUID, title, description, status, priority, created/due/reminder/completed times and optional project association. Completed time is retained when editing an already completed record.

Use My Tasks to Add, Edit, Complete or Delete. Search covers title, description and project. Filters cover active, today's, upcoming, overdue and each status. Dates accept ISO dates/times with an optional timezone offset; a time without an offset uses local Ubuntu time. A date by itself means local midnight. Set a full timestamp for precise reminders. Invalid dates or failed saves leave the edit form open with an error. Cancelling does not write.

Text or confirmed voice supports:

- “Add a task to review my project tomorrow.” opens a review form, proposing tomorrow at 17:00 local time as the due date. This does not create a reminder automatically.
- “Show my pending tasks.” uses the real active count and opens My Tasks.
- “Mark the website task complete.” searches candidates, asks for an exact selection if ambiguous, then asks confirmation.
- “Delete the completed test task.” searches completed matches only, requires exact selection when ambiguous and confirms deletion.

The grammar is intentionally limited. Other language can still be answered as ordinary conversation, but a model has no task database write API. Task command content is not appended to model/chat history. Task forms provide the full field set.

## Reminders

A Qt timer checks persisted reminders every 30 seconds, starting shortly after launch. Overdue reminders missed while logged out or rebooting are checked on next launch. A transaction atomically claims each due reminder before showing an in-app notification. A generic Ubuntu desktop notification is also attempted when Qt reports a supported system tray; task titles remain inside ZORVYQ. No global service, cron entry, systemd timer or login configuration is created.

Claims are persistent and avoid duplicate notifications across restarts or another database connection. Changing the reminder time clears its claim. Completing/cancelling a task prevents notification. Delivery is at most once per saved reminder time: a crash after a claim but before display can suppress that notification. The task and reminder remain visible for review. No guarantee of delivery while the application is closed or of desktop-notification delivery is made.

Dashboard counts come from stored records: active, due today, overdue and future unclaimed reminders, plus the next three future reminders. Saved tasks survive application restart, logout and reboot.

## Owner acceptance

Create tasks with each optional field; restart the application and verify them. Search/filter, change status, edit priority and complete a task. Create two matching titles and verify command selection plus confirmation. Cancel a delete and check neither record changes. Set a reminder a minute ahead, observe one notification and restart to check no duplicate. Close before another reminder, reopen after its time and verify a missed notification. Exporting or copying task data is not automatic.
