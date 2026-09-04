import re
from datetime import datetime
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from core.models import CalibrationDataset

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('path'); parser.add_argument('--symbol', required=True); parser.add_argument('--name', required=True); parser.add_argument('--adjustment', default='前复权'); parser.add_argument('--float-shares', type=float, help='流通股本（股），用于筹码分布计算')
    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.is_file(): raise CommandError(f'文件不存在：{path}')
        bars = []
        for line in path.read_text(encoding='gb18030').splitlines():
            fields = re.split(r'\s+', line.strip())
            if len(fields) < 7 or not re.fullmatch(r'\d{4}/\d{2}/\d{2}', fields[0]): continue
            try: open_, high, low, close, volume, amount = map(float, fields[1:7])
            except ValueError: continue
            bars.append({'time': int(datetime.strptime(fields[0], '%Y/%m/%d').timestamp()), 'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume, 'amount': amount})
        if len(bars) < 100: raise CommandError('未识别到足够的日线记录')
        record, _ = CalibrationDataset.objects.update_or_create(symbol=options['symbol'].upper(), defaults={'name': options['name'], 'period': '日线', 'adjustment': options['adjustment'], 'float_shares': options['float_shares'], 'bars': bars})
        self.stdout.write(self.style.SUCCESS(f'已导入 {record.symbol}：{len(bars)} 根日线（{record.adjustment}）'))
