from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0003_remove_futu_formula_mode')]
    operations = [migrations.CreateModel(name='CalibrationDataset', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('symbol', models.CharField(max_length=32, unique=True, verbose_name='证券代码')),
        ('name', models.CharField(max_length=80, verbose_name='证券名称')),
        ('period', models.CharField(default='日线', max_length=16, verbose_name='周期')),
        ('adjustment', models.CharField(blank=True, max_length=32, verbose_name='复权方式')),
        ('bars', models.JSONField(verbose_name='K线数据')),
        ('imported_at', models.DateTimeField(auto_now=True, verbose_name='导入时间')),
    ], options={'verbose_name': '通达信校准数据', 'verbose_name_plural': '通达信校准数据'})]
