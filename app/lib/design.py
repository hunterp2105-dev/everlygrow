"""Video Design & Graphic Creator module: flyer/ad and standalone-video
request intake. Deliberately reuses Phase 3's generic generation engine
(app/lib/generation.py, app/lib/blotato_client.py) unchanged — the only
new thing here is the module-specific wrapper (what type of deliverable,
which customer, delivery status) and the weekly caps from §7. Kept
functionally separate from the Social module's own video generator via
module_id, a separate request path, and this separate table — not by
duplicating the generation engine.
"""

from datetime import datetime, timedelta, timezone

from app.lib import blotato_client, generation


def categorize_templates(templates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (image_templates, video_templates) for flyer/ad vs.
    standalone-video request intake. Classification itself lives in
    blotato_client.is_video_template — shared with the Social module's
    video-prompt handling so both agree on what counts as a video template."""
    image_templates, video_templates = [], []
    for template in templates:
        if blotato_client.is_video_template(template):
            video_templates.append(template)
        else:
            image_templates.append(template)
    return image_templates, video_templates


def list_design_customers(client) -> list[dict]:
    response = (
        client.table("customer_modules")
        .select("customer_id, enabled, modules!inner(key), customers(id, name)")
        .eq("modules.key", "video_design_graphic_creator")
        .eq("enabled", True)
        .execute()
    )
    return [row["customers"] for row in (response.data or []) if row.get("customers")]


def check_cap_usage(client, customer_id: str, deliverable_type: str, caps: dict) -> dict:
    """§7 weekly caps: flyer/ad deliverables share `design_deliverables_per_week`;
    standalone videos have their own `standalone_videos_per_week`. Soft check
    only — flags usage, does not block (matches the credit-tracker philosophy
    in §10: flag, don't hard-block)."""
    if deliverable_type == "video":
        cap_key, types = "standalone_videos_per_week", ["video"]
    else:
        cap_key, types = "design_deliverables_per_week", ["flyer", "ad"]

    limit = caps.get(cap_key)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    response = (
        client.table("design_deliverables")
        .select("id, type")
        .eq("customer_id", customer_id)
        .in_("type", types)
        .gte("created_at", week_ago)
        .execute()
    )
    used = len(response.data or [])
    return {"used": used, "limit": limit, "within_cap": limit is None or used < limit}


def create_design_request(
    client,
    customer_id: str,
    module_id: str,
    deliverable_type: str,
    occasion: str,
    template_id: str,
    template_description: str,
    prompt: str,
    voice_name: str | None = None,
) -> dict:
    gen = generation.start_generation(
        client,
        customer_id=customer_id,
        module_id=module_id,
        template_id=template_id,
        template_description=template_description,
        prompt=prompt,
        voice_name=voice_name,
    )
    inserted = (
        client.table("design_deliverables")
        .insert(
            {
                "generation_id": gen["id"],
                "customer_id": customer_id,
                "type": deliverable_type,
                "occasion": occasion,
            }
        )
        .execute()
    )
    deliverable = inserted.data[0]
    deliverable["generation"] = gen
    return deliverable


def list_design_requests(client, customer_id: str) -> list[dict]:
    response = (
        client.table("design_deliverables")
        .select("*, generations(*)")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []
