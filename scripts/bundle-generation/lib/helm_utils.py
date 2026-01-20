#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project

"""
Common Helm chart utilities.
"""

import logging


def log_header(message, *args):
    """
    Logs a header message with visual separators and formats the message using multiple arguments.

    Args:
        message (str): The message to be displayed as the header
        *args: Additional arguments to be passed into the message string
    """
    # Format the message with the provided arguments
    formatted_message = message.format(*args)

    # Create a separator line that matches the length of the formatted message
    separator = "=" * len(formatted_message)

    # Log an empty line before the separator and the header
    logging.info("")

    # Log the separator, the formatted message, and the separator again
    logging.info(separator)
    logging.info(formatted_message)
    logging.info(separator)


def split_at(the_str, the_delim, favor_right=True):
    """
    Split a string at a specified delimiter.
    If delimiter doesn't exist, consider the string to be all "left-part" or "right-part" as requested.

    Args:
        the_str (str): The string to split
        the_delim (str): The delimiter to split on
        favor_right (bool, optional): If True and delimiter not found, put everything in right part.
                                     If False, put everything in left part. Defaults to True.

    Returns:
        tuple: (left_part, right_part) where one may be None if delimiter not found
    """
    split_pos = the_str.find(the_delim)
    if split_pos > 0:
        left_part = the_str[0:split_pos]
        right_part = the_str[split_pos+1:]
    else:
        if favor_right:
            left_part = None
            right_part = the_str
        else:
            left_part = the_str
            right_part = None

    return (left_part, right_part)


def insertFlowControlIfAround(lines_list, first_line_index, last_line_index, if_condition):
    """
    Insert Helm flow control (if statement) around a block of lines.

    Args:
        lines_list (list): List of lines to modify
        first_line_index (int): Index of first line to wrap
        last_line_index (int): Index of last line to wrap
        if_condition (str): The condition for the if statement (without {{ }} or if)

    Returns:
        list: Modified list of lines with if/end-if added
    """
    # Get indentation from the first line
    indent = lines_list[first_line_index][:len(lines_list[first_line_index]) - len(lines_list[first_line_index].lstrip())]

    # Insert {{- if condition }} before the first line
    if_line = f"{indent}{{{{- if {if_condition} }}}}\n"
    lines_list.insert(first_line_index, if_line)

    # Insert {{- end }} after the last line (adjust index due to insertion above)
    end_line = f"{indent}{{{{- end }}}}\n"
    lines_list.insert(last_line_index + 2, end_line)

    return lines_list


def escape_template_variables(helmChart, variables):
    """
    Escape Helm template variables so they don't get evaluated during templating.

    This is used when you want to preserve variables like {{ .VARIABLE }} in the output
    instead of having them evaluated.

    Args:
        helmChart (str): Path to the Helm chart
        variables (list): List of variable names to escape

    Returns:
        None: Modifies template files in place
    """
    import os
    import re

    if not variables:
        logging.debug("No variables to escape")
        return

    logging.info(f"Escaping template variables: {variables}")

    templates_path = os.path.join(helmChart, "templates")

    if not os.path.exists(templates_path):
        logging.warning(f"Templates path does not exist: {templates_path}")
        return

    for filename in os.listdir(templates_path):
        if not filename.endswith(".yaml"):
            continue

        file_path = os.path.join(templates_path, filename)

        with open(file_path, 'r') as f:
            content = f.read()

        modified = False
        for var in variables:
            # Pattern to match {{ .VARIABLE }}
            pattern = r'\{\{\s*\.' + re.escape(var) + r'\s*\}\}'
            # Replace with escaped version: {{ "{{ .VARIABLE }}" }}
            replacement = r'{{ "{{' + r' .' + var + r' }}" }}'

            if re.search(pattern, content):
                content = re.sub(pattern, replacement, content)
                modified = True
                logging.debug(f"Escaped variable {var} in {filename}")

        if modified:
            with open(file_path, 'w') as f:
                f.write(content)

    logging.info("Template variables escaped successfully\n")
