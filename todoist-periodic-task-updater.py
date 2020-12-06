#!/usr/bin/env python3

import logging
import argparse
import pytz

# noinspection PyPackageRequirements
from todoist.api import TodoistAPI

import re
import socket
import time
import sys
from datetime import datetime

timezone = None
now = None

LAST_RUN_CONST = '$TodoistUpdaterLastRun$'

def get_subitems(items, parent_item=None, include_completed=False):
    """Search a flat item list for child items."""
    parent_id = None
    if parent_item:
        parent_id = parent_item['id']
    result_items = []
    for item in items:
        if (include_completed or item['date_completed'] is None) and item['parent_id'] == parent_id:
            result_items.append(item)
    return result_items

def main():
    """Main process function."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--api_key', help='Todoist API Key')
    parser.add_argument('-l', '--label', help='The "No Date" label to use', default='NoDate')
    parser.add_argument('--debug', help='Enable debugging', action='store_true')
    parser.add_argument('-p', '--periodical_sync_sec', help='Run the sync periodically', type=int, default=None)
    parser.add_argument('--parallel_suffix', default='(=)')
    parser.add_argument('--serial_suffix', default='(-)')
    parser.add_argument('-x', '--execute', action='store_true', default=False, help='Execute the changes (otherwise just prints them)')
    args = parser.parse_args()

    # Set debug
    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level)

    # Check we have a API key
    if not args.api_key:
        logging.error('No API key set, exiting...')
        sys.exit(1)

    # Run the initial sync
    logging.debug('Connecting to the Todoist API')
    api = TodoistAPI(token=args.api_key)
    logging.debug('Syncing the current state from the API')
    api.sync()

    # Check the NoDate label exists
    labels = api.labels.all(lambda x: x['name'] == args.label)
    if len(labels) > 0:
        nodate_label_id = labels[0]['id']
        logging.debug('Label %s found as label id %d', args.label, nodate_label_id)
    else:
        logging.error("Label %s doesn't exist, please create it.", args.label)
        sys.exit(1)

    def get_project_type(project_object):
        """Identifies how a project should be handled."""
        name = project_object['name'].strip()
        if name.endswith(args.parallel_suffix):
            return 'parallel'
        elif name.endswith(args.serial_suffix):
            return 'serial'

    class ItemMetadata:
        def __init__(self):
            self.type = None
            self.delay = None

    def has_suffix(str, suffix):
        if str.endswith(suffix):
            return (True, str[0:-(len(suffix))])
        else:
            return (False, str)

    def has_delay_suffix(str):
        m = re.match('(.*){(.*?)}', str)
        if m:
            return (m.group(2), m.group(1))
        else:
            return (None, str)

    def parse_item_metadata(item):
        """Identifies how a item with sub items should be handled."""
        name = item['content'].strip()
        metadata = ItemMetadata()
        while True:
            (is_parallel, name) = has_suffix(name, args.parallel_suffix)
            if is_parallel:
                metadata.type = 'parallel'
                continue
            (is_serial, name) = has_suffix(name, args.serial_suffix)
            if is_serial:
                metadata.type = 'serial'
                continue
            (delay_info, name) = has_delay_suffix(name)
            if delay_info is not None:
                metadata.delay = delay_info
                continue
            break
        return metadata

    def add_nodate_label(item):
        if nodate_label_id in item['labels']:
            return
        labels = item['labels']
        logging.debug('Updating %s with "NoDate" label', item['content'])
        labels.append(nodate_label_id)
        item.update(labels=labels)

    def remove_nodate_label(item):
        if not nodate_label_id in item['labels']:
            return
        labels = item['labels']
        logging.debug('Removing "NoDate" label from %s', item['content'])
        labels.remove(nodate_label_id)
        item.update(labels=labels)

    def set_date(item, metadata):
        if item['due'] is None:
            new_due = metadata.delay if metadata.delay is not None else 'today'
            item.update(due={'string' : new_due })
            logging.debug('Setting due date to %s for item %s', new_due, item['content'])

    def parse_due(item):
        due = item['due']
        if due is None: return False
        tz = due['timezone'] if due['timezone'] is not None else timezone

        try:
            due_date = datetime.strptime(due['date'], '%Y-%m-%dT%H:%M:%S')
        except:
            due_date = datetime.strptime(due['date'], '%Y-%m-%d')

        return tz.localize(due_date)

    def is_active(item):
        due = parse_due(item)
        if due is None: return False
        # logging.debug("is_active: due parsed: %s", due)
        return due <= now

    def uncomplete(item):
        if item['date_completed'] is not None:
            logging.debug('Uncompleting task')
            item.uncomplete()
            if item['due'] is not None:
                item.update(due=None)

    def process_item(item, processing_mode, is_first, items):
        """
        processing_mode: 'serial', 'parallel', 'inactive' (inactive part of serial), null (parent does not specify)
        """

        logging.debug('** Processing item: %s, processing_mode: %s, is_first: %s', item['content'], processing_mode, is_first)

        due_obj = item['due']
        is_recurring = due_obj['is_recurring'] if not due_obj is None else False
        is_active_recurring = is_recurring and is_active(item)
        child_items = get_subitems(items, item, include_completed = is_active_recurring)
        item_metadata = parse_item_metadata(item)

        # Fix-recurring task = true is a special case: when a recurring task becomes active,
        # which is neither serial, nor parallel, all of its children should be uncompleted
        # so that the whole tree shows up in Todoist.
        fix_recurring_task = is_active_recurring and item_metadata.type is None

        is_considered_leaf = len(child_items) == 0

        # Defines how the item and it's subtasks (if any) should be processed:
        # * 'activate': make the tree active: put at least one element into the 'Today' view.
        # * 'take': take ownership of the tree: it will be owned by this automation.
        # * <None>: do not change the tree
        tree_prcessing_mode = (
            'activate'
                if (processing_mode == 'serial' and is_first)
                    or processing_mode == 'parallel'
                    or is_active_recurring
            else 'take'
                if processing_mode == 'serial'
                    or processing_mode == 'inactive'
                    or item_metadata.type is not None
            else None)

        # Defines how to process the actual item:
        # * 'activate': make item visible in the 'Today' view
        # * 'take': take ownership of the item: it will be owned by this automation.
        # * <None>: does not change the item
        item_processing_mode = (
            'activate'
                if tree_prcessing_mode == 'activate'
                    and (is_considered_leaf or fix_recurring_task)
            else 'take'
                if tree_prcessing_mode == 'activate' or tree_prcessing_mode == 'take'
            else None)

        # | tree_processing_mode | item_type | child_processing_mode |
        # |----------------------|-----------|-----------------------|
        # | activate             | serial    | serial                |
        # | activate             | parallel  | parallel              |
        # | activate             | <None>    | <None>                |
        # | take                 | serial    | inactive              |
        # | take                 | parallel  | inactive              |
        # | take                 | <None>    | <None>                |
        # | <None>               | serial    | serial                |
        # | <None>               | parallel  | parallel              |
        # | <None>               | <None>    | <None>                |
        # Special case: fix_recurring_task ->  inactive

        child_processing_mode = (
            'inactive' if fix_recurring_task
            else None if item_metadata.type == None
            else 'inactive' if tree_prcessing_mode == 'take'
            else item_metadata.type)

        logging.debug('Is Recurring: (%s, %s), Tree processing mode: %s, child items: %d, item processing mode: %s, Item type: %s, Child processing mode: %s',
            is_recurring, is_active_recurring, tree_prcessing_mode, len(child_items), item_processing_mode, item_metadata.type, child_processing_mode)

        if item_processing_mode == 'activate':
            uncomplete(item)
            set_date(item, item_metadata)
            remove_nodate_label(item)
        elif item_processing_mode == 'take':
            uncomplete(item)
            if item['due'] is None:
                add_nodate_label(item)
            if is_active_recurring:
                logging.debug('Completing recurring task.')
                item.close()

        if item['content'].startswith(LAST_RUN_CONST):
            item.update(content = LAST_RUN_CONST + ': %s %s' % (socket.gethostname(), now))

        for idx, child in enumerate(child_items):
            process_item(child, child_processing_mode, idx == 0, items)

    def process_project(project):
        if project.data['is_archived']:
            logging.debug('****** Project %s is archived, skipping.', project.data['name'])
            return
        project_type = get_project_type(project)
        logging.debug('****** Project %s being processed as %s', project.data['name'], project_type)

        # Get all items for the project, sort by the item_order field.
        items = sorted(api.items.all(lambda x: x.data['project_id'] == project.data['id']), key=lambda x: x.data['child_order'])

        top_level_items = get_subitems(items)

        for idx, item in enumerate(top_level_items):
            process_item(item, project_type, idx == 0, items)

    # Main code
    while True:
        try:
            api.sync()
            timezone = pytz.timezone(api.user.state['user']['tz_info']['timezone'])
            now = datetime.now(tz = timezone)
            logging.debug('Timezone: %s, now: %s', timezone, now)

            for project in api.projects.all():
                process_project(project)

            if len(api.queue):
                logging.debug('changes queued for sync: %s', str(api.queue))
                if args.execute:
                    logging.debug('commiting to Todoist.')
                    api.commit()
            else:
                logging.debug('No changes queued, skipping sync.')
        except Exception as e:
            logging.exception('Error trying to sync with Todoist API: %s' % str(e))

        if args.periodical_sync_sec is None:
            break

        logging.debug('Sleeping for %d seconds', args.periodical_sync_sec)
        time.sleep(args.periodical_sync_sec)



if __name__ == '__main__':
    main()
