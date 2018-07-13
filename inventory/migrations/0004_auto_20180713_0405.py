# Generated by Django 2.0.4 on 2018-07-13 04:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_auto_20180626_2000'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Entity',
            new_name='Asset',
        ),
        migrations.RemoveIndex(
            model_name='asset',
            name='inventory_e_account_7f4862_idx',
        ),
        migrations.AddIndex(
            model_name='asset',
            index=models.Index(fields=['account'], name='inventory_a_account_305c41_idx'),
        ),
    ]
