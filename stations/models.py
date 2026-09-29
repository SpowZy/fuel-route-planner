from django.db import models
from django.db.models import Q


class Station(models.Model):
    """A fuel station from the price file, one row per OPIS truckstop ID."""

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=160, help_text="Highway and exit, as in the price file")
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2, db_index=True)
    country = models.CharField(max_length=2, default="US")
    rack_id = models.PositiveIntegerField()
    price = models.DecimalField(
        max_digits=7, decimal_places=4, help_text="Dollars per gallon used for planning"
    )
    price_min = models.DecimalField(max_digits=7, decimal_places=4)
    price_max = models.DecimalField(max_digits=7, decimal_places=4)
    price_rows = models.PositiveSmallIntegerField(default=1)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geo_source = models.CharField(
        max_length=24, blank=True, help_text="How the city centroid was found"
    )

    class Meta:
        ordering = ["state", "city", "name"]
        indexes = [models.Index(fields=["latitude", "longitude"])]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="station_price_positive"),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True)
                | Q(latitude__isnull=False, longitude__isnull=False),
                name="station_coordinates_all_or_none",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.city}, {self.state}"
