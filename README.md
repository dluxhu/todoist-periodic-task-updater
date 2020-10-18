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

Recurring task handling:
=========================

* A recurring task can be also serial or parallel (identified by the postfixes mentioned above)
* If a recurring task reached due time, all of the completed subtasks will be uncompleted and the recurring task itself will be marked as completed (= moved to the next time).
* A recurring task or its subtasks can be _serial_ or _paralell_, the same way as non-recurring tasks.
* If a _serial_ or _parallel_ recurring task has recurring children, then it is always treated as an incomplete task, so it might break the _serial_ algorithm.