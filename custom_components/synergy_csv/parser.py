"""Parse and validate a Synergy Interval Data File.

Pure module: no Home Assistant imports, so it can be tested in isolation.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from .slug import slugify

type Readings = dict[str, dict[datetime, float]]
"""Register slug -> Perth-local naive Interval start -> kWh."""

_REGISTER_HEADER = re.compile(r"^(?P<name>.+?)\s*\((?:kwh|units)\)$", re.IGNORECASE)
_UNIT_SUFFIX = re.compile(r"\([^()]*\)\s*$")
_BILLING_STATUS = "billing status"
_FIRST_COLUMNS = ("date", "time")


class IntervalFileError(ValueError):
    """The file is not a valid Interval Data File; ``line`` is 1-based when known."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(f"Line {line}: {message}" if line else message)
        self.line = line


@dataclass
class ParsedFile:
    """Validated contents of one Interval Data File."""

    names: dict[str, str] = field(default_factory=dict)
    readings: Readings = field(default_factory=dict)
    ignored_columns: list[str] = field(default_factory=list)


def parse_interval_file(text: str) -> ParsedFile:
    """Parse ``text``; raise IntervalFileError on the first problem found."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    while header is not None and not any(cell.strip() for cell in header):
        header = next(reader, None)
    if header is None or [c.strip().lower() for c in header[:2]] != list(_FIRST_COLUMNS):
        raise IntervalFileError("Not a Synergy interval data file")

    parsed = _parse_header(header)
    if not parsed.readings:
        raise IntervalFileError("No energy columns found")
    register_columns = _register_columns(header)

    rows = 0
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        line = reader.line_num
        if len(row) != len(header):
            raise IntervalFileError(f"expected {len(header)} columns", line)
        start = _parse_interval(row[0], row[1], line)
        for index, slug in register_columns.items():
            by_interval = parsed.readings[slug]
            if start in by_interval:
                raise IntervalFileError(f"duplicate interval {start:%d/%m/%Y %H:%M}", line)
            by_interval[start] = _parse_value(row[index], parsed.names[slug], line)
        rows += 1

    if rows == 0:
        raise IntervalFileError("File contains no readings")
    return parsed


def _register_columns(header: list[str]) -> dict[int, str]:
    return {
        index: slugify(match["name"])
        for index, cell in enumerate(header)
        if (match := _REGISTER_HEADER.match(cell.strip()))
    }


def _parse_header(header: list[str]) -> ParsedFile:
    parsed = ParsedFile()
    for cell in header[2:]:
        title = cell.strip()
        if match := _REGISTER_HEADER.match(title):
            name = match["name"].strip()
            slug = slugify(name)
            if not slug or slug in parsed.names:
                raise IntervalFileError(f"Two columns have the same name once normalised: {title}")
            parsed.names[slug] = name
            parsed.readings[slug] = {}
        elif title.lower() != _BILLING_STATUS and _UNIT_SUFFIX.search(title):
            parsed.ignored_columns.append(title)
    return parsed


def _parse_interval(date_text: str, time_text: str, line: int) -> datetime:
    try:
        start = datetime.strptime(f"{date_text.strip()} {time_text.strip()}", "%d/%m/%Y %H:%M")
    except ValueError:
        raise IntervalFileError("invalid date/time", line) from None
    if start.minute not in (0, 30):
        raise IntervalFileError("time is not on a 30-minute boundary", line)
    return start


def _parse_value(text: str, register: str, line: int) -> float:
    try:
        value = float(text)
    except ValueError:
        raise IntervalFileError(f"invalid value for {register}", line) from None
    if not math.isfinite(value) or value < 0:
        raise IntervalFileError(f"invalid value for {register}", line)
    return value
