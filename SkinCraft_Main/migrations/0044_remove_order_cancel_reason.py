from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('SkinCraft_Main', '0043_order_cancel_reason'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='cancel_reason',
        ),
    ]
