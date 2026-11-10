"""Scripted stand-ins for the model, one per demo task.

Each script is the list of tool calls a real model would be expected to make.
They let the tests and the dashboard's demo mode run the full agent loop with
no API key. A run that uses one of these is a replay, not a real model result.
"""

from __future__ import annotations

from .llm import ScriptedLLM

MEDIAN_FIX = (
    "    middle = len(ordered) // 2\n    return ordered[middle]",
    "    middle = len(ordered) // 2\n"
    "    if len(ordered) % 2 == 0:\n"
    "        return (ordered[middle - 1] + ordered[middle]) / 2\n"
    "    return ordered[middle]",
)
TRIM_FIX = ("last - first);", "last - first + 1);")
WORDCOUNT_FIX = ("text.split(' ').count()", "text.split_whitespace().count()")
CART_FIX = ("$total += $item[0];", "$total += $item[0] * $item[1];")


def script_for(file: str, old: str, new: str, summary: str) -> list:
    return [
        [("run_tests", {})],
        [("read_file", {"path": file})],
        [("edit_file", {"path": file, "old_text": old, "new_text": new})],
        [("run_tests", {})],
        [("finish", {"summary": summary})],
    ]


DEMO_SCRIPTS: dict[str, list] = {
    "py_stats_median": script_for(
        "stats.py", *MEDIAN_FIX, "Averaged the two middle values."
    ),
    "cpp_strutil_trim": script_for(
        "strutil.cpp", *TRIM_FIX, "Fixed off-by-one in substr length."
    ),
    "rs_wordcount_spaces": script_for(
        "src/lib.rs", *WORDCOUNT_FIX, "Split on any whitespace."
    ),
    "hack_cart_total": script_for(
        "src/cart.hack", *CART_FIX, "Multiplied each price by its quantity."
    ),
}


def scripted_llm(task_name: str) -> ScriptedLLM:
    return ScriptedLLM(DEMO_SCRIPTS[task_name])
