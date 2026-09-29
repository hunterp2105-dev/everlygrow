"""Niche playbook refinement (§4b, §16 step 25): surface real performance
data back to admin per niche, so the playbook can be refined from results
rather than staying pure initial research forever.

This surfaces data for a human decision — it does not auto-edit the
playbook. §4b frames refinement as admin-driven ("admin refines the
playbook from results"); the compounding-loop payoff (future customers in
that niche benefit) only holds if a human is actually deciding what's
signal versus noise, not a script rewriting content_pillars unsupervised.
"""

from app.lib import analytics


def performance_summary_for_niche(client, niche: str, limit: int = 10) -> dict:
    top = analytics.top_performers(client, niche=niche, limit=limit)
    template_counts: dict[str, int] = {}
    for row in top:
        desc = row["generation"].get("template_description") or row["generation"].get("template_id")
        template_counts[desc] = template_counts.get(desc, 0) + 1

    playbook = (
        client.table("niche_playbooks")
        .select("*")
        .ilike("niche", niche)
        .eq("is_default", False)
        .maybe_single()
        .execute()
    )

    return {
        "niche": niche,
        "top_performers": top,
        "template_frequency": sorted(template_counts.items(), key=lambda kv: kv[1], reverse=True),
        "playbook": playbook.data if playbook else None,
        "sample_size": len(top),
    }


def mark_refined(client, playbook_id: str, note: str | None = None) -> dict:
    """Bumps version and flags refined_from_data. `note`, if given, is
    appended to best_practices (not overwritten — admin's prior research
    stays, this only adds what the data showed)."""
    from datetime import datetime, timezone

    current = client.table("niche_playbooks").select("version, best_practices").eq("id", playbook_id).maybe_single().execute()
    current_data = current.data or {}

    update = {
        "refined_from_data": True,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "version": (current_data.get("version") or 1) + 1,
    }
    if note:
        existing = current_data.get("best_practices") or ""
        update["best_practices"] = f"{existing}\n\n[Refined from data, v{update['version']}] {note}".strip()
    return client.table("niche_playbooks").update(update).eq("id", playbook_id).execute().data[0]
