from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('fitness', '0010_weightlog'),
    ]

    operations = [
        migrations.RenameField(
            model_name='weightlog',
            old_name='weight',
            new_name='weight_kg',
        ),
    ]
