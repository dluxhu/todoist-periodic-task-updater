#!/usr/bin/env python3

import logging
import argparse

# noinspection PyPackageRequirements
from todoist.api import TodoistAPI

import time
import sys
from datetime import datetime


def get_subitems(items, parent_item=None):
    """Search a flat item list for child items."""
    parent_id = None
    if parent_item:
        parent_id = parent_item.data['id']
    result_items = []
    for item in items:
        if item.data['date_completed'] is None and item.data['parent_id'] == parent_id:
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

    def get_item_type(item):
        """Identifies how a item with sub items should be handled."""
        name = item['content'].strip()
        if name.endswith(args.parallel_suffix):
            return 'parallel'
        elif name.endswith(args.serial_suffix):
            return 'serial'

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

    def set_date(item):
        if item.data['due'] is None:
            item.update(due={'string' : 'today'})
            logging.debug('Setting due date to today for item %s', item['content'])

    def remove_date(item):
        if not item.data['due'] is None:
            item.update(due=None)
            logging.debug('Removing due date from item %s', item['content'])

    def process_item(items, item, processing_mode, is_first):
        """
        processing_mode: 'serial', 'parallel', 'inactive' (inactive part of serial), null (parent does not specify)
        """
        # # If its too far in the future, remove the next_action tag and skip
        # if args.hide_future > 0 and 'due_date_utc' in item.data and item['due_date_utc'] is not None:
        #     due_date = datetime.strptime(item['due_date_utc'], '%a %d %b %Y %H:%M:%S +0000')
        #     future_diff = (due_date - datetime.utcnow()).total_seconds()
        #     if future_diff >= (args.hide_future * 86400):
        #         remove_nodate_label(item, label_id)
        #         continue

        logging.debug('** Processing item: %s, processing_mode: %s, is_first: %s', item['content'], processing_mode, is_first)

        child_items = get_subitems(items, item)

        tree_activation_mode = ('activate' if (processing_mode == 'serial' and is_first) or processing_mode == 'parallel' else
            'inactivate' if processing_mode == 'serial' or processing_mode == 'inactive' else None)

        item_type = get_item_type(item)

        is_considered_leaf = len(child_items) == 0 or item_type is None

        item_processing_mode = ('activate' if tree_activation_mode == 'activate' and is_considered_leaf else
            'inactivate' if tree_activation_mode == 'activate' or tree_activation_mode == 'inactivate' else None)

        # | tree_activation_mode | item_type | child_processing_mode |
        # |----------------------|-----------|-----------------------|
        # | activate             | serial    | serial                |
        # | activate             | parallel  | parallel              |
        # | activate             | <None>    | <None>                |
        # | inactivate           | serial    | inactive              |
        # | inactivate           | parallel  | inactive              |
        # | inactivate           | <None>    | <None>                |
        # | <None>               | serial    | serial                |
        # | <None>               | parallel  | parallel              |
        # | <None>               | <None>    | <None>                |

        child_processing_mode = (
            None if item_type == None
            else 'inactive' if tree_activation_mode == 'inactivate'
            else item_type
        )

        logging.debug('Tree activation mode: %s, child items: %d, item processing mode: %s, Item type: %s, Child processing mode: %s',
            tree_activation_mode, len(child_items), item_processing_mode, item_type, child_processing_mode)

        if item_processing_mode == 'activate':
            set_date(item)
            remove_nodate_label(item)
        elif item_processing_mode == 'inactivate':
            add_nodate_label(item)
            remove_date(item)

        for idx, child in enumerate(child_items):
            process_item(items, child, child_processing_mode, idx == 0)


    def process_project(project):
        project_type = get_project_type(project)
        if project_type:
            logging.debug('Project %s being processed as %s', project['name'], project_type)

            # Get all items for the project, sort by the item_order field.
            items = sorted(api.items.all(lambda x: x['project_id'] == project['id']), key=lambda x: x['child_order'])

            top_level_items = get_subitems(items)

            for idx, item in enumerate(top_level_items):
                process_item(items, item, project_type, idx == 0)

    # Main code
    while True:
        try:
            api.sync()
        except Exception as e:
            logging.exception('Error trying to sync with Todoist API: %s' % str(e))
        else:
            for project in api.projects.all():
                process_project(project)

            if len(api.queue):
                logging.debug('changes queued for sync: %s', str(api.queue))
                if args.execute:
                    logging.debug('commiting to Todoist.')
                    api.commit()
            else:
                logging.debug('No changes queued, skipping sync.')

        if args.periodical_sync_sec is None:
            break;

        logging.debug('Sleeping for %d seconds', args.periodical_sync_sec)
        time.sleep(args.periodical_sync_sec)



if __name__ == '__main__':
    main()
