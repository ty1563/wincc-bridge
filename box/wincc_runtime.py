"""Read-only WinCC Runtime tag discovery and value sampling.

The public helpers in this module deliberately accept an injected API object so
the selection and payload logic can be tested without WinCC or 32-bit Python.
"""
import ntpath
import re


NUMERIC_TYPE_CODES = frozenset(range(1, 10))

_VALUABLE_TOKEN = re.compile(
    r"(?:^|[^a-z0-9])(?:"
    r"n(?:p|q|pf|f|u(?:12|23|31|1n|2n|3n)|i[123]|eng|gv)|"
    r"i(?:a|b|c|tb|[123])|u(?:ab|bc|ca|ptb|12|23|31)|"
    r"p|q|f|kw|kvar|kva|kwh|kvah|hz|pf|freq(?:uency)?|"
    r"temp(?:erature)?|spd|speed|eng|gv|guide|flow|level|pressure|"
    r"vibration|bearing|winding|oil|water|rain|alarm|trip|status"
    r")(?:$|[^a-z0-9])",
    re.IGNORECASE,
)


def _candidate_score(name):
    # WinCC projects commonly use camel-case fragments such as BearingTemp.
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    return len(_VALUABLE_TOKEN.findall(normalized))


def select_candidate_tags(tags, limit=512):
    """Return likely operational tags, highest-signal names first."""
    ranked = []
    for tag in tags:
        score = _candidate_score(tag.get("name", ""))
        if score:
            ranked.append((-score, str(tag.get("name", "")).lower(), tag))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:max(0, int(limit))]]


def build_probe(api, inventory_limit=4000, candidate_limit=512):
    """Build a bounded JSON-safe diagnostic payload from a WinCC API adapter."""
    try:
        project = api.runtime_project()
        tags = list(api.enumerate_tags(project))
        inventory_cap = max(0, int(inventory_limit))
        result = {
            "available": True,
            "backend": "wincc-apicf",
            "project": ntpath.basename(project),
            "total_tags": len(tags),
            "inventory": [
                {"id": int(tag.get("id", 0)), "name": str(tag.get("name", ""))}
                for tag in tags[:inventory_cap]
            ],
            "inventory_truncated": len(tags) > inventory_cap,
            "candidates": [],
        }
        for tag in select_candidate_tags(tags, candidate_limit):
            name = str(tag.get("name", ""))
            item = {"id": int(tag.get("id", 0)), "name": name}
            try:
                type_info = api.tag_type(project, tag)
                type_code = int(type_info.get("code", 0))
                item.update({
                    "type_code": type_code,
                    "type_name": str(type_info.get("name", "")),
                    "type_size": int(type_info.get("size", 0)),
                })
                if type_code in NUMERIC_TYPE_CODES:
                    item.update(api.read_numeric(name, type_code))
            except Exception as exc:
                item["error"] = str(exc)[:200]
            result["candidates"].append(item)
        return result
    except Exception as exc:
        return {
            "available": False,
            "backend": "wincc-apicf",
            "error": str(exc)[:300],
        }
