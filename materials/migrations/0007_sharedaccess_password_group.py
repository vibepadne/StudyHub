import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("materials", "0006_sharedaccess_material")]

    operations = [
        migrations.AddField(
            model_name="sharedaccess",
            name="password_group",
            field=models.UUIDField(
                blank=True, default=uuid.uuid4, editable=False, null=True
            ),
        ),
    ]
