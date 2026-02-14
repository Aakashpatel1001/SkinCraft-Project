from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SkinCraft_Main', '0042_salarypayment_transfer_account_holder_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='cancel_reason',
            field=models.CharField(
                blank=True,
                choices=[
                    ('Changed Mind', 'Changed Mind'),
                    ('Found Better Price', 'Found Better Price'),
                    ('Ordered by Mistake', 'Ordered by Mistake'),
                    ('Delivery Is Too Late', 'Delivery Is Too Late'),
                    ('Address Issue', 'Address Issue'),
                    ('Other', 'Other'),
                ],
                max_length=60,
                null=True,
            ),
        ),
    ]
