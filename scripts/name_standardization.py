from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


APC_CAM_MAPPING = {
    "cam5202": "apc01",
    "cam5203": "apc02",
    "cam6601": "apc03",
    "camccr01": "apc04",
    "cam3001": "apc05",
    "cam1101": "apc06",
    "cam1102": "apc07",
    "cam1201": "apc08",
    "cam1202": "apc09",
    "cam1301": "apc10",
    "cam1302": "apc11",
    "cam5201": "apc12",
    "cam6101": "apc13",
}


@dataclass(frozen=True)
class NameTokens:
    original_stem: str
    normalized_stem: str
    site_token: Optional[str]
    date_token: Optional[str]
    time_token: Optional[str]


def _normalize_delimiters(text: str) -> str:
    cleaned = re.sub(r"[\s\-]+", "_", text.strip())
    return re.sub(r"_+", "_", cleaned).strip("_")


def _normalize_ttc_prefix(stem: str) -> str:
    if re.match(r"(?i)^ttcps", stem):
        return "ttcps" + stem[5:]
    if re.match(r"(?i)^ttc", stem):
        return "ttcps" + stem[3:]
    return stem


def _map_apc_cam_name(stem: str) -> Optional[str]:
    match = re.match(
        r"(?i)^apc_(cam[0-9a-z]+)_(\d{6}|\d{8})_(\d{4}|\d{6})(?:_(\d+))?$",
        stem,
    )
    if not match:
        return None

    cam_id = match.group(1).lower()
    mapped_site = APC_CAM_MAPPING.get(cam_id)
    if not mapped_site:
        return None

    date_token = match.group(2)
    time_token = match.group(3)
    chunk = match.group(4)
    base = f"{mapped_site}_{date_token}_{time_token}"
    return f"{base}_{chunk}" if chunk else base


def _map_cam_to_cgtd(stem: str) -> Optional[str]:
    match = re.match(
        r"(?i)^cam([0-9a-z]+)_(\d{6}|\d{8})_(\d{4}|\d{6})(?:_(.+))?$",
        stem,
    )
    if not match:
        return None

    camera_id = match.group(1).upper()
    date_token = match.group(2)
    time_token = match.group(3)
    suffix = match.group(4)
    base = f"CGTD{camera_id}_{date_token}_{time_token}"
    return f"{base}_{suffix}" if suffix else base


def standardize_dataset_stem(stem: str) -> str:
    normalized = _normalize_delimiters(stem)
    mapped_apc = _map_apc_cam_name(normalized)
    if mapped_apc:
        return mapped_apc

    mapped_cgtd = _map_cam_to_cgtd(normalized)
    if mapped_cgtd:
        return mapped_cgtd

    return _normalize_ttc_prefix(normalized)


def parse_name_tokens(stem: str) -> NameTokens:
    normalized_stem = standardize_dataset_stem(stem)
    parts = [part for part in re.split(r"[_\-\s]+", normalized_stem) if part]
    site_token = parts[0] if parts else None

    date_token = None
    time_token = None
    for index, part in enumerate(parts):
        if not date_token and re.fullmatch(r"\d{6}|\d{8}", part):
            date_token = part
            for candidate in parts[index + 1 :]:
                if re.fullmatch(r"\d{4}|\d{6}", candidate):
                    time_token = candidate
                    break
            continue
        if not time_token and re.fullmatch(r"\d{4}|\d{6}", part):
            time_token = part

    return NameTokens(
        original_stem=stem,
        normalized_stem=normalized_stem,
        site_token=site_token,
        date_token=date_token,
        time_token=time_token,
    )


def normalize_site_tag(site_token: Optional[str]) -> Optional[str]:
    if not site_token:
        return None

    normalized = site_token.strip().lower()
    if not normalized:
        return None

    match = re.match(r"^([a-z]+)", normalized)
    if not match:
        return None

    site_tag = match.group(1)
    return site_tag if len(site_tag) >= 3 else normalized


def standardize_dataset_filename(filename: str) -> str:
    path = Path(filename)
    normalized_stem = standardize_dataset_stem(path.stem)
    return f"{normalized_stem}{path.suffix}"
