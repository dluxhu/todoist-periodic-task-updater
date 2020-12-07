## Remaining before migration

def main():
    """Main process function."""


    def process_item(item, processing_mode, is_first, items):
        """
        processing_mode: 'serial', 'parallel', 'inactive' (inactive part of serial), null (parent does not specify)
        """

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

