todoist-periodic-task-updater
=============================

Updates Todoist tasks based on various custom rules.

Based on [NextAction](https://github.com/nikdoof/NextAction) by [https://github.com/nikdoof](https://github.com/nikdoof).

Requirements
============

* Python 3.0
* `todoist-python` package.

Custom rules
============

* If a project name or a task name is postfixed with `(=)`, then its tasks or subtasks are treated as _parallel_ tasks, if they are postfixed with `(-)`, they are treated as _serial_ tasks.
* If a _parallel_ task is active, then all of its descendants are active.
* If a _serial_ task is active, then the first of its descendants is active, the rest is inactive.
* An active leaf task has their due dates set to `today` (if if it set already to any date, then it is not updated) and has their `NoDate` label removed.
* An inactive leaf task has a `NoDate` label and have its due date removed.
* Non-leaf _serial_ or _parallel_ _active_ or _inactive_ tasks are considered as inactive (`NoDate` is set, no due date).
* Non-leaf tasks that are neither _serial_ nor _paralell_ are treated as leaf tasks.