from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SkinCraft_Main', '0040_bankdetails'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salarypayment',
            name='payment_mode',
            field=models.CharField(
                blank=True,
                choices=[('Bank Transfer', 'Bank Transfer'), ('UPI', 'UPI')],
                max_length=20,
                null=True,
            ),
        ),
    ]

