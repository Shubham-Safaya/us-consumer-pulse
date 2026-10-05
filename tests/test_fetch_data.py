"""Offline tests for fetch_data.py. Standard library only:  python -m unittest -v"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fetch_data  # noqa: E402

BLS_SAMPLE = (Path(__file__).parent / "fixtures" / "bls_sample.json").read_bytes()


def fake_urlopen(payload: bytes):
    def _open(req, timeout=30):
        return io.BytesIO(payload)
    return _open


class BlsParsingTests(unittest.TestCase):
    def setUp(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen(BLS_SAMPLE)):
            self.bls = fetch_data.fetch_bls()

    def test_known_series_only(self):
        self.assertEqual(set(self.bls), {"cpi_all", "avg_hourly_earnings", "unemployment_rate"})

    def test_skips_annual_and_missing_and_sorts(self):
        cpi = self.bls["cpi_all"]
        dates = [p["date"] for p in cpi]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(cpi), 23)  # 24 months, one "-" dropped, M13 dropped
        self.assertNotIn(999.0, [p["value"] for p in cpi])


class DerivedSeriesTests(unittest.TestCase):
    def test_yoy(self):
        pts = [{"date": "2024-01", "value": 100.0}, {"date": "2025-01", "value": 103.0},
               {"date": "2025-02", "value": 50.0}]
        self.assertEqual(fetch_data.yoy(pts), [{"date": "2025-01", "value": 3.0}])


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "data" / "data.json"
        self.env = mock.patch.dict(os.environ, {"CENSUS_API_KEY": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_main(self, urlopen):
        with mock.patch.object(fetch_data, "DATA_PATH", self.path), \
             mock.patch("urllib.request.urlopen", urlopen), \
             mock.patch("sys.stdout", io.StringIO()):
            fetch_data.main()
        return json.loads(self.path.read_text())

    def test_writes_series_derived_and_states(self):
        data = self.run_main(fake_urlopen(BLS_SAMPLE))
        derived = data["derived"]
        cpi = {p["date"]: p["value"] for p in derived["inflation_yoy"]}
        wage = {p["date"]: p["value"] for p in derived["wage_growth_yoy"]}
        for p in derived["real_wage_growth"]:
            self.assertAlmostEqual(p["value"], round(wage[p["date"]] - cpi[p["date"]], 2))
        self.assertTrue(derived["real_wage_growth"])
        self.assertEqual(len(data["states"]), len(fetch_data.ACS_2023_SNAPSHOT))
        self.assertEqual(data["states"][0]["population"], 700_000)
        self.assertIn("snapshot", data["states_source"])

    def test_bls_outage_keeps_previous_series(self):
        self.path.parent.mkdir(parents=True)
        previous = {"series": {"cpi_all": [{"date": "2025-01", "value": 1.0}]}, "derived": {"x": []}}
        self.path.write_text(json.dumps(previous))

        def down(req, timeout=30):
            raise OSError("BLS down")

        data = self.run_main(down)
        self.assertEqual(data["series"], previous["series"])
        self.assertEqual(data["derived"], previous["derived"])


class ImportSideEffectTests(unittest.TestCase):
    def test_import_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "fetch_data.py", tmp)
            (Path(tmp) / "data").mkdir()
            (Path(tmp) / "data" / "data.json").write_text("{}")
            subprocess.run([sys.executable, "-c", "import fetch_data"], cwd=tmp, check=True,
                           env={**os.environ, "FRED_API_KEY": ""}, capture_output=True)
            self.assertFalse((Path(tmp) / "data" / "history").exists())


if __name__ == "__main__":
    unittest.main()
