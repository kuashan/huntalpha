import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
from decimal import Decimal
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
from .models import MarketSymbol
from .symbol_catalog import FutuOpenDAdapter, ProviderCatalogSnapshot, ProviderSymbol
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


class SymbolCatalogSyncTests(TestCase):
    def symbol(self, code, name, market='cn', active=True, exchange='CN_SH'):
        return ProviderSymbol(code, name, market, exchange, 'STOCK', active)

    def run_sync(self, snapshot, market='cn'):
        class FakeProvider:
            def fetch_market(self, requested_market):
                self.requested_market = requested_market
                return snapshot

        with patch('core.management.commands.sync_symbol_catalog.FutuOpenDAdapter', FakeProvider):
            output = io.StringIO()
            call_command('sync_symbol_catalog', market=market, stdout=output)
        return output.getvalue()

    def test_sync_is_idempotent_and_updates_name_and_status(self):
        snapshot = ProviderCatalogSnapshot(
            'cn',
            (self.symbol('SH.600001', '甲公司'), self.symbol('SZ.000001', '乙公司')),
            {'SH.600001': Decimal('1200000000'), 'SZ.000001': Decimal('900000000')},
        )
        first = self.run_sync(snapshot)
        second = self.run_sync(snapshot)
        self.assertIn('added=2', first)
        self.assertIn('added=0', second)
        self.assertEqual(MarketSymbol.objects.count(), 2)

        changed = ProviderCatalogSnapshot('cn', (self.symbol('SH.600001', '甲公司（更名）', active=False),), {'SH.600001': Decimal('1300000000')})
        self.run_sync(changed)
        row = MarketSymbol.objects.get(code='SH.600001')
        self.assertEqual(row.name, '甲公司（更名）')
        self.assertFalse(row.active)
        self.assertTrue(MarketSymbol.objects.filter(code='SZ.000001', active=False).exists())

    def test_provider_missing_symbol_is_inactivated_not_deleted(self):
        MarketSymbol.objects.create(
            code='HK.09999', name='历史证券', market='hk', exchange='HK_MAINBOARD',
            security_type='STOCK', provider='futu-opend', provider_symbol='HK.09999',
        )
        snapshot = ProviderCatalogSnapshot('hk', (), {})
        output = self.run_sync(snapshot, market='hk')
        self.assertIn('inactive=1', output)
        row = MarketSymbol.objects.get(code='HK.09999')
        self.assertFalse(row.active)
        self.assertEqual(MarketSymbol.objects.count(), 1)

    def test_one_market_failure_does_not_block_other_markets(self):
        snapshots = {
            'cn': ProviderCatalogSnapshot('cn', (self.symbol('SH.600001', '甲公司'),), {'SH.600001': Decimal('10')}),
            'us': ProviderCatalogSnapshot('us', (self.symbol('US.TEST', 'Test Corp', 'us', exchange='US_NYSE'),), {'US.TEST': Decimal('20')}),
        }

        class FakeProvider:
            def fetch_market(self, market):
                if market == 'hk':
                    raise RuntimeError('provider unavailable')
                return snapshots[market]

        with patch('core.management.commands.sync_symbol_catalog.FutuOpenDAdapter', FakeProvider):
            output = io.StringIO()
            call_command('sync_symbol_catalog', stdout=output)
        self.assertIn('market=hk status=error', output.getvalue())
        self.assertTrue(MarketSymbol.objects.filter(code='SH.600001').exists())
        self.assertTrue(MarketSymbol.objects.filter(code='US.TEST').exists())

    def test_market_cap_failure_clears_stale_leader_values(self):
        MarketSymbol.objects.create(
            code='US.TEST', name='Test Corp', market='us', exchange='US_NYSE', security_type='STOCK',
            provider='futu-opend', provider_symbol='US.TEST', market_cap=Decimal('100'), market_cap_currency='USD',
        )
        snapshot = ProviderCatalogSnapshot(
            'us', (self.symbol('US.TEST', 'Test Corp', 'us', exchange='US_NYSE'),), {}, 'market_cap_fetch_failed'
        )
        self.run_sync(snapshot, market='us')
        row = MarketSymbol.objects.get(code='US.TEST')
        self.assertIsNone(row.market_cap)
        self.assertIsNone(row.market_cap_updated_at)

    def test_futu_adapter_maps_stock_catalog_and_filters_invalid_caps(self):
        class Frame:
            def __init__(self, rows):
                self.rows = rows

            def itertuples(self, index=False):
                return iter(self.rows)

        class Client:
            def get_stock_basicinfo(self, market, stock_type):
                return 0, Frame([
                    SimpleNamespace(code='HK.00001', name='真实公司', stock_type='STOCK', exchange_type='HK_MAINBOARD', delisting=False),
                    SimpleNamespace(code='HK.00002', name='ETF fixture', stock_type='ETF', exchange_type='HK_MAINBOARD', delisting=False),
                ])

            def get_stock_filter(self, *args, **kwargs):
                return 0, (False, 2, [
                    SimpleNamespace(stock_code='HK.00001', market_val='123.45'),
                    SimpleNamespace(stock_code='HK.00002', market_val='nan'),
                ])

            def close(self):
                pass

        snapshot = FutuOpenDAdapter(context_factory=Client).fetch_market('hk')
        self.assertEqual([item.code for item in snapshot.symbols], ['HK.00001'])
        self.assertEqual(snapshot.market_caps, {'HK.00001': Decimal('123.4500')})


class SymbolCatalogApiTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username='catalog@example.com', password='A-safe-password-42'))
        for index in range(6):
            MarketSymbol.objects.create(
                code=f'SH.6000{index + 1}', name=f'测试公司{index + 1}', market='cn', exchange='CN_SH',
                security_type='STOCK', provider='futu-opend', provider_symbol=f'SH.6000{index + 1}',
                market_cap=Decimal(str((6 - index) * 100)), market_cap_currency='CNY',
            )
        MarketSymbol.objects.create(
            code='SH.000000', name='无效市值', market='cn', exchange='CN_SH', security_type='STOCK',
            provider='futu-opend', provider_symbol='SH.000000', market_cap=Decimal('0'), market_cap_currency='CNY',
        )
        MarketSymbol.objects.create(
            code='HK.00700', name='港股公司', market='hk', exchange='HK_MAINBOARD', security_type='STOCK',
            provider='futu-opend', provider_symbol='HK.00700', market_cap=Decimal('999'), market_cap_currency='HKD',
        )

    def test_leaders_are_sorted_filtered_and_market_specific(self):
        response = self.client.get('/api/market-leaders/cn/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['code'] for item in response.json()['items']], [f'SH.6000{index}' for index in range(1, 6)])
        self.assertEqual(response.json()['items'][0]['market_cap_currency'], 'CNY')
        self.assertNotIn('SH.000000', [item['code'] for item in response.json()['items']])

        hk = self.client.get('/api/market-leaders/hk/').json()
        self.assertEqual([item['code'] for item in hk['items']], ['HK.00700'])

    def test_search_supports_name_code_limit_and_pagination(self):
        name_search = self.client.get('/api/symbols/cn/?q=测试公司&limit=2&page=2')
        self.assertEqual(name_search.status_code, 200)
        self.assertEqual(name_search.json()['total'], 6)
        self.assertEqual([item['code'] for item in name_search.json()['items']], ['SH.60003', 'SH.60004'])

        code_search = self.client.get('/api/symbols/cn/?q=60006&limit=10')
        self.assertEqual([item['code'] for item in code_search.json()['items']], ['SH.60006'])

    def test_empty_search_returns_top_five_and_crypto_is_unavailable(self):
        response = self.client.get('/api/symbols/cn/')
        self.assertEqual(response.json()['mode'], 'leaders')
        self.assertEqual(len(response.json()['items']), 5)
        crypto = self.client.get('/api/symbols/crypto/').json()
        self.assertEqual(crypto['status'], 'unavailable')
        self.assertEqual(crypto['items'], [])

    def test_provider_failure_has_no_static_fallback(self):
        class FakeProvider:
            def fetch_market(self, market):
                raise RuntimeError('OpenD unavailable')

        with patch('core.management.commands.sync_symbol_catalog.FutuOpenDAdapter', FakeProvider):
            output = io.StringIO()
            call_command('sync_symbol_catalog', market='us', stdout=output)
        self.assertIn('market=us status=error', output.getvalue())
        self.assertFalse(MarketSymbol.objects.filter(market='us').exists())


class SymbolCatalogFrontendContractTests(SimpleTestCase):
    def test_runtime_catalog_has_no_hand_written_securities(self):
        source = (Path(settings.BASE_DIR) / 'frontend' / 'src' / 'data' / 'marketData.js').read_text(encoding='utf-8')
        self.assertNotIn('贵州茅台', source)
        self.assertNotIn('SH.600519', source)
        self.assertNotIn('CC.BTCUSD', source)
        self.assertNotIn('symbolsFor', source)

    def test_scheduler_invokes_only_the_sync_management_command(self):
        source = (Path(settings.BASE_DIR) / 'scripts' / 'manage_symbol_catalog_task.ps1').read_text(encoding='utf-8')
        self.assertIn('Install', source)
        self.assertIn('Remove', source)
        self.assertIn('manage.py sync_symbol_catalog', source)
        self.assertNotIn('get_stock_basicinfo', source)


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
