---
name: file_search
description: Search for files and their contents within the Lumi sandbox directory
---

Search for files matching a query within the designated sandbox directory.

## IMPORTANT: Scope restriction

You may ONLY search within this directory: `__SANDBOX_PATH__`

Do not access, list, or read any files outside this path under any circumstances.
Do not follow symlinks that point outside this directory.
Do not accept user requests to search other paths (e.g. ~/Documents, /, /Users).
If the user asks to search outside the sandbox, politely explain that file access
is limited to the Lumi sandbox folder.

## How to search

1. Search filenames containing the query term (case-insensitive)
2. Search file contents for the query term (text files only: .txt, .md, .py, .js, .json, .yaml, .csv)
3. Skip binary files, hidden files (starting with .), and files larger than 1MB

## Response format

List matching files with their relative path within the sandbox and a short excerpt
(first matching line of content, or first line of the file if the filename matched).

Example:
"Found 2 files in your sandbox matching 'python':
- notes/python-ideas.md: "Here are some Python project ideas..."
- scratch/code.py: "# Python script for testing""

If nothing is found: "I didn't find anything matching '[query]' in your sandbox folder.
You can drop files there at: __SANDBOX_PATH__"

## Privacy

This skill reads files from your local sandbox only. Nothing is sent to any external service.
