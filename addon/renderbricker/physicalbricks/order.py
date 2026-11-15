# SPDX-License-Identifier: GPL-3.0-or-later
"""A tree reads from left to right. Its steps are numbered frames in the order of the flow, 40 apart; a frame carries
no label, its title is the first line of its text. Frames that share a place in the row stand one below the other (a
stack) and are equally wide; every stack starts at the same top and ends at the same bottom. Inside a frame a node's
column is the longest chain of nodes of that frame that feeds it; then, from the right, every node that feeds a node
of its frame moves into the column directly left of the leftmost node it feeds. In a group every input fed by a group
input or a panel value has a small Group Input of its own, and that is a node like any other for these rules – so the
group inputs of a node stand in the column directly left of it. Inside a column the nodes stand top to bottom in the
order of what they feed: first by the place of the nearest node they feed (its frame, its column, its row), then by
that node's socket from the top; a node that feeds nothing to its right comes last, and equal ones keep the order in
which they were made. Every node of a column is as wide as its widest node; columns are 40 apart, the nodes of a
column 40 apart (two group inputs 12), a frame's margin is at least 30, and a frame wider than its columns holds them
in its middle. The columns' edges and tops, the nodes' widths and the frames' edges lie on Blender's grid of 20. No
room is kept for links and no reroute is laid.

Pure Python (no bpy, no import): a node is anything with `name` and `inputs`, an input anything with `identifier`, a
link anything with `from_node`, `to_node`, `to_socket`; nodes are told apart by `name`.

    NODE_GAP, COLUMN_GAP, FRAME_GAP   the nodes of a column, the columns, the frames: 40, 40, 40 apart (FRAME_GAP 30
                             until part 4c's ruling G1, task 7g: 30 lies off the grid)
    columns(members, links) -> list[list]   the columns of one frame, left to right, each in the order of members
    rows(plan, links)        sorts every column of plan (frames in the order of the flow, each as its columns) in
                             place, top to bottom by the nearest node each node feeds"""

NODE_GAP = 40
COLUMN_GAP = 40
FRAME_GAP = 40


def columns(members, links):
    """The columns of one frame, left to right, each in the order of `members`. Only links between two members count.
    A member's column is the longest chain of members that feeds it (0 without one); then, from the highest column
    down, every member that feeds a member moves into the column one left of its leftmost consumer. A cycle among the
    links does not raise: the longest chains are counted in topological order, so the links of a cycle add nothing
    past it. Columns left empty are dropped."""
    names = [node.name for node in members]
    index = {name: i for i, name in enumerate(names)}
    consumers = {name: [] for name in names}
    feeders = {name: 0 for name in names}
    for link in links:
        a, b = link.from_node.name, link.to_node.name
        if a in index and b in index and a != b and b not in consumers[a]:
            consumers[a].append(b)
            feeders[b] += 1
    column = {name: 0 for name in names}
    ready = [name for name in names if feeders[name] == 0]
    while ready:
        name = ready.pop(0)
        for b in consumers[name]:
            column[b] = max(column[b], column[name] + 1)
            feeders[b] -= 1
            if feeders[b] == 0:
                ready.append(b)
    for name in sorted(names, key=lambda name: (-column[name], index[name])):
        if consumers[name]:
            column[name] = min(column[b] for b in consumers[name]) - 1
    found = sorted(set(column.values()))
    result = [[] for _ in found]
    place = {value: i for i, value in enumerate(found)}
    for node in members:
        result[place[column[node.name]]].append(node)
    return result


def rows(plan, links):
    """Sorts every column of `plan` in place. The frames from the last to the first, each frame's columns from the last
    to the first: a node's key is the smallest (rank of the consumer, index of the fed socket in the consumer's inputs)
    over its links into nodes that have a rank - rank = (frame, column, row) - a node without such a link sorts after
    those with one; the sort is stable. After a column is sorted its nodes get their ranks."""
    out = {}
    for link in links:
        out.setdefault(link.from_node.name, []).append(link)
    rank = {}
    for f in range(len(plan) - 1, -1, -1):
        for c in range(len(plan[f]) - 1, -1, -1):
            column = plan[f][c]
            column[:] = sorted(column, key=lambda node: _key(out.get(node.name, ()), rank))
            for r, node in enumerate(column):
                rank[node.name] = (f, c, r)


def _key(links, rank):
    """(0, (rank, socket index)) of the nearest ranked consumer among `links`; (1,) when none of them has a rank."""
    best = None
    for link in links:
        place = rank.get(link.to_node.name)
        if place is not None:
            found = (place, _socket_index(link.to_node, link.to_socket))
            if best is None or found < best:
                best = found
    return (0, best) if best is not None else (1,)


def _socket_index(node, socket):
    """The index of `socket` in the node's inputs, by identifier; past the last input when it is not among them."""
    for i, candidate in enumerate(node.inputs):
        if candidate.identifier == socket.identifier:
            return i
    return len(node.inputs)
