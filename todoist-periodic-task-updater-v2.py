#!/usr/bin/env python3

import logging
import argparse
import pytz
import re
import socket
import time
import sys

from collections import OrderedDict 
from datetime import datetime
from todoist.api import TodoistAPI

LAST_RUN_CONST = '$TodoistUpdaterV2LastRun$'

timezone = None
now = None
args = None
nodate_label_id = None
next_label_ids = set()
rerun = False

def main():
    """Main process function."""

    parse_args()
    set_debug()
    debuglog = DebugLogger()
    api = connect(debuglog)

    while True:
        global rerun
        rerun = False
        try:
            api.sync()
            set_timezone_and_now(api)

            for project in api.projects.all():
                process_project(api, debuglog, project)

            if len(api.queue):
                debuglog.log('changes queued for sync: %s'% str(api.queue))
                if args.execute or args.execute1:
                    logging.debug('Commiting to Todoist.')
                    api.commit()
                    if args.execute1: rerun = False
                    if rerun: continue
            else:
                debuglog.log('No changes queued, skipping sync.')

        except Exception as e:
            logging.exception('Error trying to sync with Todoist API: %s' % str(e))
        

        if args.periodical_sync_sec is None:
            break

        debuglog.log('Sleeping for %d seconds' % args.periodical_sync_sec)
        time.sleep(args.periodical_sync_sec)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--api_key', help='Todoist API Key')
    parser.add_argument('-l', '--label', help='The "No Date" label to use', default='NoDate')
    parser.add_argument('--debug', help='Enable debugging', action='store_true')
    parser.add_argument('-p', '--periodical_sync_sec', help='Run the sync periodically', type=int, default=None)
    parser.add_argument('--parallel_suffix', default='(=)')
    parser.add_argument('--serial_suffix', default='(-)')
    parser.add_argument('-x', '--execute', action='store_true', default=False, help='Execute the changes (otherwise just prints them)')
    parser.add_argument('-1', '--execute1', action='store_true', default=False, help='Execute the first round of changes (useful for debugging')
    parser.add_argument('--next_prefix', default='::', help='Prefix for labels that store "Next" tasks (tasks that are available to do)')
    global args
    args = parser.parse_args()

def set_debug():
    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level)

def connect(parentdebuglog):
    if not args.api_key:
        logging.error('No API key set, exiting...')
        sys.exit(1)

    # Run the initial sync
    debuglog = parentdebuglog.sublogger('Connecting to the Todoist API')
    api = TodoistAPI(token=args.api_key)
    debuglog.log('Syncing the current state from the API')
    api.sync()

    # Check the NoDate label exists
    labels = api.labels.all(lambda x: x['name'] == args.label)
    if len(labels) > 0:
        global nodate_label_id
        nodate_label_id = labels[0]['id']
        debuglog.log('Label %s found as label id %d' % (args.label, nodate_label_id))
    else:
        debuglog.error("Label %s doesn't exist, please create it." % args.label)
        sys.exit(1)
    global next_label_ids
    next_label_ids = set(map(
        lambda x: x['id'],
        api.labels.all(lambda x: x['name'].startswith(args.next_prefix))
    ))
    debuglog.log('"Next" label ids: %s' % (next_label_ids))
    
    return api

class DebugLogger:
    def __init__(self, level = 0):
        self.level = level

    def log(self, str):
        logging.debug('  ' * self.level + str)

    def sublogger(self, str):
        self.log(str)
        return DebugLogger(self.level + 1)

def set_timezone_and_now(api):
    global timezone, now
    timezone = pytz.timezone(api.user.state['user']['tz_info']['timezone'])
    now = datetime.now(tz = timezone)
    logging.debug('Timezone: %s, now: %s', timezone, now)

class Props:
    def __init__(self, name):
        # to avoid pylint warnings:
        self.name = name
        self.is_parallel = None
        self.is_serial = None

    def __repr__(self):
        p = vars(self)
        pp = {}
        for k in p.keys():
            if p[k] is not None: pp[k] = p[k]
        return str(pp)

def process_project(api, parentdebuglog, project):
    if project.data['is_archived']:
        parentdebuglog.log('Project %s is archived, skipping.' % project.data['name'])
        return

    props = Props(project['name'].strip())
    set_parallel_or_serial(props)
    props.owned = None
    props.is_recurring = None
    props.recurring_reactivation = None
    props.suppress_tree_due_now = None

    debuglog = parentdebuglog.sublogger('Project: %s' % props)

    # Get all items for the project, sort by the item_order field.
    items = sorted(api.items.all(lambda x: x.data['project_id'] == project.data['id']),
                   key=lambda x: x.data['child_order'])
    
    (unused_completed_items, active_items) = get_top_level_items(items)

    for idx, item in enumerate(active_items):
        process_item(items, props, debuglog, item, idx)

def process_item(items, parentprops, parentdebuglog, item, idx):
    props = Props(item['content'])
    set_parallel_or_serial(props)

    props.id = item.data['id']
    props.first = idx == 0

    (completed_subitems, active_subitems) = get_subitems(items, item)

    props.has_active_subitems = len(active_subitems) > 0
    props.has_completed_subitems = len(completed_subitems) > 0 or None

    props.owned = parentprops.owned or props.is_parallel or props.is_serial
    props.is_recurring = is_recurring(item)
    props.is_due = is_due(item)

    # Recurring reactivation: when a recurring parallel or serial task becomes due, all of
    # its subtasks will be uncompleted (re-activated) and the recurring task itself will be
    # completed.
    # Note: this does not work now.
    props.recurring_reactivation = None # props.is_recurring and props.is_due and (
    #     props.is_parallel or props.is_serial
    # )

    props.due_now = not parentprops.suppress_tree_due_now and (
        parentprops.is_parallel or parentprops.is_serial)

    props.suppress_tree_due_now = props.due_now and (parentprops.is_serial and not props.first)

    props.item_due_now = props.due_now and not props.suppress_tree_due_now and not (
        (props.is_parallel or props.is_serial) and props.has_active_subitems)

    debuglog = parentdebuglog.sublogger('Item: %s' % props)

    if props.recurring_reactivation:
        complete_item(item, debuglog)
        for item in completed_subitems:
            reactivate_completed_subtree(items, props, debuglog, item)
        # We need to rerun the sync after the subtree is completed, because these items
        # will be active in the next run.
        global rerun
        rerun = True
        return

    if props.item_due_now:
        activate_item(item, props, debuglog)
    elif props.owned:
        own_item(item, debuglog)

    if item['content'].startswith(LAST_RUN_CONST):
        debuglog.log('## Updating last run timestamp')
        item.update(content = LAST_RUN_CONST + ': %s %s' % (socket.gethostname(), now))

    for idx, item in enumerate(active_subitems):
        process_item(items, props, debuglog, item, idx)

def reactivate_completed_subtree(items, parentprops, parentdebuglog, item):
    props = Props(item['content'])

    debuglog = parentdebuglog.sublogger('Reactivating item: %s' % props)

    uncomplete_item(item, debuglog)

    (completed_subitems, unused_active_subitems) = get_subitems(items, item)
    for item in completed_subitems:
        reactivate_completed_subtree(items, props, debuglog, item)

    # Note: for now, we just reactivate the completed items, but it might be possible that
    # there are some completed items under currently active tasks. Consider recursing into
    # active_subitems, too

def set_parallel_or_serial(props):
    name = props.name
    (props.delay, name) = has_delay_suffix(name)
    props.is_parallel = name.endswith(args.parallel_suffix)
    props.is_serial = name.endswith(args.serial_suffix)

def get_top_level_items(items):
    return get_subitems(items, None)

def get_subitems(items, parent_item):
    """Search a flat item list for child items."""
    parent_id = None
    if parent_item:
        parent_id = parent_item['id']
    completed_result_items = []
    active_result_items = []
    for item in items:
        if item['parent_id'] == parent_id:
            if item.data['checked'] == 0:
                active_result_items.append(item)
            else:
                completed_result_items.append(item)
    return (completed_result_items, active_result_items)

def has_delay_suffix(str):
    m = re.match('(.*){(.*?)}', str)
    if m:
        return (m.group(2), m.group(1))
    else:
        return (None, str)

def own_item(item, debuglog):
    if item['due'] is None:
        add_nodate_label(item, debuglog)

def activate_item(item, props, debuglog):
    set_date(item, props, debuglog)
    remove_nodate_label(item, debuglog)

def uncomplete_item(item, debuglog):
    if item['date_completed'] is not None:
        debuglog.log('## Uncompleting item')
        item.uncomplete()
        if item['due'] is not None:
            debuglog.log('## Removing due date')
            item.update(due=None)

def complete_item(item, debuglog):
    if item['date_completed'] is None:
        debuglog.log('## Completing the item')
        item.close()

def add_nodate_label(item, debuglog):
    if nodate_label_id in item['labels']:
        return
    labels = item['labels']
    debuglog.log('## Updating %s with "NoDate" label' % item['content'])
    labels.append(nodate_label_id)
    item.update(labels=labels)

def remove_nodate_label(item, debuglog):
    if not nodate_label_id in item['labels']:
        return
    labels = item['labels']
    debuglog.log('## Removing "NoDate" label from %s' % (item['content']))
    labels.remove(nodate_label_id)
    item.update(labels=labels)

def set_date(item, props, debuglog):
    if set(item['labels']).intersection(next_label_ids):
        debuglog.log('## Not setting due date for item %s, because one of the "Next" labels exist' % (item['content']))
        return
    if item['due'] is None:
        new_due = props.delay if props.delay is not None else 'today'
        debuglog.log('## Setting due date to %s for item %s' % (new_due, item['content']))
        item.update(due={'string' : new_due })

def is_recurring(item):
    due = item['due']
    return due['is_recurring'] if not due is None else False

def is_due(item):
    due = parse_due(item)
    if due is None: return False
    # logging.debug("is_active: due parsed: %s", due)
    return due <= now

def parse_due(item):
    due = item['due']
    if due is None: return None
    tz = due['timezone'] if due['timezone'] is not None else timezone

    try:
        due_date = datetime.strptime(due['date'], '%Y-%m-%dT%H:%M:%S')
    except:
        due_date = datetime.strptime(due['date'], '%Y-%m-%d')

    return tz.localize(due_date)

if __name__ == '__main__':
    main()
