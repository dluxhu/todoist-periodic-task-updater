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

def main():
    """Main process function."""

    parse_args()
    set_debug()
    debuglog = DebugLogger()
    api = connect(debuglog)

    while True:
        try:
            api.sync()
            set_timezone_and_now(api)

            for project in api.projects.all():
                process_project(api, debuglog, project)

            if len(api.queue):
                debuglog.log('changes queued for sync: %s'% str(api.queue))
                if args.execute:
                    logging.debug('Commiting to Todoist.')
                    api.commit()
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
    props.tree_active = props.is_parallel or props.is_serial
    props.is_recurring = None
    props.recurring_reactivation_tree = None

    debuglog = parentdebuglog.sublogger('Project: %s' % props)

    # Get all items for the project, sort by the item_order field.
    items = sorted(api.items.all(lambda x: x.data['project_id'] == project.data['id']),
                   key=lambda x: x.data['child_order'])
    
    (completed_items, active_items) = get_top_level_items(items)

    for idx, item in enumerate(completed_items):
        process_completed_item(items, props, debuglog, item, idx)

    for idx, item in enumerate(active_items):
        process_active_item(items, props, debuglog, item, idx, idx + len(completed_items))

def process_completed_item(items, parentprops, parentdebuglog, item, idx):
    if parentprops.recurring_reactivation_tree:
        uncomplete_item(item, parentdebuglog)
        process_active_item(items, parentprops, parentdebuglog, item, idx, idx)

def process_active_item(items, parentprops, parentdebuglog, item, all_idx, active_idx):
    props = Props(item['content'])
    set_parallel_or_serial(props)

    props.first = all_idx == 0
    props.first_active = active_idx == 0

    (completed_subitems, active_subitems) = get_subitems(items, item)

    props.has_active_subitems = len(active_subitems) > 0

    props.owned = parentprops.owned or props.is_parallel or props.is_serial
    props.is_recurring = is_recurring(item)
    props.is_due = is_due(item)

    # Recurring reactivation: when a recurring parallel or serial task becomes due, all of
    # its subtasks will be uncompleted (re-activated) and the recurring task itself will be
    # completed.
    props.recurring_reactivation_item = props.is_recurring and props.is_due and (
        props.is_parallel or props.is_serial
    )
    props.recurring_reactivation_tree = (
        parentprops.recurring_reactivation_tree or props.recurring_reactivation_item
    )

    props.tree_active = (
        (
            parentprops.tree_active and (
                parentprops.is_parallel or (parentprops.is_serial and props.first)
            )
        )
        or (props.is_parallel or props.is_serial)
    )

    props.active = props.tree_active and not props.has_active_subitems


    debuglog = parentdebuglog.sublogger('Item: %s' % props)

    if props.recurring_reactivation_item:
        complete_item(item, debuglog)

    if props.active:
        activate_item(item, props, debuglog)
    elif props.owned:
        own_item(item, debuglog)

    if item['content'].startswith(LAST_RUN_CONST):
        debuglog.log('## Updating last run timestamp')
        item.update(content = LAST_RUN_CONST + ': %s %s' % (socket.gethostname(), now))

    for idx, item in enumerate(completed_subitems):
        process_completed_item(items, props, debuglog, item, idx)

    for idx, item in enumerate(active_subitems):
        process_active_item(items, props, debuglog, item, idx, idx + len(completed_subitems))


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
            if item['date_completed'] is None:
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
        debuglog.log('## Uncompleting following item & removing due date if needed:')
        item.uncomplete()
        if item['due'] is not None:
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
