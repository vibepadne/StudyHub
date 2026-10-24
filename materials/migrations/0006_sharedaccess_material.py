from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("materials", "0005_materialtextindex")]

    operations = [
        migrations.AddField(
            model_name="sharedaccess",
            name="material",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="shares",
                to="materials.material",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="sharedaccess", name="sharedaccess_exactly_one_target"
        ),
        migrations.AddConstraint(
            model_name="sharedaccess",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(subject__isnull=False, topic__isnull=True, material__isnull=True)
                    | models.Q(subject__isnull=True, topic__isnull=False, material__isnull=True)
                    | models.Q(subject__isnull=True, topic__isnull=True, material__isnull=False)
                ),
                name="sharedaccess_exactly_one_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="sharedaccess",
            constraint=models.UniqueConstraint(
                condition=models.Q(material__isnull=False),
                fields=("shared_with", "material"),
                name="unique_material_share_per_user",
            ),
        ),
    ]
