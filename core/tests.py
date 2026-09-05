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
from .views import _watchlist_create, bar_rows
from .watchlist import resolve_account_tier, resolve_watchlist_limit
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

    def test_account_center_profile_preferences_and_live_terminal_state_contract(self):
        self.assertIn(':watchlist-total="watchlistTotal"', self.app_source)
        self.assertIn(':watchlist-limit="watchlistLimit"', self.app_source)
        self.assertIn(':watchlist-remaining="watchlistRemaining"', self.app_source)
        self.assertIn('marketColorTokens', self.app_source)
        self.assertIn(':market-color-tokens="marketColorTokens"', self.app_source)
        self.assertLess(self.app_source.index('<AccountPopover v-else'), self.app_source.index('<select class="terminal-language"'))
        self.assertIn('/api/account/profile/', self.center_source)
        self.assertIn('/api/account/avatar/', self.center_source)
        self.assertIn('/api/account/preferences/', self.center_source)
        self.assertIn('price_color_mode', self.center_source)
        self.assertIn('default_market', self.center_source)
        self.assertIn('default_period', self.center_source)
        self.assertNotIn('setLocale', self.center_source)
        self.assertNotIn('languages', self.center_source)
        self.assertIn('applyOptions', (self.base_dir / 'frontend' / 'src' / 'components' / 'MarketChart.vue').read_text(encoding='utf-8'))


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
