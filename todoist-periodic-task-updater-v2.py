#!/usr/bin/env python3

import logging
import argparse
import pytz
import re
import socket
import time
import sys

from datetime import datetime
from todoist.api import TodoistAPI

LAST_RUN_CONST = '$TodoistUpdaterV2LastRun$'

timezone = None
now = None
args = None

def main():
    """Main process function."""

    parse_args()
    set_debug()
    debuglog = DebugLogger()
    api = connect(debuglog)

    while True:
        try:
            api.sync()
            set_timezone_and_now()

            for project in api.projects.all():
                process_project(api, debuglog, project)

        except Exception as e:
            logging.exception('Error trying to sync with Todoist API: %s' % str(e))
        
        if args.periodical_sync_sec is None:
            break;

        logging.debug('Sleeping for %d seconds', args.periodical_sync_sec)
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
    debuglog.debug('Syncing the current state from the API')
    api.sync()

    # Check the NoDate label exists
    labels = api.labels.all(lambda x: x['name'] == args.label)
    if len(labels) > 0:
        nodate_label_id = labels[0]['id']
        debuglog.debug('Label %s found as label id %d' % (args.label, nodate_label_id))
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

def set_timezone_and_now():
    global timezone, now
    timezone = pytz.timezone(api.user.state['user']['tz_info']['timezone'])
    now = datetime.now(tz = timezone)
    logging.debug('Timezone: %s, now: %s', timezone, now)

class Props:
    def __repr__(self):
        return vars(self)

def process_project(api, parentdebuglog, project):
    if project.data['is_archived']:
        parentdebuglog.debug('Project %s is archived, skipping.', project.data['name'])
        return

    props = Props()
    props.name = project['name'].strip()
    set_type_from_name(props)

    debuglog = parentdebuglog.sublogger('Project: %s' % props)

    # Get all items for the project, sort by the item_order field.
    items = sorted(api.items.all(lambda x: x.data['project_id'] == project.data['id']),
                   key=lambda x: x.data['child_order'])
    
    (completed_items, active_items) = get_top_level_items(items)

    for idx, item in enumerate(completed_items):
        process_completed_item(items, props, debuglog, item, idx)

    for idx, item in enumerate(active_items):
        process_active_item(items, props, debuglog, item, idx, idx + len(completed_items))

def set_type_from_name(props):
    props.is_parallel = props.name.endswith(args.parallel_suffix)
    props.is_serial = props.name.endswith(args.serial_suffix)

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

def process_completed_item(items, parentprops, parentdebuglog, item, idx):
    pass

def process_active_item(items, parentprops, parentdebuglog, item, all_idx, active_idx):
    props = Props()
    props.name = item['content']
    props.first = all_idx == 0
    props.first_active = active_idx == 0

    debuglog = parentdebuglog.sublogger('Item: %s' % props)

