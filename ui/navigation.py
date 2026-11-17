"""Which results section is on screen: the three groups, their sections, and how a click is told apart from a jump.

`result_tab` (session state) is the one source of truth for the section on screen. Two kinds of change reach it:
  * a click on the group control or on a section pill, and
  * a jump from code (a "See all gaps" button, a test setting it directly).
Both controls keep their own value between runs, so the script cannot tell the two apart by looking at the controls alone.
It remembers what it last put in them (`synced`); a control that holds something else was clicked.

The controls must keep the SAME key from one run to the next. When the key changed with every click, the browser's next click
went to a widget the new run no longer drew and was silently dropped.
"""
from __future__ import annotations

TAB_GROUPS = {
    "Results": ["Overview", "Gaps", "Proposals"],
    "Evidence": ["Evidence", "References", "Graph", "Wiki"],
    "Audit": ["Lab", "Trace", "Export"],
}
GROUP_NOTES = {
    "Results": "What the run found: the summary, the research gaps, and the proposals that follow from them.",
    "Evidence": "What the findings rest on: the quotes, the cited references, the knowledge graph and the wiki pages.",
    "Audit": "For review and handover: model comparison, the stage trace, and the report and file exports.",
}
ALL_TABS = [t for tabs in TAB_GROUPS.values() for t in tabs]
DEFAULT_TAB = "Overview"


def valid_tab(tab) -> str:
    return tab if tab in ALL_TABS else DEFAULT_TAB


def group_of(tab: str) -> str:
    return next(g for g, tabs in TAB_GROUPS.items() if tab in tabs)


def adopt_click(current_tab: str, widget_group, widget_tab, synced_group, synced_tab) -> str:
    """The section to show this run.

    `widget_group` / `widget_tab` are what the group control and the section pills hold now; `synced_group` / `synced_tab` are what
    the script put in them at the end of the last run. A value that differs from the synced one was clicked, and wins.
    A control that still holds its synced value did not change, so a jump that moved `current_tab` is kept.
    """
    group = group_of(current_tab)
    if widget_group in TAB_GROUPS and widget_group != synced_group and widget_group != group:
        return TAB_GROUPS[widget_group][0]                    # a click on another group opens that group's first section
    # A pill row only counts if it was the one on screen last run: a row for a group we are jumping INTO may still hold an old value.
    if synced_group == group and widget_tab in TAB_GROUPS[group] and widget_tab != synced_tab and widget_tab != current_tab:
        return widget_tab                                     # a click on a section pill
    return current_tab
