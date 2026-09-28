---
name: repo-locator
description: Find Python source functions, async functions, classes, and nearby tests relevant to a repository issue. Use when the issue does not give a clear file or an initial exact search did not locate it.
---
Call run_skill_script with skill_name="repo-locator", file_path="scripts/locate.py",
and args={"query": "the issue title and relevant behavior, identifiers, errors", "top": "6"}.
Keep concrete issue details; omit template checklists. The workspace defaults to /workspace.

This script reads current Python files without importing or executing them. It returns
ranked source locations with line-numbered excerpts and separate related test paths.
Read the most relevant function and its callers before editing. Scores are retrieval
hints, not proof that a file must change. Results do not cover non-Python files, newly
requested files, or all parts of very long functions. Use targeted text search for
those cases or when scan_limited is true. Avoid repeatedly rerunning the same query.
If the script is unavailable or fails, continue with ordinary source searches.
