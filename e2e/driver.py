"""Drive a running Home Assistant through the Synergy CSV integration, end to end.

Expected statistics are computed here from the CSV files with the stdlib only,
independently of the integration's own code.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp

FIXTURES = Path("/repo/tests/fixtures")
PERTH = ZoneInfo("Australia/Perth")
CLIENT_ID = "http://synergy-e2e/"
ANYTIME = "synergy_csv:e2e_anytime"
EXPORT = "synergy_csv:e2e_solar_export"


def read_csv(name: str) -> dict[str, dict[datetime, float]]:
    """{statistic suffix: {interval start (Perth-aware): kWh}}"""
    out: dict[str, dict[datetime, float]] = {"anytime": {}, "solar_export": {}}
    with (FIXTURES / name).open(newline="") as handle:
        for row in csv.DictReader(handle):
            start = datetime.strptime(f"{row['Date']} {row['Time']}", "%d/%m/%Y %H:%M")
            start = start.replace(tzinfo=PERTH)
            out["anytime"][start] = float(row["ANYTIME (KWH)"])
            out["solar_export"][start] = float(row["Solar export (Units)"])
    return out


def expected_sums(*files: str) -> dict[str, list[float]]:
    """Merge files (later wins), then cumulative sum per UTC hour."""
    merged: dict[str, dict[datetime, float]] = defaultdict(dict)
    for name in files:
        for key, readings in read_csv(name).items():
            merged[key].update(readings)
    result = {}
    for key, readings in merged.items():
        hourly: dict[datetime, float] = defaultdict(float)
        for start, value in readings.items():
            hourly[start.astimezone(UTC).replace(minute=0)] += value
        total, sums = 0.0, []
        for hour in sorted(hourly):
            total += hourly[hour]
            sums.append(round(total, 6))
        result[key] = sums
    return result


class Hass:
    def __init__(self, base: str, session: aiohttp.ClientSession) -> None:
        self.base, self.session, self.token = base, session, ""
        self.entry_id = ""
        self._ws_id = 0

    async def wait_ready(self) -> None:
        for _ in range(180):
            try:
                async with self.session.get(f"{self.base}/api/onboarding") as resp:
                    if resp.status == 200:
                        return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(2)
        raise SystemExit("Home Assistant did not become ready")

    async def onboard(self) -> None:
        async with self.session.post(
            f"{self.base}/api/onboarding/users",
            json={
                "client_id": CLIENT_ID,
                "name": "E2E",
                "username": "e2e",
                "password": "e2e-password-1",
                "language": "en",
            },
        ) as resp:
            assert resp.status == 200, await resp.text()
            code = (await resp.json())["auth_code"]
        async with self.session.post(
            f"{self.base}/auth/token",
            data={"grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID},
        ) as resp:
            assert resp.status == 200, await resp.text()
            self.token = (await resp.json())["access_token"]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def post(self, path: str, body: dict | None = None) -> dict:
        async with self.session.post(f"{self.base}{path}", json=body, headers=self.headers) as resp:
            assert resp.status == 200, f"{path}: {resp.status} {await resp.text()}"
            return await resp.json()

    async def upload_file(self, name: str) -> dict:
        """Upload through the options flow; returns the flow step after the file."""
        flow = await self.post(
            "/api/config/config_entries/options/flow", {"handler": self.entry_id}
        )
        assert flow["type"] == "menu", flow
        flow = await self.post(
            f"/api/config/config_entries/options/flow/{flow['flow_id']}",
            {"next_step_id": "upload"},
        )
        assert flow["step_id"] == "upload", flow
        form = aiohttp.FormData()
        form.add_field(
            "file", (FIXTURES / name).read_bytes(), filename=name, content_type="text/csv"
        )
        async with self.session.post(
            f"{self.base}/api/file_upload", data=form, headers=self.headers
        ) as resp:
            assert resp.status == 200, await resp.text()
            file_id = (await resp.json())["file_id"]
        step = await self.post(
            f"/api/config/config_entries/options/flow/{flow['flow_id']}", {"file": file_id}
        )
        step["_flow_id"] = flow["flow_id"]
        return step

    async def finish_upload(self, step: dict) -> None:
        assert step["step_id"] == "summary", step
        done = await self.post(f"/api/config/config_entries/options/flow/{step['_flow_id']}", {})
        assert done["type"] == "create_entry", done

    async def ws(self, *commands: dict) -> list[dict]:
        async with self.session.ws_connect(f"{self.base}/api/websocket") as sock:
            assert (await sock.receive_json())["type"] == "auth_required"
            await sock.send_json({"type": "auth", "access_token": self.token})
            assert (await sock.receive_json())["type"] == "auth_ok"
            results = []
            for command in commands:
                self._ws_id += 1
                await sock.send_json({**command, "id": self._ws_id})
                reply = await sock.receive_json()
                assert reply["success"], reply
                results.append(reply["result"])
            return results

    async def sums(self, statistic_id: str) -> list[float]:
        (result,) = await self.ws(
            {
                "type": "recorder/statistics_during_period",
                "start_time": "2000-01-01T00:00:00+00:00",
                "statistic_ids": [statistic_id],
                "period": "hour",
                "types": ["sum"],
            }
        )
        return [row["sum"] for row in result.get(statistic_id, [])]

    async def wait_for_sums(self, statistic_id: str, expected: list[float]) -> None:
        for _ in range(60):
            actual = await self.sums(statistic_id)
            if actual == expected:
                return
            await asyncio.sleep(1)
        raise AssertionError(
            f"{statistic_id}: expected {len(expected)} points ending {expected[-3:]}, "
            f"got {len(actual)} ending {actual[-3:]}"
        )

    async def statistic_ids(self) -> dict[str, dict]:
        (result,) = await self.ws({"type": "recorder/list_statistic_ids"})
        return {item["statistic_id"]: item for item in result}


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


async def main(base: str) -> None:
    async with aiohttp.ClientSession() as session:
        hass = Hass(base, session)
        step("waiting for Home Assistant")
        await hass.wait_ready()
        await hass.onboard()

        step("adding a Meter named 'E2E'")
        flow = await hass.post("/api/config/config_entries/flow", {"handler": "synergy_csv"})
        assert flow["type"] == "form" and flow["step_id"] == "user", flow
        done = await hass.post(
            f"/api/config/config_entries/flow/{flow['flow_id']}", {"meter_name": "E2E"}
        )
        assert done["type"] == "create_entry", done
        hass.entry_id = done["result"]["entry_id"]

        step("rejecting an invalid file")
        bad = await hass.upload_file("invalid_negative.csv")
        assert bad["step_id"] == "upload" and bad["errors"] == {"base": "invalid_file"}, bad
        assert "Line 2" in bad["description_placeholders"]["error"], bad
        assert await hass.sums(ANYTIME) == []

        step("uploading summer_2w.csv")
        summary = await hass.upload_file("summer_2w.csv")
        assert "1,344 new, 0 replaced" in summary["description_placeholders"]["summary"]
        await hass.finish_upload(summary)
        expected = expected_sums("summer_2w.csv")
        await hass.wait_for_sums(ANYTIME, expected["anytime"])
        await hass.wait_for_sums(EXPORT, expected["solar_export"])

        step("checking statistic metadata")
        ids = await hass.statistic_ids()
        assert ids[ANYTIME]["statistics_unit_of_measurement"] == "kWh", ids[ANYTIME]
        assert ids[ANYTIME]["has_sum"] is True and ids[ANYTIME]["source"] == "synergy_csv"
        assert ids[ANYTIME]["name"] == "E2E ANYTIME", ids[ANYTIME]

        step("uploading overlap.csv (newest wins, history extends)")
        summary = await hass.upload_file("overlap.csv")
        assert "672 new, 672 replaced" in summary["description_placeholders"]["summary"]
        await hass.finish_upload(summary)
        expected = expected_sums("summer_2w.csv", "overlap.csv")
        await hass.wait_for_sums(ANYTIME, expected["anytime"])

        step("uploading winter_2w.csv (out of order, earlier-in-year data arrives later)")
        await hass.finish_upload(await hass.upload_file("winter_2w.csv"))
        expected = expected_sums("summer_2w.csv", "overlap.csv", "winter_2w.csv")
        await hass.wait_for_sums(ANYTIME, expected["anytime"])
        await hass.wait_for_sums(EXPORT, expected["solar_export"])

        step("re-uploading winter_2w.csv changes nothing")
        again = await hass.upload_file("winter_2w.csv")
        assert "0 new, 1,344 replaced" in again["description_placeholders"]["summary"], again
        await hass.finish_upload(again)
        await hass.wait_for_sums(ANYTIME, expected["anytime"])

        step("deleting all data")
        flow = await hass.post(
            "/api/config/config_entries/options/flow", {"handler": hass.entry_id}
        )
        flow = await hass.post(
            f"/api/config/config_entries/options/flow/{flow['flow_id']}",
            {"next_step_id": "delete"},
        )
        assert flow["step_id"] == "delete", flow
        done = await hass.post(f"/api/config/config_entries/options/flow/{flow['flow_id']}", {})
        assert done["type"] == "create_entry", done
        await hass.wait_for_sums(ANYTIME, [])
        assert ANYTIME not in await hass.statistic_ids()

        step("removing the Meter")
        async with session.delete(
            f"{base}/api/config/config_entries/entry/{hass.entry_id}", headers=hass.headers
        ) as resp:
            assert resp.status == 200, await resp.text()
        entries = await hass.ws({"type": "config_entries/get", "domain": "synergy_csv"})
        assert entries[0] == [], entries

        print("E2E PASSED")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
