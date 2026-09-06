import hashlib
import io
import inspect
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import shutil
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
from datetime import datetime, timezone as datetime_timezone
from unittest import mock
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command, CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from futu import Market, RET_OK

from formula_editor.models import Formula
from .market_indices import INDEX_DEFINITIONS, FutuOpenDIndexAdapter, convert_snapshot_frame
from .models import AccountProfile, MarketSymbol, WatchlistEntry
from .symbol_catalog import FutuOpenDAdapter, ProviderCatalogSnapshot, ProviderSymbol, ProviderSyncError, apply_catalog_snapshot
from .views import _watchlist_create, bar_rows, formula_run_registry, merge_calculation_snapshot_rows
from .watchlist import resolve_account_tier, resolve_watchlist_limit
from .realtime import (
    FutuRealtimeProvider,
    NormalizedBar,
    RealtimeRegistry,
    RealtimeStateStore,
    RealtimeProviderError,
    merge_realtime_bar,
    provider_time_to_timestamp,
)
from .realtime.formula_scheduler import FormulaFlightCoordinator, FormulaRunRegistry, calculation_input_fingerprint
from PIL import Image


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
        session = self.client.get('/api/auth/session/')
        self.assertEqual(session.status_code, 401)
        self.assertIsNone(session.json()['tier'])
        self.assertIsNone(session.json()['tier_label'])
        self.assertIsNone(session.json()['watchlist_limit'])

    def test_email_registration_creates_a_session(self):
        response = self.client.post(
            '/api/auth/register/',
            data=json.dumps({'email': 'researcher@example.com', 'password': 'A-safe-password-42'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['user']['email'], 'researcher@example.com')
        self.assertEqual(response.json()['user']['tier'], 'free')
        self.assertEqual(response.json()['user']['tier_label'], 'FREE')
        self.assertEqual(response.json()['user']['watchlist_limit'], 10)
        self.assertEqual(response.json()['tier'], 'free')
        self.assertEqual(response.json()['tier_label'], 'FREE')
        self.assertEqual(response.json()['watchlist_limit'], 10)
        self.assertEqual(self.client.get('/api/auth/session/').status_code, 200)

    def test_authenticated_tier_uses_free_without_a_real_pro_entitlement(self):
        User = get_user_model()
        user = User.objects.create_user(username='tier@example.com', email='tier@example.com', password='safe-password-123')
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])
        self.client.force_login(user)

        payload = self.client.get('/api/auth/session/').json()
        self.assertEqual(resolve_account_tier(user), 'free')
        self.assertEqual(resolve_watchlist_limit(user), 10)
        self.assertEqual(payload['user']['tier'], 'free')
        self.assertEqual(payload['user']['tier_label'], 'FREE')
        self.assertEqual(payload['user']['watchlist_limit'], 10)
        self.assertNotEqual(payload['user']['tier'], 'pro')
        self.assertEqual(payload['tier'], 'free')
        self.assertEqual(payload['tier_label'], 'FREE')
        self.assertEqual(payload['watchlist_limit'], 10)

    def test_guest_session_can_see_common_indicators_only(self):
        response = self.client.post('/api/auth/guest/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['visitor'])
        self.assertIsNone(response.json()['user']['tier'])
        self.assertIsNone(response.json()['user']['tier_label'])
        self.assertIsNone(response.json()['user']['watchlist_limit'])
        self.assertIsNone(response.json()['tier'])
        self.assertIsNone(response.json()['tier_label'])
        self.assertIsNone(response.json()['watchlist_limit'])
        indicators = self.client.get('/api/indicators/').json()['items']
        self.assertEqual({item['code'] for item in indicators if item['visitor_available']}, {'MA', 'BOLL', 'VOL', 'MACD', 'KDJ', 'RSI'})

    def test_ai_analysis_is_not_available_to_a_guest(self):
        self.client.post('/api/auth/guest/')
        response = self.client.post('/api/ai-analysis/', data=json.dumps({'code': 'SH.600519'}), content_type='application/json')
        self.assertEqual(response.status_code, 403)


class AccountCenterApiTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        User = get_user_model()
        self.user = User.objects.create_user(
            username='account@example.com',
            email='account@example.com',
            first_name='研究员',
            password='Original-password-42',
        )
        self.symbol = MarketSymbol.objects.create(
            code='SH.600519', name='测试证券', market='cn', exchange='CN_SH',
            security_type='STOCK', active=True, provider='test-provider',
            provider_symbol='SH.600519',
        )

    def csrf_headers(self):
        response = self.client.get('/api/csrf/')
        self.assertEqual(response.status_code, 200)
        return {'HTTP_X_CSRFTOKEN': self.client.cookies['csrftoken'].value}

    def test_summary_rejects_anonymous_and_visitor(self):
        anonymous = self.client.get('/api/account/summary/')
        self.assertEqual(anonymous.status_code, 403)
        self.client.post('/api/auth/guest/')
        visitor = self.client.get('/api/account/summary/')
        self.assertEqual(visitor.status_code, 403)
        self.assertEqual(visitor.json()['code'], 'login_required')

    def test_summary_returns_real_account_state_without_periodic_ai_fields(self):
        self.client.force_login(self.user)
        WatchlistEntry.objects.create(user=self.user, symbol=self.symbol)
        response = self.client.get('/api/account/summary/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['user'], {'name': '研究员', 'email': 'account@example.com', 'avatar_url': None})
        self.assertEqual(payload['membership'], {'tier': 'free', 'tier_label': 'FREE', 'expires_at': None})
        self.assertEqual(payload['ai_beans'], {'status': 'not_enabled', 'balance': None, 'permanent': True})
        self.assertEqual(payload['watchlist'], {'total': 1, 'limit': 10, 'remaining': 9})
        self.assertNotIn('reset_at', payload)
        self.assertNotIn('next_reset_at', payload)
        self.assertNotIn('reset_at', payload['ai_beans'])
        self.assertNotIn('next_reset_at', payload['ai_beans'])

    def test_change_password_is_csrf_protected_and_preserves_session(self):
        self.client.force_login(self.user)
        body = json.dumps({
            'current_password': 'Original-password-42',
            'new_password': 'New-secure-password-43',
            'confirm_password': 'New-secure-password-43',
        })
        without_csrf = self.client.post('/api/account/change-password/', data=body, content_type='application/json')
        self.assertEqual(without_csrf.status_code, 403)

        headers = self.csrf_headers()
        wrong_current = self.client.post(
            '/api/account/change-password/',
            data=json.dumps({**json.loads(body), 'current_password': 'wrong'}),
            content_type='application/json', **headers,
        )
        self.assertEqual(wrong_current.status_code, 400)
        self.assertEqual(wrong_current.json()['code'], 'current_password_invalid')

        mismatch = self.client.post(
            '/api/account/change-password/',
            data=json.dumps({**json.loads(body), 'confirm_password': 'different'}),
            content_type='application/json', **headers,
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(mismatch.json()['code'], 'password_mismatch')

        weak = self.client.post(
            '/api/account/change-password/',
            data=json.dumps({**json.loads(body), 'new_password': '123', 'confirm_password': '123'}),
            content_type='application/json', **headers,
        )
        self.assertEqual(weak.status_code, 400)
        self.assertEqual(weak.json()['code'], 'password_invalid')

        success = self.client.post('/api/account/change-password/', data=body, content_type='application/json', **headers)
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()['status'], 'ok')
        refreshed = get_user_model().objects.get(pk=self.user.pk)
        self.assertTrue(refreshed.check_password('New-secure-password-43'))
        self.assertEqual(self.client.get('/api/auth/session/').status_code, 200)


class AccountProfileApiTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        User = get_user_model()
        self.user = User.objects.create_user(
            username='profile@example.com', email='profile@example.com', first_name='研究员', password='Original-password-42'
        )
        self.media_temp = tempfile.TemporaryDirectory()
        self.media_root = Path(self.media_temp.name)
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_temp.cleanup)

    def csrf_headers(self):
        self.client.get('/api/csrf/')
        return {'HTTP_X_CSRFTOKEN': self.client.cookies['csrftoken'].value}

    def patch_json(self, path, payload, headers=None):
        return self.client.patch(path, data=json.dumps(payload), content_type='application/json', **(headers or {}))

    def image_upload(self, image_format='PNG', name=None, size=(64, 64)):
        output = io.BytesIO()
        Image.new('RGB', size, (43, 113, 158)).save(output, format=image_format)
        extension = image_format.lower()
        return SimpleUploadedFile(name or f'avatar.{extension}', output.getvalue(), content_type=f'image/{extension}')

    def test_summary_defaults_do_not_create_profile_and_auth_payload_has_preferences(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/account/summary/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['preferences'], {'price_color_mode': 'cn', 'default_market': 'cn', 'default_period': '日线'})
        self.assertIsNone(response.json()['user']['avatar_url'])
        self.assertFalse(AccountProfile.objects.filter(user=self.user).exists())
        session = self.client.get('/api/auth/session/').json()
        self.assertEqual(session['user']['preferences'], response.json()['preferences'])

    def test_profile_is_authenticated_csrf_protected_and_only_updates_display_name(self):
        anonymous = self.patch_json('/api/account/profile/', {'display_name': '新名称'})
        self.assertEqual(anonymous.status_code, 403)
        self.client.post('/api/auth/guest/')
        visitor = self.patch_json('/api/account/profile/', {'display_name': '新名称'}, self.csrf_headers())
        self.assertEqual(visitor.status_code, 403)
        self.client.force_login(self.user)
        without_csrf = self.patch_json('/api/account/profile/', {'display_name': '新名称'})
        self.assertEqual(without_csrf.status_code, 403)
        headers = self.csrf_headers()
        updated = self.patch_json('/api/account/profile/', {'display_name': '  新名称  '}, headers)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['user']['name'], '新名称')
        self.assertEqual(get_user_model().objects.get(pk=self.user.pk).first_name, '新名称')
        forbidden = self.patch_json('/api/account/profile/', {'display_name': '另一个', 'tier': 'pro'}, headers)
        self.assertEqual(forbidden.status_code, 400)
        non_string = self.patch_json('/api/account/profile/', {'display_name': ['不是字符串']}, headers)
        self.assertEqual(non_string.status_code, 400)
        self.assertEqual(self.client.get('/api/auth/session/').json()['user']['tier'], 'free')

    def test_preferences_validate_persist_and_keep_account_tier_separate(self):
        self.client.force_login(self.user)
        self.assertEqual(self.patch_json('/api/account/preferences/', {'default_market': 'us'}).status_code, 403)
        headers = self.csrf_headers()
        invalid = self.patch_json('/api/account/preferences/', {'default_market': 'crypto'}, headers)
        self.assertEqual(invalid.status_code, 400)
        non_string = self.patch_json('/api/account/preferences/', {'default_market': ['us']}, headers)
        self.assertEqual(non_string.status_code, 400)
        valid = self.patch_json('/api/account/preferences/', {
            'price_color_mode': 'international', 'default_market': 'hk', 'default_period': '30分',
        }, headers)
        self.assertEqual(valid.status_code, 200)
        expected = {'price_color_mode': 'international', 'default_market': 'hk', 'default_period': '30分'}
        self.assertEqual(valid.json()['preferences'], expected)
        self.assertEqual(self.client.get('/api/account/summary/').json()['preferences'], expected)
        self.assertEqual(self.client.get('/api/auth/session/').json()['user']['preferences'], expected)
        self.assertEqual(valid.json()['user']['tier'], 'free')

    def test_avatar_requires_auth_csrf_validates_and_replaces_then_deletes(self):
        upload = self.image_upload()
        self.assertEqual(self.client.post('/api/account/avatar/', {'avatar': upload}).status_code, 403)
        self.client.force_login(self.user)
        no_csrf = self.client.post('/api/account/avatar/', {'avatar': self.image_upload()})
        self.assertEqual(no_csrf.status_code, 403)
        headers = self.csrf_headers()
        svg = SimpleUploadedFile('avatar.svg', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', content_type='image/svg+xml')
        self.assertEqual(self.client.post('/api/account/avatar/', {'avatar': svg}, **headers).status_code, 400)
        oversized = SimpleUploadedFile('avatar.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')
        self.assertEqual(self.client.post('/api/account/avatar/', {'avatar': oversized}, **headers).status_code, 400)
        too_wide = self.image_upload(size=(4097, 1))
        self.assertEqual(self.client.post('/api/account/avatar/', {'avatar': too_wide}, **headers).status_code, 400)

        for image_format in ('JPEG', 'PNG', 'WEBP'):
            response = self.client.post('/api/account/avatar/', {'avatar': self.image_upload(image_format)}, **headers)
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.json()['avatar_url'])
        profile = AccountProfile.objects.get(user=self.user)
        old_name = profile.avatar.name
        old_path = self.media_root / old_name
        self.assertTrue(old_path.is_file())
        replacement = self.client.post('/api/account/avatar/', {'avatar': self.image_upload('PNG', 'replacement.png')}, **headers)
        self.assertEqual(replacement.status_code, 200)
        new_name = AccountProfile.objects.get(user=self.user).avatar.name
        self.assertNotEqual(old_name, new_name)
        self.assertFalse(old_path.exists())
        self.assertTrue((self.media_root / new_name).is_file())
        deleted = self.client.delete('/api/account/avatar/', **headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(deleted.json()['avatar_url'])
        self.assertFalse((self.media_root / new_name).exists())


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
        snapshot = ProviderCatalogSnapshot(
            'hk', (self.symbol('HK.10000', '当前证券', market='hk', exchange='HK_MAINBOARD'),),
            {'HK.10000': Decimal('10')},
        )
        output = self.run_sync(snapshot, market='hk')
        self.assertIn('inactive=1', output)
        row = MarketSymbol.objects.get(code='HK.09999')
        self.assertFalse(row.active)
        self.assertEqual(MarketSymbol.objects.count(), 2)

    def test_suspicious_empty_catalog_preserves_existing_market(self):
        MarketSymbol.objects.create(
            code='HK.09999', name='历史证券', market='hk', exchange='HK_MAINBOARD',
            security_type='STOCK', provider='futu-opend', provider_symbol='HK.09999',
        )
        output = self.run_sync(ProviderCatalogSnapshot('hk', (), {}), market='hk')
        self.assertIn('market=hk status=error error_type=suspicious_empty_catalog', output)
        self.assertTrue(MarketSymbol.objects.get(code='HK.09999').active)

    def test_adapter_rejects_successful_empty_provider_catalog(self):
        class EmptyFrame:
            def itertuples(self, index=False):
                return iter(())

        class Client:
            def get_stock_basicinfo(self, market, stock_type):
                return RET_OK, EmptyFrame()

            def close(self):
                pass

        with self.assertRaises(ProviderSyncError) as raised:
            FutuOpenDAdapter(context_factory=Client).fetch_market('hk')
        self.assertEqual(raised.exception.error_type, 'suspicious_empty_catalog')

    def test_cn_market_caps_merge_sh_and_sz_before_ranking(self):
        class Frame:
            def __init__(self, rows):
                self.rows = rows

            def itertuples(self, index=False):
                return iter(self.rows)

        class Client:
            basic_calls = []
            filter_calls = []

            def get_stock_basicinfo(self, market, stock_type):
                self.basic_calls.append(market)
                rows = {
                    Market.SH: [SimpleNamespace(code='SH.600001', name='上海样本', stock_type='STOCK', exchange_type='SH_MAINBOARD', delisting=False)],
                    Market.SZ: [SimpleNamespace(code='SZ.000001', name='深圳样本', stock_type='STOCK', exchange_type='SZ_MAINBOARD', delisting=False)],
                }[market]
                return RET_OK, Frame(rows)

            def get_stock_filter(self, market, **kwargs):
                self.filter_calls.append(market)
                rows = {
                    Market.SH: [SimpleNamespace(stock_code='SH.600001', market_val='100')],
                    Market.SZ: [SimpleNamespace(stock_code='SZ.000001', market_val='1000')],
                }[market]
                return RET_OK, (True, len(rows), rows)

            def close(self):
                pass

        client = Client()
        snapshot = FutuOpenDAdapter(context_factory=lambda: client).fetch_market('cn')
        self.assertEqual(client.basic_calls, [Market.SH, Market.SZ])
        self.assertEqual(client.filter_calls, [Market.SH, Market.SZ])
        self.assertEqual(snapshot.market_caps['SZ.000001'], Decimal('1000.0000'))
        self.assertEqual(snapshot.market_caps['SH.600001'], Decimal('100.0000'))

        apply_catalog_snapshot(snapshot)
        ranked = list(MarketSymbol.objects.filter(market='cn').order_by('-market_cap').values_list('code', flat=True))
        self.assertEqual(ranked, ['SZ.000001', 'SH.600001'])

    def test_hk_alternate_currency_is_not_mixed_into_leaders(self):
        class Frame:
            def __init__(self, rows):
                self.rows = rows

            def itertuples(self, index=False):
                return iter(self.rows)

        class Client:
            def get_stock_basicinfo(self, market, stock_type):
                return RET_OK, Frame([
                    SimpleNamespace(code='HK.00001', name='主柜台样本', stock_type='STOCK', exchange_type='HK_MAINBOARD', stock_child_type='N/A', delisting=False),
                    SimpleNamespace(code='HK.80001', name='主柜台样本-R', stock_type='STOCK', exchange_type='HK_MAINBOARD', stock_child_type='N/A', currency='CNY', delisting=False),
                ])

            def get_stock_filter(self, market, **kwargs):
                return RET_OK, (False, 2, [
                    SimpleNamespace(stock_code='HK.80001', market_val='999999'),
                    SimpleNamespace(stock_code='HK.00001', market_val='100'),
                ])

            def close(self):
                pass

        snapshot = FutuOpenDAdapter(context_factory=Client).fetch_market('hk')
        alternate = next(item for item in snapshot.symbols if item.code == 'HK.80001')
        self.assertEqual(alternate.market_cap_currency, 'CNY')
        self.assertFalse(alternate.market_cap_eligible)
        self.assertEqual(snapshot.market_caps, {'HK.00001': Decimal('100.0000')})

        apply_catalog_snapshot(snapshot)
        stored = MarketSymbol.objects.get(code='HK.80001')
        self.assertIsNone(stored.market_cap)
        self.assertEqual(stored.market_cap_currency, 'CNY')
        self.client.force_login(get_user_model().objects.create_user(username='hk-catalog@example.com', password='A-safe-password-42'))
        leaders = self.client.get('/api/market-leaders/hk/').json()['items']
        self.assertEqual([item['code'] for item in leaders], ['HK.00001'])

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


class MarketIndexSnapshotTests(SimpleTestCase):
    class Frame:
        def __init__(self, rows):
            self.rows = rows

        def iterrows(self):
            return enumerate(self.rows)

    class Context:
        def __init__(self, responses):
            self.responses = responses
            self.calls = []

        def get_market_snapshot(self, codes):
            key = tuple(codes)
            self.calls.append(key)
            return self.responses[key]

        def close(self):
            pass

    def test_definitions_contain_the_seven_verified_index_mappings(self):
        self.assertEqual(len(INDEX_DEFINITIONS), 7)
        self.assertEqual(
            [(item.market, item.provider_code, item.provider_name) for item in INDEX_DEFINITIONS],
            [
                ("cn", "SH.000001", "上证指数"),
                ("cn", "SZ.399001", "深证成指"),
                ("hk", "HK.800000", "恒生指数"),
                ("hk", "HK.800700", "恒生科技指数"),
                ("us", "US..SPX", "标普500指数"),
                ("us", "US..IXIC", "纳斯达克综合指数"),
                ("us", "US..DJI", "道琼斯指数"),
            ],
        )

    def test_snapshot_frame_converts_realistic_public_fields_and_change(self):
        definition = INDEX_DEFINITIONS[0]
        items = convert_snapshot_frame(self.Frame([{
            "code": definition.provider_code,
            "name": definition.provider_name,
            "last_price": 105.0,
            "prev_close_price": 100.0,
            "open_price": 101.0,
            "high_price": 106.0,
            "low_price": 99.0,
            "update_time": "2026-09-04 15:00:00",
        }]), (definition,))
        self.assertEqual(items[0]["status"], "ok")
        self.assertEqual(items[0]["price"], 105.0)
        self.assertEqual(items[0]["previous_close"], 100.0)
        self.assertEqual(items[0]["change"], 5.0)
        self.assertEqual(items[0]["change_percent"], 5.0)
        self.assertEqual(items[0]["updated_at"], "2026-09-04 15:00:00")

    def test_invalid_previous_close_never_creates_a_fake_percentage(self):
        definition = INDEX_DEFINITIONS[0]
        for previous in (0, None, float("nan")):
            with self.subTest(previous=previous):
                item = convert_snapshot_frame(self.Frame([{
                    "code": definition.provider_code,
                    "name": definition.provider_name,
                    "last_price": 105.0,
                    "prev_close_price": previous,
                }]), (definition,))[0]
                self.assertEqual(item["price"], 105.0)
                self.assertIsNone(item["change"])
                self.assertIsNone(item["change_percent"])
                self.assertEqual(item["status"], "partial")

    def test_nan_price_is_unavailable_and_not_returned_as_a_number(self):
        definition = INDEX_DEFINITIONS[0]
        item = convert_snapshot_frame(self.Frame([{
            "code": definition.provider_code,
            "last_price": float("nan"),
            "prev_close_price": 100.0,
        }]), (definition,))[0]
        self.assertIsNone(item["price"])
        self.assertIsNone(item["change"])
        self.assertIsNone(item["change_percent"])
        self.assertEqual(item["status"], "unavailable")

    def test_market_batches_are_isolated_and_a_missing_index_does_not_hide_others(self):
        definitions_by_market = {
            market: tuple(item for item in INDEX_DEFINITIONS if item.market == market)
            for market in ("cn", "hk", "us")
        }
        responses = {}
        for market, definitions in definitions_by_market.items():
            rows = [{
                "code": definition.provider_code,
                "name": definition.provider_name,
                "last_price": 100.0 + index,
                "prev_close_price": 100.0,
            } for index, definition in enumerate(definitions) if definition.key != "shenzhen"]
            responses[tuple(item.provider_code for item in definitions)] = (RET_OK, self.Frame(rows))
        context = self.Context(responses)
        items = FutuOpenDIndexAdapter(lambda: context).fetch()
        by_key = {item["code"]: item for item in items}
        self.assertEqual(len(context.calls), 3)
        self.assertEqual(by_key["SH.000001"]["status"], "ok")
        self.assertEqual(by_key["SZ.399001"]["status"], "unavailable")
        self.assertEqual(by_key["HK.800000"]["status"], "ok")
        self.assertEqual(by_key["US..SPX"]["status"], "ok")

    def test_opend_failure_returns_only_unavailable_rows_without_fallback_values(self):
        items = FutuOpenDIndexAdapter(lambda: (_ for _ in ()).throw(RuntimeError("OpenD unavailable"))).fetch()
        self.assertEqual(len(items), 7)
        self.assertTrue(all(item["status"] == "unavailable" for item in items))
        self.assertTrue(all(item["price"] is None for item in items))
        self.assertTrue(all(item["change_percent"] is None for item in items))

    def test_frontend_header_keeps_index_data_and_uses_crypto_preview_without_quotes(self):
        app_source = (Path(settings.BASE_DIR) / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
        self.assertIn("const visibleMarkets = computed(() => markets)", app_source)
        self.assertIn('v-for="item in visibleMarkets"', app_source)
        self.assertIn("/api/market-index-snapshots/", app_source)
        self.assertIn("displayIndexPrice(index.price)", app_source)
        self.assertIn("index.status === 'loading'", app_source)
        self.assertIn("const cryptoPreviewRows = [{ name: 'BTC' }, { name: 'ETH' }]", app_source)
        self.assertIn("item.code === 'crypto' ? '待接入真实数据源' : 'futu-opend'", app_source)
        self.assertIn("provider_status: 'not_connected'", app_source)
        self.assertIn(":title=\"indexTitle(index)\"", app_source)
        self.assertNotIn("v-for=\"item in markets\"", app_source)
        self.assertNotIn("/api/kline/", app_source)
        self.assertNotIn("/api/indicator-render/", app_source)
        self.assertNotIn("/api/quote/CC.", app_source)
        self.assertIn(".markets{grid-template-columns:repeat(4,minmax(0,1fr));min-height:100px}", app_source)
        self.assertIn("@media(max-width:800px){.markets{grid-template-columns:repeat(2,minmax(0,1fr))}", app_source)
        self.assertIn("index.updated_at ? `更新时间：${index.updated_at}` : status", app_source)


class HuntAlphaBrandHeaderContractTests(SimpleTestCase):
    def setUp(self):
        self.base_dir = Path(settings.BASE_DIR)
        self.app_source = (self.base_dir / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
        self.auth_source = (self.base_dir / "frontend" / "src" / "components" / "AuthGate.vue").read_text(encoding="utf-8")
        self.tier_badge_source = (self.base_dir / "frontend" / "src" / "components" / "AccountTierBadge.vue").read_text(encoding="utf-8")
        self.popover_source = (self.base_dir / "frontend" / "src" / "components" / "AccountPopover.vue").read_text(encoding="utf-8")
        self.center_source = (self.base_dir / "frontend" / "src" / "components" / "PersonalCenter.vue").read_text(encoding="utf-8")

    def test_visible_brand_uses_huntalpha_hub_and_real_account_state(self):
        self.assertIn("HuntAlphaLogo", self.app_source)
        self.assertIn("<span class=\"brand-name\">HuntAlpha</span>", self.app_source)
        self.assertIn("<small class=\"brand-hub\">HUB</small>", self.app_source)
        self.assertIn("<AccountPopover v-else :user=\"user\"", self.app_source)
        self.assertIn("<div v-if=\"visitor\" class=\"visitor-account\">", self.app_source)
        self.assertNotIn("visitor ? t('visitor') : user.name", self.app_source)
        self.assertIn("HuntAlphaLogo", self.auth_source)
        self.assertIn("<span>HuntAlpha</span><small>HUB</small>", self.auth_source)
        self.assertNotIn("QuantScope", self.app_source)
        self.assertNotIn("QuantScope", self.auth_source)
        self.assertNotIn("visitor ? t('visitor') : t('pro')", self.app_source)
        self.assertNotIn("visitor ? t('visitorAi') : user.name", self.app_source)

    def test_logo_is_local_original_svg_without_external_dependency_or_letter_mark(self):
        logo_path = self.base_dir / "frontend" / "public" / "huntalpha-wolf.svg"
        self.assertTrue(logo_path.is_file())
        logo_source = logo_path.read_text(encoding="utf-8")
        self.assertIn("<svg", logo_source)
        self.assertIn("#56D6AF", logo_source)
        self.assertNotRegex(logo_source, r"(?:href|xlink:href)=[\"']https?://")
        self.assertNotRegex(logo_source, r">\s*(?:A|H|HA)\s*<")

    def test_branding_keeps_task_004_and_004_1_runtime_contracts(self):
        self.assertIn("visibleMarkets", self.app_source)
        self.assertIn("/api/market-index-snapshots/", self.app_source)
        self.assertIn("const endpoint = search ? `symbols/${market.value.code}/` : 'watchlist/'", self.app_source)
        self.assertIn("toggleWatchlist", self.app_source)
        self.assertIn("@click.stop=\"toggleWatchlist(item)\"", self.app_source)
        self.assertIn("`${API_BASE}/api/${endpoint}?${params}`", self.app_source)

    def test_account_tier_badge_is_embedded_and_supports_free_and_pro(self):
        self.assertIn("AccountPopover", self.app_source)
        self.assertIn("<AccountTierBadge", self.popover_source)
        self.assertIn(":tier=\"user.tier\"", self.popover_source)
        self.assertIn(":tier-label=\"user.tier_label\"", self.popover_source)
        self.assertIn(":watchlist-limit=\"user.watchlist_limit\"", self.popover_source)
        self.assertIn(":user-name=\"user.name\"", self.popover_source)
        self.assertIn(":avatar-url=\"user.avatar_url\"", self.popover_source)
        self.assertIn("account-trigger", self.popover_source)
        self.assertIn('aria-haspopup="dialog"', self.popover_source)
        self.assertIn('viewBox="0 0 54 48"', self.tier_badge_source)
        self.assertIn('class="crown"', self.tier_badge_source)
        self.assertIn('class="avatar-circle"', self.tier_badge_source)
        self.assertIn('<circle class="avatar-circle"', self.tier_badge_source)
        self.assertIn('class="ribbon"', self.tier_badge_source)
        self.assertIn('class="ribbon-label" x="27" y="44.3"', self.tier_badge_source)
        self.assertIn('>{{ displayLabel }}</text>', self.tier_badge_source)
        self.assertIn('v-if="avatarUrl"', self.tier_badge_source)
        self.assertIn('v-else-if="avatarInitial"', self.tier_badge_source)
        self.assertIn('class="avatar-fallback"', self.tier_badge_source)
        self.assertIn("tier-free .crown", self.tier_badge_source)
        self.assertIn("tier-pro .crown", self.tier_badge_source)
        self.assertNotIn("avatar-ring", self.tier_badge_source)
        self.assertNotIn("avatar-bg", self.tier_badge_source)
        self.assertNotRegex(self.tier_badge_source, r"https?://")
        self.assertNotRegex(self.tier_badge_source, r"[\U0001F300-\U0001FAFF]")

    def test_account_menu_and_personal_center_contract(self):
        combined = self.app_source + self.popover_source + self.center_source
        self.assertIn("/api/account/summary/", combined)
        self.assertIn("/api/account/change-password/", self.center_source)
        self.assertIn("window.addEventListener('popstate', handleRouteChange)", self.app_source)
        self.assertIn("window.history.pushState", self.app_source)
        self.assertIn("/account", self.app_source)
        self.assertIn("个人中心", self.popover_source)
        self.assertIn("退出登录", self.popover_source)
        self.assertIn("prefers-reduced-motion:reduce", combined)
        self.assertEqual(self.center_source.count("{ key:"), 5)
        self.assertNotIn("reset_at", combined)
        self.assertNotIn("next_reset_at", combined)
        self.assertNotIn("每月重置", combined)

    def test_account_summary_retry_only_caches_success(self):
        success_index = self.popover_source.index('summary.value = payload')
        loaded_index = self.popover_source.index('summaryLoaded.value = true')
        finally_index = self.popover_source.index('.finally(() => { loading.value = false })')
        self.assertLess(success_index, loaded_index)
        self.assertLess(loaded_index, finally_index)
        self.assertIn('summaryLoaded.value = false', self.popover_source)
        self.assertNotIn('finally(() => { loading.value = false; summaryLoaded.value = true })', self.popover_source)
        self.assertNotIn('setInterval', self.popover_source)

    def test_account_center_profile_preferences_and_live_terminal_state_contract(self):
        self.assertIn(':watchlist-total="watchlistTotal"', self.app_source)
        self.assertIn(':watchlist-limit="watchlistLimit"', self.app_source)
        self.assertIn(':watchlist-remaining="watchlistRemaining"', self.app_source)
        self.assertIn('marketColorTokens', self.app_source)
        self.assertIn(':market-color-tokens="marketColorTokens"', self.app_source)
        header_source = self.app_source.split('<header>', 1)[1].split('</header>', 1)[0]
        controls_source = header_source.split('<div class="header-account-controls">', 1)[1].split('</div></header>', 1)[0]
        self.assertIn('<div class="header-account-controls">', header_source)
        self.assertIn('<div v-if="visitor" class="visitor-account">', controls_source)
        self.assertIn('<AccountPopover v-else', controls_source)
        self.assertIn('<select class="terminal-language"', controls_source)
        self.assertLess(controls_source.index('<AccountPopover v-else'), controls_source.index('<select class="terminal-language"'))
        self.assertIn('.header-account-controls{', self.app_source)
        self.assertIn('margin-left:auto', self.app_source.split('.header-account-controls{', 1)[1].split('}', 1)[0])
        self.assertIn('/api/account/profile/', self.center_source)
        self.assertIn('/api/account/avatar/', self.center_source)
        self.assertIn('/api/account/preferences/', self.center_source)
        self.assertIn('price_color_mode', self.center_source)
        self.assertIn('default_market', self.center_source)
        self.assertIn('default_period', self.center_source)
        self.assertNotIn('setLocale', self.center_source)
        self.assertNotIn('languages', self.center_source)
        self.assertIn('applyOptions', (self.base_dir / 'frontend' / 'src' / 'components' / 'MarketChart.vue').read_text(encoding='utf-8'))

    def test_header_right_controls_and_worklog_keep_account_security_out_of_realtime_task(self):
        worklog_source = (self.base_dir / 'docs' / 'product-worklog.md').read_text(encoding='utf-8')
        task_lines = worklog_source.splitlines()
        task_005_1_3 = next(index for index, line in enumerate(task_lines) if line.startswith('### Task 005.1.3'))
        task_005_1_4 = next(index for index, line in enumerate(task_lines) if line.startswith('### Task 005.1.4'))
        self.assertIn('状态：`IN_PROGRESS`', '\n'.join(task_lines[task_005_1_3:task_005_1_4]))
        self.assertIn('状态：`PLANNED`', '\n'.join(task_lines[task_005_1_4:]))
        self.assertIn('Provider-neutral realtime architecture', '\n'.join(task_lines[task_005_1_3:task_005_1_4]))


class WatchlistModelAndApiTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        User = get_user_model()
        self.user_a = User.objects.create_user(username="watch-a@example.com", email="watch-a@example.com", password="safe-password-123")
        self.user_b = User.objects.create_user(username="watch-b@example.com", email="watch-b@example.com", password="safe-password-123")
        self.cn_symbols = [self.make_symbol(f"SH.6005{index:02d}", "cn") for index in range(5)]
        self.hk_symbols = [self.make_symbol(f"HK.000{index:02d}", "hk") for index in range(3)]
        self.us_symbols = [self.make_symbol(f"US.TEST{index}", "us") for index in range(4)]
        self.inactive = self.make_symbol("SH.609999", "cn", active=False)

    @staticmethod
    def make_symbol(code, market, active=True):
        return MarketSymbol.objects.create(
            code=code,
            name=f"测试证券 {code}",
            market=market,
            exchange=market.upper(),
            security_type="STOCK",
            active=active,
            provider="test-provider",
            provider_symbol=code,
        )

    def csrf_headers(self):
        response = self.client.get("/api/csrf/")
        self.assertEqual(response.status_code, 200)
        return {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def post_watchlist(self, code, headers=None):
        return self.client.post(
            "/api/watchlist/",
            data=json.dumps({"code": code}),
            content_type="application/json",
            **(headers or self.csrf_headers()),
        )

    def test_entry_binds_real_user_and_symbol_and_unique_constraint(self):
        entry = WatchlistEntry.objects.create(user=self.user_a, symbol=self.cn_symbols[0])
        self.assertEqual(entry.user, self.user_a)
        self.assertEqual(entry.symbol, self.cn_symbols[0])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WatchlistEntry.objects.create(user=self.user_a, symbol=self.cn_symbols[0])
        WatchlistEntry.objects.create(user=self.user_b, symbol=self.cn_symbols[0])
        self.assertEqual(WatchlistEntry.objects.filter(symbol=self.cn_symbols[0]).count(), 2)

    def test_user_delete_cascades_entries_but_keeps_symbol(self):
        WatchlistEntry.objects.create(user=self.user_a, symbol=self.cn_symbols[0])
        self.user_a.delete()
        self.assertFalse(WatchlistEntry.objects.filter(symbol=self.cn_symbols[0]).exists())
        self.assertTrue(MarketSymbol.objects.filter(pk=self.cn_symbols[0].pk).exists())

    def test_watched_symbol_is_protected_from_physical_delete(self):
        WatchlistEntry.objects.create(user=self.user_a, symbol=self.cn_symbols[0])
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.cn_symbols[0].delete()

    def test_get_isolated_and_total_is_global_across_markets(self):
        WatchlistEntry.objects.bulk_create([
            WatchlistEntry(user=self.user_a, symbol=self.cn_symbols[0]),
            WatchlistEntry(user=self.user_a, symbol=self.hk_symbols[0]),
            WatchlistEntry(user=self.user_a, symbol=self.us_symbols[0]),
            WatchlistEntry(user=self.user_b, symbol=self.us_symbols[1]),
        ])
        self.client.force_login(self.user_a)
        payload = self.client.get("/api/watchlist/?market=cn").json()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["limit"], 10)
        self.assertEqual(payload["remaining"], 7)
        self.assertEqual([item["code"] for item in payload["items"]], [self.cn_symbols[0].code])
        self.assertNotIn("formula_source", payload["items"][0])
        self.client.force_login(self.user_b)
        other = self.client.get("/api/watchlist/?market=us").json()
        self.assertEqual([item["code"] for item in other["items"]], [self.us_symbols[1].code])

    def test_post_requires_csrf_and_creates_only_real_active_stock(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            "/api/watchlist/",
            data=json.dumps({"code": self.cn_symbols[0].code}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        response = self.post_watchlist(self.cn_symbols[0].code)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["item"]["code"], self.cn_symbols[0].code)
        self.assertEqual(WatchlistEntry.objects.filter(user=self.user_a).count(), 1)

    def test_duplicate_post_is_idempotent(self):
        self.client.force_login(self.user_a)
        first = self.post_watchlist(self.cn_symbols[0].code)
        second = self.post_watchlist(self.cn_symbols[0].code)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "already_exists")
        self.assertEqual(second.json()["total"], 1)
        self.assertEqual(WatchlistEntry.objects.filter(user=self.user_a).count(), 1)

    def test_create_serializes_quota_check_on_locked_user_row(self):
        source = inspect.getsource(_watchlist_create)
        lock_position = source.index("locked_user = get_user_model().objects.select_for_update()")
        duplicate_position = source.index('WatchlistEntry.objects.select_related("symbol")', lock_position)
        quota_position = source.index("totals = _watchlist_totals_for_user(locked_user)", duplicate_position)
        create_position = source.index("WatchlistEntry.objects.create(user=locked_user", quota_position)

        self.assertLess(lock_position, duplicate_position)
        self.assertLess(duplicate_position, quota_position)
        self.assertLess(quota_position, create_position)
        constraints = [
            constraint for constraint in WatchlistEntry._meta.constraints
            if constraint.name == "core_watch_user_symbol_uniq"
        ]
        self.assertEqual(len(constraints), 1)
        self.assertEqual(tuple(constraints[0].fields), ("user", "symbol"))

    def test_quota_is_backend_enforced_and_shared_across_markets(self):
        entries = self.cn_symbols[:4] + self.hk_symbols + self.us_symbols[:3]
        WatchlistEntry.objects.bulk_create([WatchlistEntry(user=self.user_a, symbol=symbol) for symbol in entries])
        self.client.force_login(self.user_a)
        response = self.post_watchlist(self.us_symbols[3].code)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "watchlist_limit_reached")
        self.assertEqual(response.json()["total"], 10)
        self.assertEqual(response.json()["limit"], 10)
        self.assertEqual(WatchlistEntry.objects.filter(user=self.user_a).count(), 10)

    def test_free_account_can_add_ten_entries_before_quota_is_reached(self):
        entries = self.cn_symbols[:4] + self.hk_symbols + self.us_symbols[:3]
        self.client.force_login(self.user_a)
        responses = [self.post_watchlist(symbol.code) for symbol in entries]
        self.assertTrue(all(response.status_code == 201 for response in responses))
        self.assertEqual(responses[-1].json()["total"], 10)
        self.assertEqual(responses[-1].json()["remaining"], 0)
        self.assertEqual(WatchlistEntry.objects.filter(user=self.user_a).count(), 10)

    def test_inactive_and_unknown_symbols_are_rejected(self):
        self.client.force_login(self.user_a)
        inactive = self.post_watchlist(self.inactive.code)
        missing = self.post_watchlist("SH.000000")
        self.assertEqual(inactive.status_code, 409)
        self.assertEqual(inactive.json()["code"], "symbol_inactive")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["code"], "symbol_not_found")
        self.assertEqual(WatchlistEntry.objects.count(), 0)

    def test_visitor_cannot_persist_watchlist_and_crypto_preview_is_not_collectible(self):
        self.client.post("/api/auth/guest/")
        response = self.post_watchlist(self.cn_symbols[0].code)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "login_required")
        crypto = self.client.get("/api/watchlist/?market=crypto").json()
        self.assertEqual(crypto["status"], "login_required")
        self.assertEqual(crypto["items"], [])
        self.assertEqual(WatchlistEntry.objects.count(), 0)

    def test_delete_isolated_to_current_user_and_updates_count(self):
        WatchlistEntry.objects.create(user=self.user_b, symbol=self.cn_symbols[0])
        self.client.force_login(self.user_a)
        response = self.client.delete(
            f"/api/watchlist/{self.cn_symbols[0].code}/",
            **self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(WatchlistEntry.objects.filter(user=self.user_b, symbol=self.cn_symbols[0]).exists())
        WatchlistEntry.objects.create(user=self.user_a, symbol=self.cn_symbols[0])
        response = self.client.delete(
            f"/api/watchlist/{self.cn_symbols[0].code}/",
            **self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

    def test_search_returns_watchlisted_annotation_without_private_fields(self):
        WatchlistEntry.objects.create(user=self.user_a, symbol=self.cn_symbols[0])
        self.client.force_login(self.user_a)
        payload = self.client.get(f"/api/symbols/cn/?q={self.cn_symbols[0].code}&limit=10&page=1").json()
        self.assertEqual(payload["items"][0]["watchlisted"], True)
        self.assertNotIn("formula_source", payload["items"][0])
        self.assertEqual(payload["watchlist_total"], 1)


class FakeRealtimeProvider:
    provider_name = "test-provider"

    def __init__(self, snapshot=None, error=None, health_started=None, health_release=None):
        self.snapshot = snapshot
        self.error = error
        self.callbacks = {}
        self.subscribe_calls = []
        self.unsubscribe_calls = []
        self.status = "live"
        self.health_calls = 0
        self.health_started = health_started
        self.health_release = health_release

    def subscribe(self, symbol, period, callback):
        self.subscribe_calls.append((symbol, period))
        if self.error:
            raise self.error
        self.callbacks[(symbol.upper(), period)] = callback
        return {"mode": "streaming"}

    def unsubscribe(self, symbol, period):
        self.unsubscribe_calls.append((symbol, period))
        self.callbacks.pop((symbol.upper(), period), None)

    def latest_snapshot(self, symbol, period):
        return self.snapshot

    def close(self):
        self.callbacks.clear()

    def health_check(self):
        self.health_calls += 1
        if self.health_started:
            self.health_started.set()
        if self.health_release:
            self.health_release.wait(timeout=1)
        return self.status

    def emit(self, bar):
        self.callbacks[(bar.symbol.upper(), bar.period)](bar)


class RealtimeCoreContractTests(TestCase):
    def bar(self, time_value, close=10, high=11, low=9, sequence=None, volume=100, amount=None, turnover_rate=None, **kwargs):
        return NormalizedBar(
            provider="test-provider", market="cn", symbol="SH.600519", period="1分",
            time=time_value, open=10, high=high, low=low, close=close, volume=volume,
            amount=amount, turnover_rate=turnover_rate, sequence=sequence, **kwargs,
        )

    def test_first_consumer_creates_one_provider_subscription(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        first = registry.subscribe("SH.600519", "1分")
        second = registry.subscribe("SH.600519", "1分")
        stats = registry.stats(first.key)
        self.assertEqual(len(provider.subscribe_calls), 1)
        self.assertEqual(stats["consumer_count"], 2)
        self.assertEqual(stats["provider_subscription_count"], 1)
        registry.unsubscribe(first)
        self.assertEqual(registry.stats(second.key)["consumer_count"], 1)
        registry.unsubscribe(second)
        time.sleep(0.03)
        self.assertEqual(provider.unsubscribe_calls, [("SH.600519", "1分")])

    def test_provider_identity_is_not_hardcoded_in_registry_key(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        consumer = registry.subscribe("SH.600519", "1分")
        self.assertEqual(consumer.key[0], "test-provider")
        registry.unsubscribe(consumer)
        time.sleep(0.03)

    def test_failed_initial_subscribe_removes_entry_and_retry_subscribes_again(self):
        provider = FakeRealtimeProvider(error=RuntimeError("first subscription failed"))
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=30)
        with self.assertRaises(RealtimeProviderError):
            registry.subscribe("SH.600519", "1分")
        self.assertEqual(registry.stats()["active_keys"], 0)
        self.assertEqual(registry.stats()["provider_subscription_count"], 0)
        provider.error = None
        consumer = registry.subscribe("SH.600519", "1分")
        self.assertEqual(len(provider.subscribe_calls), 2)
        self.assertEqual(registry.stats(consumer.key)["provider_subscription_count"], 1)
        registry.unsubscribe(consumer)
        registry.close()

    def test_second_consumer_receives_the_shared_provider_event(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        first = registry.subscribe("SH.600519", "1分")
        second = registry.subscribe("SH.600519", "1分")
        provider.emit(self.bar(100))
        first_events = [first.get(timeout=0.2) for _ in range(2)]
        second_events = [second.get(timeout=0.2) for _ in range(2)]
        self.assertTrue(any(event["type"] == "snapshot" for event in first_events))
        self.assertTrue(any(event["type"] == "snapshot" for event in second_events))
        registry.unsubscribe(first)
        registry.unsubscribe(second)

    def test_grace_unsubscribe_is_cancelled_by_a_new_consumer(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0.08)
        first = registry.subscribe("SH.600519", "1分")
        registry.unsubscribe(first)
        second = registry.subscribe("SH.600519", "1分")
        time.sleep(0.12)
        self.assertEqual(provider.unsubscribe_calls, [])
        registry.unsubscribe(second)
        time.sleep(0.1)

    def test_registry_health_probe_is_shared_and_throttled(self):
        started = threading.Event()
        release = threading.Event()
        provider = FakeRealtimeProvider(health_started=started, health_release=release)
        registry = RealtimeRegistry(
            provider=provider, state_store=RealtimeStateStore(), grace_seconds=0, health_interval_seconds=5,
        )
        consumer = registry.subscribe("SH.600519", "1分")
        results = []
        first = threading.Thread(target=lambda: results.append(registry.health_check()))
        second = threading.Thread(target=lambda: results.append(registry.health_check()))
        first.start()
        self.assertTrue(started.wait(timeout=1))
        second.start()
        second.join(timeout=1)
        release.set()
        first.join(timeout=1)
        self.assertEqual(provider.health_calls, 1)
        self.assertEqual(results, ["live", "live"])
        registry.unsubscribe(consumer)

    def test_registry_does_not_probe_without_consumers(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        self.assertEqual(registry.health_check(), "live")
        self.assertEqual(provider.health_calls, 0)

    def test_reconnecting_status_is_published_without_fake_bar(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        consumer = registry.subscribe("SH.600519", "1分")
        provider.callbacks[("SH.600519", "1分")]({"status": "reconnecting", "error": "connection lost"})
        events = [consumer.get(timeout=0.2) for _ in range(2)]
        status = next(event for event in events if event["type"] == "status" and event["status"] == "reconnecting")
        self.assertIsNone(status["bar"])
        registry.unsubscribe(consumer)

    def test_new_consumer_receives_latest_shared_snapshot(self):
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        first = registry.subscribe("SH.600519", "1分")
        provider.emit(self.bar(100))
        first.get(timeout=0.2)
        first.get(timeout=0.2)
        second = registry.subscribe("SH.600519", "1分")
        events = [second.get(timeout=0.2) for _ in range(2)]
        snapshot = next(event for event in events if event["type"] == "snapshot")
        self.assertEqual(snapshot["bar"]["time"], 100)
        registry.unsubscribe(first)
        registry.unsubscribe(second)

    def test_sequence_older_than_current_same_timestamp_is_stale(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100, sequence=2))
        state, result = store.apply_bar(key, self.bar(100, close=99, sequence=1))
        self.assertFalse(result.accepted)
        self.assertEqual(state.current_bar.close, 10)

    def test_unavailable_status_is_explicit_and_has_no_bar(self):
        store = RealtimeStateStore()
        key = ("futu-opend", "SH.600519", "1分")
        state = store.set_status(key, "unavailable", mode="streaming", source="futu-opend", error="OpenD unavailable")
        self.assertEqual(state.status, "unavailable")
        self.assertIsNone(state.current_bar)
        self.assertEqual(state.error, "OpenD unavailable")

    def test_status_changes_also_have_monotonic_revisions(self):
        store = RealtimeStateStore()
        key = ("futu-opend", "SH.600519", "1分")
        connecting = store.set_status(key, "connecting", source="futu-opend")
        live = store.set_status(key, "live", source="futu-opend")
        self.assertLess(connecting.revision, live.revision)

    def test_state_payload_and_calculation_snapshot_share_process_epoch(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        state, _ = store.apply_bar(key, self.bar(100))
        snapshot = store.capture(key)
        self.assertTrue(store.epoch)
        self.assertEqual(state.epoch, store.epoch)
        self.assertEqual(state.to_dict()["epoch"], store.epoch)
        self.assertEqual(snapshot.epoch, store.epoch)

    def test_lower_revision_from_new_epoch_is_a_new_authority_generation(self):
        first = RealtimeStateStore()
        second = RealtimeStateStore()
        self.assertNotEqual(first.epoch, second.epoch)
        first_key = ("test-provider", "SH.600519", "1分")
        second_key = ("test-provider", "SH.600519", "1分")
        for index in range(500):
            first.apply_bar(first_key, self.bar(100 + index))
        first_snapshot = first.capture(first_key)
        second_snapshot = second.capture(second_key)
        self.assertEqual(first_snapshot.revision, 500)
        self.assertEqual(second_snapshot.revision, 0)
        self.assertNotEqual(first_snapshot.epoch, second_snapshot.epoch)

    def test_formula_flight_isolated_by_symbol_period_and_formula(self):
        coordinator = FormulaFlightCoordinator()
        self.assertTrue(coordinator.begin(("A", "1分", "MA"), 1))
        self.assertTrue(coordinator.begin(("B", "1分", "MA"), 1))
        self.assertTrue(coordinator.begin(("A", "5分", "MA"), 1))
        self.assertTrue(coordinator.begin(("A", "1分", "RSI"), 1))

    def test_visitor_can_use_stream_boundary_but_not_anonymous(self):
        client = Client()
        client.post("/api/auth/guest/")
        provider = FakeRealtimeProvider()
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        with patch("core.views.get_realtime_registry", return_value=registry):
            response = client.get("/api/realtime/market-stream/SH.600519/?period=1分")
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_realtime_period_contract_rejects_intraday_semantics(self):
        client = Client()
        client.post("/api/auth/guest/")
        response = client.get("/api/realtime/market-stream/SH.600519/?period=分时")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["mode"], "unavailable")

    def test_same_timestamp_updates_current_bar_without_replacing_series_contract(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        first, result = store.apply_bar(key, self.bar(100, close=10, high=11, low=9))
        second, result = store.apply_bar(key, self.bar(100, close=12, high=12, low=8))
        self.assertEqual(result.relation, "updated")
        self.assertEqual(first.revision + 1, second.revision)
        self.assertEqual(second.current_bar.close, 12)
        self.assertEqual(second.current_bar.high, 12)
        self.assertEqual(second.current_bar.low, 8)

    def test_live_same_timestamp_high_is_monotonic_and_low_is_monotonic(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100, high=12, low=8, volume=100))
        state, result = store.apply_bar(key, self.bar(100, high=10, low=9, volume=120, close=11))
        self.assertTrue(result.accepted)
        self.assertEqual(state.current_bar.high, 12)
        self.assertEqual(state.current_bar.low, 8)
        self.assertEqual(state.current_bar.volume, 120)

    def test_live_same_timestamp_stale_cumulative_volume_is_rejected(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100, volume=200, amount=300))
        state, result = store.apply_bar(key, self.bar(100, volume=150, amount=250, close=12))
        self.assertFalse(result.accepted)
        self.assertEqual(result.relation, "suspected_stale")
        self.assertEqual(state.current_bar.volume, 200)

    def test_authoritative_reconcile_can_correct_high_low_and_volume(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100, high=120, low=80, volume=200))
        corrected = self.bar(100, high=110, low=90, volume=180, event_kind="reconcile")
        state, result = store.apply_bar(key, corrected)
        self.assertEqual(result.relation, "reconciled")
        self.assertEqual(state.current_bar.high, 110)
        self.assertEqual(state.current_bar.low, 90)
        self.assertEqual(state.current_bar.volume, 180)

    def test_provider_time_key_is_not_used_as_event_sequence(self):
        source = Path(settings.BASE_DIR / "core" / "realtime" / "futu_provider.py").read_text(encoding="utf-8")
        self.assertIn("sequence=None", source)
        self.assertNotIn("sequence=getattr(row, \"time_key\"", source)

    def test_new_timestamp_appends_and_closes_previous_bar(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100))
        state, result = store.apply_bar(key, self.bar(101, close=11))
        self.assertEqual(result.relation, "appended")
        self.assertEqual(state.current_bar.time, 101)
        self.assertTrue(state.last_closed_bar.is_closed)
        self.assertEqual(state.last_closed_bar.time, 100)

    def test_older_event_is_rejected_and_revision_does_not_go_back(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        current, _ = store.apply_bar(key, self.bar(101, close=11))
        stale, result = store.apply_bar(key, self.bar(100, close=9))
        self.assertFalse(result.accepted)
        self.assertEqual(result.relation, "stale")
        self.assertEqual(stale.revision, current.revision)
        self.assertEqual(stale.current_bar.time, 101)

    def test_duplicate_event_is_idempotent(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        first, _ = store.apply_bar(key, self.bar(100, sequence="a"))
        second, result = store.apply_bar(key, self.bar(100, sequence="a"))
        self.assertFalse(result.accepted)
        self.assertEqual(first.revision, second.revision)

    def test_revision_is_monotonic_for_state_changes(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        revisions = [store.apply_bar(key, self.bar(index))[0].revision for index in (100, 101, 102)]
        self.assertEqual(revisions, sorted(revisions))
        self.assertEqual(len(set(revisions)), 3)

    def test_missing_amount_and_turnover_rate_remain_none_and_real_zero_survives(self):
        bar = self.bar(100, amount=None, turnover_rate=None, volume=0)
        self.assertIsNone(bar.amount)
        self.assertIsNone(bar.turnover_rate)
        self.assertEqual(bar.volume, 0)
        result = merge_realtime_bar(None, bar)
        self.assertEqual(result.bar.volume, 0)

    def test_market_time_conversion_does_not_use_host_timezone(self):
        cn = provider_time_to_timestamp("2026-09-04 09:30:00", "cn")
        us = provider_time_to_timestamp("2026-09-04 09:30:00", "us")
        self.assertNotEqual(cn, us)
        self.assertEqual(cn, 1788485400)

    def test_provider_failure_has_no_test_provider_runtime_fallback(self):
        provider = FakeRealtimeProvider(error=RuntimeError("provider unavailable"))
        registry = RealtimeRegistry(provider=provider, state_store=RealtimeStateStore(), grace_seconds=0)
        with self.assertRaises(RealtimeProviderError):
            registry.subscribe("SH.600519", "1分")
        time.sleep(0.03)
        self.assertEqual(registry.stats()["active_keys"], 0)
        self.assertTrue(FutuRealtimeProvider.provider_name == "futu-opend")

    def test_formula_flight_keeps_only_latest_pending_revision(self):
        coordinator = FormulaFlightCoordinator()
        key = ("SH.600519", "1分", "fixture")
        self.assertTrue(coordinator.begin(key, 100))
        self.assertFalse(coordinator.begin(key, 101))
        self.assertFalse(coordinator.begin(key, 104))
        self.assertEqual(coordinator.state(key).pending_revision, 104)
        self.assertEqual(coordinator.finish(key, 100), 104)
        self.assertEqual(coordinator.finish(key, 104), None)

    def test_formula_stale_revision_is_rejected(self):
        coordinator = FormulaFlightCoordinator()
        key = ("SH.600519", "1分", "fixture")
        coordinator.begin(key, 100)
        self.assertTrue(coordinator.is_stale(key, 100, 101))
        self.assertFalse(coordinator.is_stale(key, 100, 100))

    def test_calculation_snapshot_remains_atomic_when_state_advances(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100, close=10))
        captured = store.capture(key)
        store.apply_bar(key, self.bar(100, close=11))
        self.assertEqual(captured.revision, 1)
        self.assertEqual(captured.current_bar.close, 10)
        self.assertEqual(store.capture(key).revision, 2)

    def test_formula_history_is_bounded_by_captured_current_bar(self):
        store = RealtimeStateStore()
        key = ("test-provider", "SH.600519", "1分")
        store.apply_bar(key, self.bar(100, close=100))
        snapshot = store.capture(key)
        history = [
            {"time": 100, "open": 100, "high": 101, "low": 99, "close": 105, "volume": 10},
            {"time": 101, "open": 101, "high": 102, "low": 100, "close": 102, "volume": 20},
        ]
        bounded = merge_calculation_snapshot_rows(history, snapshot)
        self.assertEqual([row["time"] for row in bounded], [100])
        self.assertEqual(bounded[0]["close"], 100)
        self.assertEqual(bounded[0]["volume"], 100)

    def test_indicator_response_revision_matches_captured_calculation_snapshot(self):
        user = get_user_model().objects.create_user(username="realtime-formula-user", password="Valid-password-123")
        client = Client()
        client.force_login(user)
        provider = FakeRealtimeProvider()
        store = RealtimeStateStore()
        registry = RealtimeRegistry(provider=provider, state_store=store, grace_seconds=0)
        key = registry.key_for("SH.600519", "1分")
        store.apply_bar(key, self.bar(100, close=10))
        item = SimpleNamespace(code="TEST", version=3, name="Public fixture", placement="main", source="PUBLIC_FIXTURE")
        public_bars = [{"time": 100, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}]
        completed = SimpleNamespace(stdout=json.dumps({"lines": [], "sticks": [], "markers": [], "fixedTexts": [], "engine": "tongdaxin"}))
        with patch("core.views.get_realtime_registry", return_value=registry), \
             patch("core.views.Formula.objects.get", return_value=item), \
             patch("core.views.history_bars", return_value=(public_bars, None, None)), \
             patch("core.views.subprocess.run", return_value=completed):
            formula_run_registry.clear()
            response = client.get("/api/indicator-render/TEST/SH.600519/?period=1%E5%88%86&count=100&revision=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(response.json()["epoch"], store.epoch)
        self.assertNotIn("PUBLIC_FIXTURE", response.content.decode("utf-8"))

    def test_formula_run_registry_deduplicates_same_revision_subprocess(self):
        registry = FormulaRunRegistry()
        input_hash = calculation_input_fingerprint([{"time": 7, "close": 100}], 123.0)
        key = ("SH.600519", "1分", "FORMULA", 1, 7, input_hash)
        started = threading.Event()
        release = threading.Event()
        calls = []
        results = []

        def runner():
            calls.append(True)
            started.set()
            release.wait(timeout=1)
            return {"drawing": "shared"}

        def invoke():
            results.append(registry.run(key, 7, runner))

        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke)
        first.start()
        self.assertTrue(started.wait(timeout=1))
        second.start()
        release.set()
        first.join(timeout=1)
        second.join(timeout=1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [{"drawing": "shared"}, {"drawing": "shared"}])
        self.assertEqual(registry.coordinator.state(key).active_revision, None)

        def fresh_runner():
            calls.append(True)
            return {"drawing": "fresh"}

        self.assertEqual(registry.run(key, 7, fresh_runner), {"drawing": "fresh"})
        self.assertEqual(len(calls), 2)

    def test_formula_input_fingerprint_separates_real_inputs(self):
        bars_a = [{"time": 100, "close": 10, "volume": 100}]
        bars_b = [{"time": 100, "close": 11, "volume": 100}]
        hash_a = calculation_input_fingerprint(bars_a, 1000.0)
        self.assertEqual(hash_a, calculation_input_fingerprint(bars_a, 1000.0))
        self.assertNotEqual(hash_a, calculation_input_fingerprint(bars_b, 1000.0))
        self.assertNotEqual(hash_a, calculation_input_fingerprint(bars_a, 1001.0))
        self.assertNotIn("source", calculation_input_fingerprint.__code__.co_varnames)

        registry = FormulaRunRegistry()
        calls = []

        def runner():
            calls.append(True)
            return {"drawing": len(calls)}

        base = ("test-provider", "SH.600519", "1分", "FORMULA", 1, "epoch", 7)
        registry.run(base + (hash_a,), 7, runner)
        registry.run(base + (calculation_input_fingerprint(bars_b, 1000.0),), 7, runner)
        registry.run(base + (calculation_input_fingerprint(bars_a, 1001.0),), 7, runner)
        self.assertEqual(len(calls), 3)

    def test_formula_registry_inflight_error_is_shared_but_not_cached(self):
        registry = FormulaRunRegistry()
        started = threading.Event()
        release = threading.Event()
        calls = []

        def runner():
            calls.append(True)
            started.set()
            release.wait(timeout=1)
            raise RuntimeError("fixture failure")

        errors = []

        def invoke():
            try:
                registry.run(("SH.600519", "1分", "FORMULA", 1, 8), 8, runner)
            except RuntimeError as exc:
                errors.append(str(exc))

        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke)
        first.start()
        self.assertTrue(started.wait(timeout=1))
        second.start()
        release.set()
        first.join(timeout=1)
        second.join(timeout=1)
        self.assertEqual(calls, [True])
        self.assertEqual(errors, ["fixture failure", "fixture failure"])
        with self.assertRaises(RuntimeError):
            registry.run(("SH.600519", "1分", "FORMULA", 1, 8), 8, runner)
        self.assertEqual(len(calls), 2)

    def test_provider_reconnect_failure_publishes_terminal_unavailable(self):
        class FailingContext:
            def set_handler(self, handler):
                self.handler = handler

            def get_global_state(self):
                return -1, "health failed"

            def close(self):
                return None

            def subscribe(self, *args, **kwargs):
                return RET_OK, ""

            def get_cur_kline(self, *args, **kwargs):
                return -1, "snapshot failed"

        events = []
        provider = FutuRealtimeProvider(context_factory=FailingContext)
        provider._context = FailingContext()
        provider._callbacks[("SH.600519", "1分")] = {events.append}
        provider._status = "live"
        self.assertEqual(provider.health_check(), "unavailable")
        self.assertEqual(provider.status, "unavailable")
        self.assertEqual(events[-1]["status"], "unavailable")

    def test_provider_reconnect_rolls_back_partial_subscription_and_retries_all_keys(self):
        class CandidateContext:
            def __init__(self, fail_symbol=None):
                self.fail_symbol = fail_symbol
                self.subscribe_calls = []
                self.closed = False

            def set_handler(self, handler):
                self.handler = handler

            def close(self):
                self.closed = True

            def subscribe(self, symbols, subtypes, **kwargs):
                symbol = symbols[0]
                self.subscribe_calls.append(symbol)
                if symbol == self.fail_symbol:
                    return -1, "subscribe failed"
                return RET_OK, ""

            def unsubscribe(self, symbols, subtypes):
                return RET_OK, ""

            def get_global_state(self):
                return RET_OK, ""

        failed_candidate = CandidateContext(fail_symbol="US.AAPL")
        recovered_candidate = CandidateContext()
        candidates = [failed_candidate, recovered_candidate]
        snapshot = self.bar(100, close=12)

        class RecoveringProvider(FutuRealtimeProvider):
            def _reconnect_snapshot(self, context, symbol, period):
                return snapshot

        provider = RecoveringProvider(context_factory=lambda: candidates.pop(0))
        old_context = CandidateContext()
        events = []
        with provider._lock:
            provider._context = old_context
            provider._connection_generation = 1
            provider._ready_generation = 1
            provider._generation_subscriptions = {("SH.600519", "1分"), ("US.AAPL", "1分")}
            provider._callbacks = {
                ("SH.600519", "1分"): {events.append},
                ("US.AAPL", "1分"): {events.append},
            }
            provider._status = "live"

        with self.assertRaises(Exception):
            provider.reconnect()
        self.assertEqual(provider.status, "unavailable")
        self.assertIsNone(provider._context)
        self.assertTrue(failed_candidate.closed)
        self.assertEqual(events, [])

        self.assertEqual(provider.health_check(), "live")
        self.assertEqual(recovered_candidate.subscribe_calls, ["SH.600519", "US.AAPL"])
        self.assertEqual(provider._generation_subscriptions, set(provider._callbacks))
        self.assertTrue(any(not isinstance(event, dict) for event in events))
        provider.close()

    def test_provider_reconnect_snapshot_failure_publishes_nothing_and_closes_candidate(self):
        class CandidateContext:
            def __init__(self):
                self.closed = False
                self.subscribe_calls = []

            def set_handler(self, handler):
                self.handler = handler

            def close(self):
                self.closed = True

            def subscribe(self, symbols, subtypes, **kwargs):
                self.subscribe_calls.append(symbols[0])
                return RET_OK, ""

            def get_global_state(self):
                return RET_OK, ""

        candidate = CandidateContext()
        snapshot = self.bar(100)

        class SnapshotFailingProvider(FutuRealtimeProvider):
            def _reconnect_snapshot(self, context, symbol, period):
                if symbol == "US.AAPL":
                    raise RuntimeError("snapshot failed")
                return snapshot

        provider = SnapshotFailingProvider(context_factory=lambda: candidate)
        events = []
        with provider._lock:
            provider._context = CandidateContext()
            provider._connection_generation = 1
            provider._ready_generation = 1
            provider._generation_subscriptions = {("SH.600519", "1分"), ("US.AAPL", "1分")}
            provider._callbacks = {
                ("SH.600519", "1分"): {events.append},
                ("US.AAPL", "1分"): {events.append},
            }
            provider._status = "live"

        with self.assertRaises(Exception):
            provider.reconnect()
        self.assertEqual(provider.status, "unavailable")
        self.assertIsNone(provider._context)
        self.assertTrue(candidate.closed)
        self.assertEqual(events, [])

    def test_health_does_not_promote_incomplete_generation_to_live(self):
        class Context:
            def __init__(self, fail_symbol=None):
                self.fail_symbol = fail_symbol
                self.closed = False

            def set_handler(self, handler):
                self.handler = handler

            def close(self):
                self.closed = True

            def get_global_state(self):
                return RET_OK, ""

            def subscribe(self, symbols, subtypes, **kwargs):
                if symbols[0] == self.fail_symbol:
                    return -1, "subscribe failed"
                return RET_OK, ""

        candidate = Context(fail_symbol="US.AAPL")
        snapshot = self.bar(100)

        class Provider(FutuRealtimeProvider):
            def _reconnect_snapshot(self, context, symbol, period):
                return snapshot

        provider = Provider(context_factory=lambda: candidate)
        with provider._lock:
            provider._context = Context()
            provider._connection_generation = 1
            provider._ready_generation = 1
            provider._generation_subscriptions = {("SH.600519", "1分")}
            provider._callbacks = {
                ("SH.600519", "1分"): {lambda event: None},
                ("US.AAPL", "1分"): {lambda event: None},
            }
            provider._status = "live"

        self.assertEqual(provider.health_check(), "unavailable")
        self.assertNotEqual(provider.status, "live")
        self.assertTrue(candidate.closed)

    def test_context_none_with_active_subscription_retries_after_failure(self):
        class Context:
            def set_handler(self, handler):
                self.handler = handler

            def close(self):
                return None

            def subscribe(self, *args, **kwargs):
                return RET_OK, ""

        factory_calls = []

        def factory():
            factory_calls.append(True)
            if len(factory_calls) == 1:
                raise RuntimeError("OpenD offline")
            return Context()

        class RecoveringProvider(FutuRealtimeProvider):
            def _reconnect_snapshot(self, context, symbol, period):
                return self.snapshot

        provider = RecoveringProvider(context_factory=factory)
        provider.snapshot = self.bar(100)
        events = []
        provider._callbacks[("SH.600519", "1分")] = {events.append}
        self.assertEqual(provider.health_check(), "unavailable")
        self.assertEqual(provider.status, "unavailable")
        self.assertEqual(provider.health_check(), "live")
        self.assertEqual(len(factory_calls), 2)
        self.assertEqual(provider.status, "live")
        self.assertTrue(any(event.get("status") == "live" for event in events if isinstance(event, dict)))
        provider.close()

    def test_stale_health_result_cannot_override_new_connection_generation(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingContext:
            def set_handler(self, handler):
                self.handler = handler

            def close(self):
                return None

            def get_global_state(self):
                started.set()
                release.wait(timeout=1)
                return -1, "old context failed"

        class LiveContext(BlockingContext):
            def get_global_state(self):
                return RET_OK, ""

        provider = FutuRealtimeProvider(context_factory=LiveContext)
        old_context = BlockingContext()
        new_context = LiveContext()
        provider._context = old_context
        provider._callbacks[("SH.600519", "1分")] = {lambda event: None}
        provider._status = "live"
        with provider._lock:
            provider._connection_generation = 1
            provider._ready_generation = 1
            provider._generation_subscriptions = {('SH.600519', '1分')}
        worker = threading.Thread(target=provider.health_check)
        worker.start()
        self.assertTrue(started.wait(timeout=1))
        with provider._lock:
            provider._context = new_context
            provider._connection_generation = 2
            provider._ready_generation = 2
            provider._generation_subscriptions = {('SH.600519', '1分')}
            provider._status = "live"
        release.set()
        worker.join(timeout=1)
        self.assertEqual(provider.status, "live")
        provider.close()

    def test_futu_connection_generation_ignores_old_frame_and_error(self):
        class Context:
            def set_handler(self, handler):
                self.handler = handler

            def close(self):
                return None

        class Frame:
            def itertuples(self, index=False):
                return [SimpleNamespace(
                    code="SH.600519", k_type="K_1M", time_key="2026-09-04 09:30:00",
                    open=10, high=11, low=9, close=10, volume=100,
                    turnover=1000, turnover_rate=None,
                )]

        provider = FutuRealtimeProvider(context_factory=Context)
        provider._ensure_context()
        old_generation = provider.connection_generation
        events = []
        provider._callbacks[("SH.600519", "1分")] = {events.append}
        with provider._lock:
            provider._connection_generation += 1
            provider._ready_generation = provider._connection_generation
            provider._generation_subscriptions = {('SH.600519', '1分')}
        current_generation = provider.connection_generation
        provider._handle_frame(Frame(), generation=old_generation)
        provider._handle_response(old_generation, -1, "late old error")
        self.assertEqual(events, [])
        self.assertEqual(provider.status, "live")
        provider._handle_response(current_generation, RET_OK, Frame())
        self.assertEqual(len(events), 1)
        provider.close()

    def test_realtime_stream_requires_terminal_session_for_anonymous(self):
        response = Client().get("/api/realtime/market-stream/SH.600519/?period=1分")
        self.assertEqual(response.status_code, 401)


class RealtimeSourceContractTests(SimpleTestCase):
    def test_futu_provider_has_one_long_lived_context_and_all_supported_periods(self):
        source = (Path(settings.BASE_DIR) / "core" / "realtime" / "futu_provider.py").read_text(encoding="utf-8")
        self.assertIn("self._context", source)
        self.assertIn("CurKlineHandlerBase", source)
        self.assertIn("REALTIME_PERIOD_SUBTYPES", source)
        self.assertIn("_connection_generation", source)
        self.assertIn("_handle_response", source)
        self.assertIn("_reconnect_lock", source)
        self.assertIn("context is not self._context", source)
        self.assertIn("_generation_subscriptions", source)
        self.assertIn("_ready_generation", source)
        self.assertIn("candidate", source)
        self.assertIn("snapshots = []", source)
        self.assertIn("_reconnect_snapshot", source)
        self.assertNotIn("FakeRealtimeProvider", source)

    def test_market_chart_updates_in_place_and_cleans_stream(self):
        source = (Path(settings.BASE_DIR) / "frontend" / "src" / "components" / "MarketChart.vue").read_text(encoding="utf-8")
        self.assertIn("candleSeries.update", source)
        self.assertIn("new EventSource", source)
        self.assertIn("eventSource?.close()", source)
        self.assertIn("visibilitychange", source)
        self.assertIn("realtimeRevision", source)
        self.assertIn("realtimeEpoch", source)
        self.assertIn("realtimeRevision = decision.revision", source)
        self.assertIn("realtimeEpoch = decision.epoch", source)
        self.assertIn("last_closed_bar", source)
        self.assertIn("reconcileRealtimeVersion", source)
        self.assertIn("closedChanged", source)
        self.assertIn("formulaPendingRevision", source)
        self.assertIn("createRealtimeUiBuffer", source)
        self.assertIn("flushMs: 300", source)
        self.assertIn("document.hidden", source)
        self.assertIn("rebuildLayer", source)
        self.assertIn("reconcileHistoryTail", source)
        self.assertIn("requestHistoryTailReconcile", source)
        self.assertIn("mergeHistoricalTail", source)
        self.assertIn("reconcileHistory: true", source)
        self.assertIn("source.onopen", source)
        self.assertIn("realtimePayloadSequence", source)
        self.assertIn("needsHistoryReconcile", source)
        self.assertIn("historyReconcileRetryTimer", source)
        self.assertIn("HISTORY_RECONCILE_RETRY_MS = 2000", source)
        self.assertIn("Array.isArray(payload.bars)", source)
        self.assertIn("getVisibleLogicalRange", source)
        self.assertIn("latestRealtimePayloadGeneration", source)
        self.assertIn("cancelFormulaWork()", source)
        self.assertIn("invalidateFormulaResults({ clearPending: false })", source)
        self.assertIn("formulaRefreshPending", source)
        self.assertIn("historyReconcilePendingGeneration", source)
        self.assertIn("settleHistoryReconcile", source)
        self.assertNotIn("applyRealtimePayload", source)
        self.assertGreaterEqual(source.count("chart?.remove()"), 2)

    def test_realtime_ui_buffer_contract_has_coalescing_and_pause(self):
        source = (Path(settings.BASE_DIR) / "frontend" / "src" / "realtime" / "realtimeUiBuffer.mjs").read_text(encoding="utf-8")
        self.assertIn("REALTIME_UI_FLUSH_MS = 300", source)
        self.assertIn("latest = payload", source)
        self.assertIn("mergeRealtimeBars", source)
        self.assertIn("mergeRealtimePayload", source)
        self.assertIn("mergeHistoricalTail", source)
        self.assertIn("isPaused", source)
        self.assertIn("flushCount", source)

    def test_registry_health_probe_has_shared_throttle_and_no_main_lock_io(self):
        source = (Path(settings.BASE_DIR) / "core" / "realtime" / "registry.py").read_text(encoding="utf-8")
        self.assertIn("_health_lock", source)
        self.assertIn("_health_inflight", source)
        self.assertIn("health_interval_seconds", source)
        self.assertIn("time.monotonic", source)
        self.assertIn("_has_active_consumers", source)

    def test_dynamic_formula_primitives_request_redraw(self):
        for filename in ("TongdaxinStickPrimitive.js", "TongdaxinTextPrimitive.js", "TongdaxinFixedTextPrimitive.js"):
            source = (Path(settings.BASE_DIR) / "frontend" / "src" / "indicators" / filename).read_text(encoding="utf-8")
            self.assertIn("attached({ requestUpdate })", source)
            self.assertIn("this.requestUpdate?.()", source)

    def test_formula_render_parses_revision_and_uses_capture_and_run_registry(self):
        source = (Path(settings.BASE_DIR) / "core" / "views.py").read_text(encoding="utf-8")
        self.assertIn('request.GET.get("revision", 0)', source)
        self.assertIn('request.GET.get("epoch", "")', source)
        self.assertIn("state_store.capture", source)
        self.assertIn("merge_calculation_snapshot_rows", source)
        self.assertIn("calculation_snapshot.epoch", source)
        self.assertIn("input_hash", source)
        self.assertIn("formula_run_registry.run", source)

    def test_bar_rows_preserves_missing_fields_and_real_zero(self):
        class Frame:
            def itertuples(self):
                return [SimpleNamespace(
                    code="SH.600519", time_key="2026-09-04 09:30:00", open=0, high=1, low=0,
                    close=0, volume=0, turnover=None, turnover_rate=None, last_close=0,
                )]

        row = bar_rows(Frame())[0]
        self.assertEqual(row["open"], 0)
        self.assertEqual(row["volume"], 0)
        self.assertIsNone(row["amount"])
        self.assertIsNone(row["turnover_rate"])
