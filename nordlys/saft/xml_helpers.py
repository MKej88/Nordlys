"""Generelle hjelpefunksjoner for håndtering av SAF-T XML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, MutableMapping, Optional, Tuple, cast

__all__ = [
    "NamespaceMap",
    "parse_saft",
    "_clean_text",
    "_find",
    "_findall",
    "_local_name",
]

_NS_FLAG_KEY = "__has_namespace__"
_NS_CACHE_KEY = "__plain_cache__"
_NS_ET_KEY = "__etree_namespace__"

NamespaceCache = Dict[str, Tuple[str, bool]]
NamespaceMap = MutableMapping[str, object]

_PREFIX_PATTERN = re.compile(r"([A-Za-z_][\w.-]*):")


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def parse_saft(path: str | Path) -> Tuple[ET.ElementTree, NamespaceMap]:
    """Leser SAF-T XML og oppdager default namespace dynamisk."""

    xml_path = Path(path)
    tree = cast(ET.ElementTree, ET.parse(xml_path))
    root = tree.getroot()
    if root is None:
        raise ValueError("SAF-T filen mangler et rot-element.")
    namespace: NamespaceMap = {"n1": ""}
    has_namespace = False
    if root.tag.startswith("{") and "}" in root.tag:
        uri = root.tag.split("}", 1)[0][1:]
        namespace["n1"] = uri
        has_namespace = bool(uri)
    else:
        namespace.pop("n1")

    namespace[_NS_FLAG_KEY] = has_namespace
    namespace[_NS_CACHE_KEY] = {}
    return tree, namespace


def _has_namespace(ns: NamespaceMap) -> bool:
    flag = ns.get(_NS_FLAG_KEY)
    if isinstance(flag, bool):
        return flag
    return bool({k: v for k, v in ns.items() if k not in {_NS_FLAG_KEY, _NS_CACHE_KEY}})


def _et_namespace(ns: NamespaceMap) -> Dict[str, str]:
    cached_obj = ns.get(_NS_ET_KEY)
    if isinstance(cached_obj, dict):
        cached = cast(Dict[str, str], cached_obj)
        return cached

    namespace: Dict[str, str] = {}
    for key, value in ns.items():
        if key in {_NS_FLAG_KEY, _NS_CACHE_KEY, _NS_ET_KEY}:
            continue
        if isinstance(key, str) and isinstance(value, str):
            namespace[key] = value

    ns[_NS_ET_KEY] = namespace
    return namespace


def _normalize_path(path: str, ns: NamespaceMap) -> Tuple[str, bool]:
    cache_obj = ns.get(_NS_CACHE_KEY)
    cache: Optional[NamespaceCache]
    if isinstance(cache_obj, dict):
        cache = cast(NamespaceCache, cache_obj)
    else:
        cache = None
    if cache is not None:
        cached = cache.get(path)
        if cached is not None:
            return cached

    has_namespace = _has_namespace(ns)

    if not has_namespace:
        normalized = path.replace("n1:", "")
        result = (normalized, False)
    else:
        replacements: list[Tuple[str, str]] = []
        known_prefixes = set()
        for key, value in ns.items():
            if key in {_NS_FLAG_KEY, _NS_CACHE_KEY, _NS_ET_KEY}:
                continue
            if isinstance(key, str) and isinstance(value, str) and value:
                replacements.append((f"{key}:", f"{{{value}}}"))
                known_prefixes.add(key)

        if not replacements:
            result = (path, True)
        else:
            normalized = path
            needs_mapping = False
            for prefix, replacement in replacements:
                if prefix in normalized:
                    normalized = normalized.replace(prefix, replacement)
            for prefix, _ in replacements:
                if prefix in normalized:
                    needs_mapping = True
                    break

            if not needs_mapping:
                for match in _PREFIX_PATTERN.finditer(path):
                    candidate = match.group(1)
                    if candidate not in known_prefixes:
                        needs_mapping = True
                        break
            result = (normalized, needs_mapping)

    if cache is not None:
        cache[path] = result
    else:
        ns[_NS_CACHE_KEY] = {path: result}

    return result


def _find(element: ET.Element, path: str, ns: NamespaceMap) -> Optional[ET.Element]:
    normalized, needs_mapping = _normalize_path(path, ns)
    if needs_mapping:
        return element.find(normalized, _et_namespace(ns))
    return element.find(normalized)


def _findall(element: ET.Element, path: str, ns: NamespaceMap) -> Iterable[ET.Element]:
    normalized, needs_mapping = _normalize_path(path, ns)
    if needs_mapping:
        return element.findall(normalized, _et_namespace(ns))
    return element.findall(normalized)
