import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
from types import SimpleNamespace
from datetime import datetime, timezone as datetime_timezone
from unittest import mock
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from futu import RET_OK

from formula_editor.models import Formula
from .views import bar_rows


class LocalDatabaseBackupCommandTests(SimpleTestCase):
    def create_temp_database(self, path):
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            connection.execute("INSERT INTO sample (value) VALUES (?)", ("temporary-test-value",))
            connection.commit()
        finally:
            connection.close()

    def run_backup(self, database_path, backup_directory, keep=None):
        output = io.StringIO()
        database_settings = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(database_path),
            }
        }
        environment = {"HUNTALPHA_LOCAL_BACKUP_DIR": str(backup_directory)}
        with override_settings(DATABASES=database_settings), mock.patch.dict(os.environ, environment, clear=False):
            arguments = {"stdout": output}
            if keep is not None:
                arguments["keep"] = keep
            call_command("backup_local_db", **arguments)
        return output.getvalue()

    def test_creates_consistent_backup_with_hash_and_integrity_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "input.sqlite3"
            backup_directory = root / "backups"
            self.create_temp_database(database_path)

            output = self.run_backup(database_path, backup_directory)
            backups = list(backup_directory.glob("huntalpha-local-db-*.sqlite3"))

            self.assertEqual(len(backups), 1)
            backup = backups[0]
            digest = hashlib.sha256(backup.read_bytes()).hexdigest()
            self.assertIn(f"path: {backup}", output)
            self.assertIn(f"size: {backup.stat().st_size}", output)
            self.assertIn(f"sha256: {digest}", output)
            self.assertIn("integrity_check: ok", output)
            self.assertNotIn("temporary-test-value", output)
            connection = sqlite3.connect(str(backup))
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                connection.close()

    def test_rejects_backup_directory_inside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "input.sqlite3"
            self.create_temp_database(database_path)
            target = Path(settings.BASE_DIR) / f".task002-rejected-{os.getpid()}"
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(database_path)}}), mock.patch.dict(
                os.environ, {"HUNTALPHA_LOCAL_BACKUP_DIR": str(target)}, clear=False
            ):
                with self.assertRaises(CommandError):
                    call_command("backup_local_db", stdout=io.StringIO())
            self.assertFalse(target.exists())

    def test_does_not_overwrite_existing_timestamped_backup(self):
        fixed_time = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=datetime_timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "input.sqlite3"
            backup_directory = root / "backups"
            self.create_temp_database(database_path)
            with mock.patch("core.management.commands.backup_local_db.timezone.now", return_value=fixed_time):
                self.run_backup(database_path, backup_directory)
                backup = next(backup_directory.glob("huntalpha-local-db-*.sqlite3"))
                original = backup.read_bytes()
                with self.assertRaises(CommandError):
                    self.run_backup(database_path, backup_directory)
                self.assertEqual(backup.read_bytes(), original)

    def test_retention_only_removes_matching_automatic_backups(self):
        fixed_time = datetime(2030, 1, 1, 0, 0, 0, tzinfo=datetime_timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "input.sqlite3"
            backup_directory = root / "backups"
            backup_directory.mkdir()
            self.create_temp_database(database_path)
            old_names = [
                "huntalpha-local-db-20200101-000000-000000.sqlite3",
                "huntalpha-local-db-20210101-000000-000000.sqlite3",
                "huntalpha-local-db-20220101-000000-000000.sqlite3",
            ]
            for name in old_names:
                (backup_directory / name).write_bytes(b"old automatic backup")
            unknown = backup_directory / "manual-recovery.sqlite3"
            unknown.write_bytes(b"keep this unknown file")

            with mock.patch("core.management.commands.backup_local_db.timezone.now", return_value=fixed_time):
                self.run_backup(database_path, backup_directory, keep=2)

            self.assertFalse((backup_directory / old_names[0]).exists())
            self.assertFalse((backup_directory / old_names[1]).exists())
            self.assertTrue((backup_directory / old_names[2]).exists())
            self.assertTrue(unknown.exists())
            self.assertEqual(len(list(backup_directory.glob("huntalpha-local-db-*.sqlite3"))), 2)

    def test_non_sqlite_configuration_is_rejected_without_creating_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup_directory = Path(temporary) / "backups"
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "not-used"}}), mock.patch.dict(
                os.environ, {"HUNTALPHA_LOCAL_BACKUP_DIR": str(backup_directory)}, clear=False
            ):
                with self.assertRaises(CommandError):
                    call_command("backup_local_db", stdout=io.StringIO())
            self.assertFalse(backup_directory.exists())

    def test_failed_source_does_not_leave_a_pseudo_success_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "invalid.sqlite3"
            backup_directory = root / "backups"
            database_path.write_bytes(b"not a sqlite database")
            with self.assertRaises(CommandError):
                self.run_backup(database_path, backup_directory)
            self.assertEqual(list(backup_directory.glob("huntalpha-local-db-*.sqlite3")), [])
            self.assertEqual(list(backup_directory.glob("*.tmp")), [])


class AuthenticationApiTests(TestCase):
    def test_terminal_data_requires_an_authenticated_session(self):
        response = self.client.get('/api/indicators/')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()['authenticated'])

    def test_email_registration_creates_a_session(self):
        response = self.client.post(
            '/api/auth/register/',
            data=json.dumps({'email': 'researcher@example.com', 'password': 'A-safe-password-42'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['user']['email'], 'researcher@example.com')
        self.assertEqual(self.client.get('/api/auth/session/').status_code, 200)

    def test_guest_session_can_see_common_indicators_only(self):
        response = self.client.post('/api/auth/guest/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['visitor'])
        indicators = self.client.get('/api/indicators/').json()['items']
        self.assertEqual({item['code'] for item in indicators if item['visitor_available']}, {'MA', 'BOLL', 'VOL', 'MACD', 'KDJ', 'RSI'})

    def test_ai_analysis_is_not_available_to_a_guest(self):
        self.client.post('/api/auth/guest/')
        response = self.client.post('/api/ai-analysis/', data=json.dumps({'code': 'SH.600519'}), content_type='application/json')
        self.assertEqual(response.status_code, 403)


class RealMarketDataApiTests(TestCase):
    def make_user(self):
        return get_user_model().objects.create_user(
            username='member@example.com',
            email='member@example.com',
            password='A-safe-password-42',
        )

    def test_quote_returns_only_the_real_opend_snapshot(self):
        self.client.force_login(self.make_user())

        class Frame:
            empty = False
            iloc = None

            def __init__(self, row):
                self.iloc = self
                self.row = row

            def __getitem__(self, index):
                if index != 0:
                    raise IndexError(index)
                return self.row

        class Client:
            def __init__(self):
                self.frame = Frame({
                    'code': 'SH.600519', 'name': '贵州茅台', 'last_price': 1500.25,
                    'prev_close_price': 1490.0, 'open_price': 1495.0,
                    'high_price': 1505.0, 'low_price': 1488.0,
                    'update_time': '2026-09-05 10:00:00',
                })

            def get_market_snapshot(self, codes):
                self.codes = codes
                return RET_OK, self.frame

            def close(self):
                pass

        client = Client()
        with patch('core.views.context', return_value=client):
            response = self.client.get('/api/quote/SH.600519/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'code': 'SH.600519', 'name': '贵州茅台', 'price': 1500.25,
            'change': 0.688, 'open': 1495.0, 'high': 1505.0, 'low': 1488.0,
            'updated_at': '2026-09-05 10:00:00', 'source': 'futu-opend',
        })
        self.assertEqual(client.codes, ['SH.600519'])

    def test_quote_reports_missing_real_data_instead_of_zero(self):
        self.client.force_login(self.make_user())

        class Frame:
            empty = False

            def __init__(self):
                self.iloc = self

            def __getitem__(self, index):
                return {
                    'code': 'CC.BTCUSD', 'name': 'Bitcoin / USD', 'last_price': None,
                    'prev_close_price': None, 'open_price': None, 'high_price': None,
                    'low_price': None, 'update_time': '',
                }

        class Client:
            def get_market_snapshot(self, codes):
                return RET_OK, Frame()

            def close(self):
                pass

        with patch('core.views.context', return_value=Client()):
            response = self.client.get('/api/quote/CC.BTCUSD/')
        self.assertEqual(response.status_code, 502)
        self.assertIn('有效最新价', response.json()['error'])

    def test_kline_error_does_not_return_generated_bars(self):
        self.client.force_login(self.make_user())

        class Client:
            def request_history_kline(self, *args, **kwargs):
                return 1, 'OpenD unavailable', None

            def close(self):
                pass

        with patch('core.views.context', return_value=Client()):
            response = self.client.get('/api/kline/SH.600519/?period=日线')
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('bars', response.json())

    def test_indicator_timeout_message_is_neutral(self):
        self.client.force_login(self.make_user())
        Formula.objects.create(
            name='Synthetic timeout fixture',
            code='SYNTHETIC_TIMEOUT',
            placement='sub',
            source='OUT:MA(C,3);',
        )
        bars = [{
            'time': 1_700_000_000,
            'open': 10,
            'high': 11,
            'low': 9,
            'close': 10,
            'volume': 1_000,
            'amount': 10_000,
        }]
        with patch('core.views.history_bars', return_value=(bars, None, None)), patch(
            'core.views.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='node', timeout=8)
        ):
            response = self.client.get('/api/indicator-render/SYNTHETIC_TIMEOUT/SH.600519/?period=日线&count=100')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error'], '指标计算耗时过长，请稍后重试或降低同时运行的指标数量')


class TongdaxinFormulaEngineTests(SimpleTestCase):
    def run_formula(self, source):
        bars = [
            {
                "time": 1_700_000_000 + index * 86_400,
                "open": 10 + index * 0.2 - (0.4 if index % 3 == 0 else 0),
                "high": 11 + index * 0.2,
                "low": 9 + index * 0.2,
                "close": 10 + index * 0.2,
                "volume": 1_000 + index * 10,
                "amount": 10_000 + index * 100,
            }
            for index in range(40)
        ]
        return subprocess.run(
            ["node", str(Path(settings.BASE_DIR) / "core" / "formula_runner.mjs")],
            input=json.dumps({"source": source, "bars": bars, "period": "日线", "symbol": "SH.600519", "name": "贵州茅台"}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
        )

    def test_extended_math_statistics_reference_and_sar_functions(self):
        completed = self.run_formula(
            "LOG10:LOG(100);R2:ROUND2(3.14159,2);ALLHIGH:HHV(C,0);"
            "STREAK:BARSLASTCOUNT(C>O);HELD:VALUEWHEN(CROSS(C,MA(C,3)),C);"
            "PSAR:SAR(4,2,20);SECOND:FINDHIGH(C,0,5,2);SAMPLEVAR:VAR(C,5);OLD:REFV(C,1);"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        values = {line["name"]: line["values"][-1] for line in payload["lines"]}
        self.assertEqual(payload["engine"], "tdx-server-v2")
        self.assertEqual(values["LOG10"], 2)
        self.assertEqual(values["R2"], 3.14)
        self.assertAlmostEqual(values["ALLHIGH"], 17.8)
        self.assertTrue(values["PSAR"] > 0)
        self.assertAlmostEqual(values["SECOND"], 17.6)
        self.assertAlmostEqual(values["OLD"], 17.6)

    def test_drawing_band_kline_and_fixed_text_are_structured(self):
        completed = self.run_formula(
            "DRAWTEXT_FIX(ISLASTBAR,0.01,0.02,0,STRCAT('bars=',CON2STR(TOTALBARSCOUNT,0))),COLORWHITE;"
            "DRAWBAND(MA(C,3),RGB(255,0,0),MA(C,5),RGB(0,255,0));"
            "DRAWKLINE(H,O,L,C);"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["fixedTexts"][0]["text"], "bars=40")
        self.assertGreaterEqual(len(payload["sticks"]), 3)
        self.assertIn("#ff0000", {group["color"] for group in payload["sticks"]})

    def test_line_style_modifiers_remain_distinct(self):
        completed = self.run_formula(
            "CIRCLE:C,CIRCLEDOT,COLORRED,LINETHICK8;"
            "POINT:C,POINTDOT,COLORGREEN;"
            "CROSS:C,CROSSDOT,COLORBLUE;"
            "DASH:C,DOTLINE,COLORYELLOW;"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        styles = {line["name"]: line["style"] for line in payload["lines"]}
        self.assertEqual(styles, {
            "CIRCLE": "circle-dot", "POINT": "point-dot",
            "CROSS": "cross-dot", "DASH": "dotted",
        })
        self.assertEqual(payload["lines"][0]["width"], 8)

    def test_drawline_expand_continues_the_anchor_slope(self):
        completed = self.run_formula(
            "DRAWLINE(BARSCOUNT(C)=2,10,BARSCOUNT(C)=4,14,1),COLORRED,LINETHICK3;"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        line = payload["lines"][0]
        self.assertEqual(line["width"], 3)
        self.assertEqual(line["values"][:6], [None, 10, 12, 14, 16, 18])

    def test_drawnull_comparisons_only_select_real_values(self):
        completed = self.run_formula(
            "MASK:IF(C>O,DRAWNULL,C);"
            "HAS_VALUE:MASK!=DRAWNULL;"
            "IS_NULL:MASK=DRAWNULL;"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        values = {line["name"]: line["values"] for line in payload["lines"]}
        self.assertEqual(values["HAS_VALUE"][:6], [0, 1, 1, 0, 1, 1])
        self.assertEqual(values["IS_NULL"][:6], [1, 0, 0, 1, 0, 0])

    def test_unknown_function_reports_its_name_without_formula_source(self):
        completed = self.run_formula("SECRETLINE:TOTALLY_UNKNOWN(C,5);")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("暂不支持通达信函数：TOTALLY_UNKNOWN", completed.stderr)
        self.assertNotIn("SECRETLINE", completed.stderr)

    def test_strict_parser_rejects_invalid_or_unconsumed_syntax(self):
        for source in ("OUT:C$LOSE;", "OUT:(C+O;", "OUT:C O;", "OUT:TOTALLY_UNKNOWN_FIELD;"):
            with self.subTest(source=source):
                completed = self.run_formula(source)
                self.assertNotEqual(completed.returncode, 0)

    def test_strings_parameters_and_mainland_volume_units(self):
        completed = self.run_formula(
            "{参数设置：SCQH (0, 2, 0)}"
            "DRAWTEXT(ISLASTBAR,CLOSE,\"A,B\"),COLORWHITE;"
            "SELECTED:IF(SCQH=0,CLOSE,OPEN);"
            "AVERAGE:AMOUNT/(VOL*100);"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["markers"][0]["text"], "A,B")
        outputs = {line["name"]: line["values"] for line in payload["lines"]}
        self.assertEqual(outputs["SELECTED"][-1], 17.8)
        self.assertAlmostEqual(outputs["AVERAGE"][0], 10)

    def test_reference_edges_sar_period_and_stick_empty_mode_are_preserved(self):
        completed = self.run_formula(
            "OLD:REF(C,1);FAST:SAR(4,2,20);SLOW:SAR(10,2,20);"
            "STICKLINE(ISLASTBAR,C,O,3,-1),COLORWHITE;"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        outputs = {line["name"]: line["values"] for line in payload["lines"]}
        self.assertIsNone(outputs["OLD"][0])
        self.assertIsNotNone(outputs["FAST"][4])
        self.assertIsNone(outputs["SLOW"][4])
        self.assertEqual(payload["sticks"][0]["points"][0]["empty"], -1)

    def test_delayed_reference_recovers_and_wide_stickline_is_background(self):
        completed = self.run_formula(
            "DELAYED:EMA(REF(C,3),5);"
            "STICKLINE(C>=0,110000,-10000,5,0),COLORGRAY;"
            "STICKLINE(ISLASTBAR,C,O,3,0),COLORRED;"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        delayed = next(line["values"] for line in payload["lines"] if line["name"] == "DELAYED")
        self.assertIsNone(delayed[2])
        self.assertIsNotNone(delayed[3])
        self.assertEqual(payload["sticks"][0]["layer"], "background")
        self.assertEqual(payload["sticks"][1]["layer"], "normal")

    def test_date_string_and_security_match_semantics(self):
        completed = self.run_formula(
            "ZERO:DATETODAY(901219);DATE0:DAYTODATE(0);SEC:TIMETOSEC(93000);"
            "CLOCK:SECTOTIME(34200);PREFIX:CODELIKE('600');NAME:NAMELIKE('贵州');"
            "HASNAME:NAMEINCLUDE('茅台');NUMBER:STR2CON('2365.02');"
            "DRAWTEXT(ISLASTBAR,C,VARCAT(SUBSTR('通达信',1,2),STRSPACE('公式'))),COLORWHITE;"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        outputs = {line["name"]: line["values"][-1] for line in payload["lines"]}
        self.assertEqual(outputs["ZERO"], 0)
        self.assertEqual(outputs["DATE0"], 901219)
        self.assertEqual(outputs["SEC"], 34200)
        self.assertEqual(outputs["CLOCK"], 93000)
        self.assertEqual(outputs["PREFIX"], 1)
        self.assertEqual(outputs["NAME"], 1)
        self.assertEqual(outputs["HASNAME"], 1)
        self.assertEqual(outputs["NUMBER"], 2365.02)
        self.assertEqual(payload["markers"][0]["text"], "通达公式 ")

    def test_opend_kline_adapter_keeps_formula_data_fields(self):
        class Frame:
            def itertuples(self):
                return [SimpleNamespace(
                    time_key="2026-09-03 15:00:00",
                    open=10,
                    high=12,
                    low=9,
                    close=11,
                    volume=12300,
                    turnover=135300,
                    turnover_rate=0.75,
                    last_close=10.5,
                )]

        row = bar_rows(Frame())[0]
        self.assertEqual(row["amount"], 135300)
        self.assertEqual(row["turnover_rate"], 0.75)
        self.assertEqual(row["last_close"], 10.5)

    def test_chip_model_uses_turnover_rate_not_monetary_turnover(self):
        bars = [
            {"time": 1_700_000_000, "open": 10, "high": 10, "low": 10, "close": 10, "volume": 1_000, "amount": 10_000, "turnover": 10_000, "turnover_rate": 1},
            {"time": 1_700_086_400, "open": 20, "high": 20, "low": 20, "close": 20, "volume": 1_000, "amount": 20_000, "turnover": 20_000, "turnover_rate": 1},
        ]
        completed = subprocess.run(
            ["node", str(Path(settings.BASE_DIR) / "core" / "formula_runner.mjs")],
            input=json.dumps({"source": "MID:COST(50);", "bars": bars, "period": "日线", "symbol": "SH.600519", "name": "校准", "chip": {"floatShares": 100_000}}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        latest = json.loads(completed.stdout)["lines"][0]["values"][-1]
        # A 1% daily turnover retains the first day's chips.  Treating the
        # 20,000 monetary turnover amount as a 100% rate would incorrectly
        # replace them all and return a value near 20 instead.
        self.assertLess(latest, 15)
