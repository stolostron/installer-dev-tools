#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

# Parse an image reference, return dict containing image reference information
def parse_image_ref(image_ref):
   # Image ref:  [registry-and-ns/]repository-name[:tag][@digest]
   parsed_ref = dict()

   remaining_ref = image_ref
   at_pos = remaining_ref.rfind("@")
   if at_pos > 0:
      parsed_ref["digest"] = remaining_ref[at_pos+1:]
      remaining_ref = remaining_ref[0:at_pos]
   else:
      parsed_ref["digest"] = None

   colon_pos = remaining_ref.rfind(":")
   if colon_pos > 0:
      parsed_ref["tag"] = remaining_ref[colon_pos+1:]
      remaining_ref = remaining_ref[0:colon_pos]
   else:
      parsed_ref["tag"] = None

   slash_pos = remaining_ref.rfind("/")
   if slash_pos > 0:
      parsed_ref["repository"] = remaining_ref[slash_pos+1:]
      rgy_and_ns = remaining_ref[0:slash_pos]
   else:
      parsed_ref["repository"] = remaining_ref
      rgy_and_ns = "localhost"

   parsed_ref["registry_and_namespace"] = rgy_and_ns

   rgy, ns = split_at(rgy_and_ns, "/", favor_right=False)
   if not ns:
      ns = ""

   parsed_ref["registry"] = rgy
   parsed_ref["namespace"] = ns

   slash_pos = image_ref.rfind("/")
   if slash_pos > 0:
      repo_and_suffix = image_ref[slash_pos+1:]
   else:
      repo_and_suffix = image_ref

   parsed_ref["repository_and_suffix"]  = repo_and_suffix
   return parsed_ref

def split_at(str, delim, favor_right=True):
    """
    Splits a string at the first occurrence of a specified delimiter.

    Parameters:
    str (str): The string to be split.
    delim (str): The delimiter to split the string at.
    favor_right (bool): If True, the string after the delimiter is considered the "right part".
                        If False, the string before the delimiter is considered the "left part".

    Returns:
    tuple: A tuple (left_part, right_part), where:
        - left_part is the part of the string before the delimiter.
        - right_part is the part of the string after the delimiter.
        If the delimiter doesn't exist, the entire string is assigned to either the left or right part,
        depending on the value of `favor_right`.
    """
    split_pos = str.find(delim)

    if split_pos > 0:
        left_part  = str[0:split_pos]
        right_part = str[split_pos+1:]

    else:
        left_part = None if favor_right else str
        right_part = str if favor_right else None

    return left_part, right_part
