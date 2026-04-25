"""Node 2: channels.list로 구독자 수 보강."""
from __future__ import annotations

from video_selection_agent.graph.state import SelectionState
from video_selection_agent.youtube.channel_service import fetch_channel_metadata


def enrich_metadata(state: SelectionState) -> SelectionState:
    candidates = state.get("candidates", [])
    if not candidates:
        trace = list(state.get("trace", []))
        trace.append("enrich_metadata: no candidates — skip")
        return {**state, "trace": trace}

    channel_ids = [c.channel_id for c in candidates if c.channel_id]
    meta = fetch_channel_metadata(channel_ids)

    for c in candidates:
        info = meta.get(c.channel_id)
        if info:
            c.channel_subscriber_count = int(info.get("subscriber_count", 0))
            if info.get("name") and not c.channel_name:
                c.channel_name = info["name"]

    trace = list(state.get("trace", []))
    trace.append(
        f"enrich_metadata: enriched {sum(1 for c in candidates if c.channel_subscriber_count > 0)}/{len(candidates)} channels"
    )
    return {**state, "candidates": candidates, "trace": trace}
