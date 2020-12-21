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

args = None

def main():
    """Main process function."""

    parse_args()
    if not args.api_key:
        logging.error('No API key set, exiting...')
        sys.exit(1)

    api = TodoistAPI(token=args.api_key)

    api.sync()

    print("Projects: %d, Items: %d" % (len(api.projects.all()), len(api.items.all())))

    for project in api.projects.all():
        print(project)

    for item in api.items.all():
        print(item)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--api_key', help='Todoist API Key')
    parser.add_argument('--debug', help='Enable debugging', action='store_true')
    global args
    args = parser.parse_args()

if __name__ == '__main__':
    main()
