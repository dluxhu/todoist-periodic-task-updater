# todoist-periodic-task-updater

Updates Todoist tasks based on various custom rules.

Based on [NextAction](https://github.com/nikdoof/NextAction) by [https://github.com/nikdoof](https://github.com/nikdoof), but it was almost completely rewritten in the process.

# Requirements

* Python 3.0
* `todoist-python` package.

# Features

* Parallel and serial task handling
* Set `NoDate` label to subtasks of paralell or serial tasks or projects
* Uncomplete subtasks of serial or parallel recurring tasks

# How it works

## Parallel and serial task handling

* If a project name or a task name is postfixed with `(=)`, then its tasks or subtasks are treated as _parallel_ tasks, if they are postfixed with `(-)`, they are treated as _serial_ tasks.
* If a _parallel_ task is active, then all of its descendants has their due date set to now.
* If a _serial_ task is active, then the first of its descendants is due now, the rest does not have their due date set.
* If a serial or parallel task has a serial or parallel subtask, then the task's due date is not directly set to now, only its (first or all) subtask(s) (depending on whether it is a serial or parallel subtask)

## `NoDate` label setting

* A task or subtask is _owned_ by the script, if it is in a subtree of a project or item that is either parallel or serial.
* If a task is _owned_, then it either has a due date set or has the `NoDate` label applied to it.

## "Next" labels

It is possible to specify a prefix for labels that are added for tasks that are available to be done. There can be multiple, because you might want to separate them by category. In the default case, this prefix is `::`. If a task has a label with this prefix, then today's date is not added to the task, because it is already considered to be 'known about'.

## Recurring task handling

* A recurring task can be also serial or parallel (identified by the postfixes mentioned above)
* If a recurring task reached due time, all of the completed subtasks will be uncompleted and the recurring task itself will be marked as completed (= moved to the next time).