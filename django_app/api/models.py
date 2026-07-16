"""Aviation data models.

Normalizes the scraper's wide ``b.csv`` (one row per airport, with up to 11
inline runway groups) into ``Airport`` + ``Runway``.

Field sizes are derived from a profile of the real dataset (19,408 rows),
roughly doubled to leave headroom for future FAA cycles.
"""

from django.db import models


class Airport(models.Model):
    """A single airport / landing facility from the FAA base dataset."""

    class Ownership(models.TextChoices):
        PUBLIC = "PU", "Public"
        PRIVATE = "PR", "Private"
        AIR_FORCE = "MA", "Air Force"
        NAVY = "MN", "Navy"
        ARMY = "MR", "Army"
        COAST_GUARD = "CG", "Coast Guard"

    # 'Identifier' is unique across the whole dataset -> natural primary key.
    identifier = models.CharField(max_length=8, primary_key=True)

    city = models.CharField(max_length=64)
    state = models.CharField(max_length=8, blank=True, default="")
    country = models.CharField(max_length=8)

    lat = models.FloatField()
    lon = models.FloatField()
    elevation = models.FloatField(null=True, blank=True)

    ownership_type_code = models.CharField(
        max_length=4, choices=Ownership.choices, blank=True, default=""
    )
    fuel_types = models.CharField(max_length=64, blank=True, default="")

    # Frequencies are free-form text: some carry several values ("121.7 348.6").
    ctaf = models.CharField(max_length=32, blank=True, default="")
    unicom = models.CharField(max_length=32, blank=True, default="")
    wx = models.CharField(max_length=64, blank=True, default="")
    phone_no = models.CharField(max_length=32, blank=True, default="")
    ground = models.CharField(max_length=128, blank=True, default="")
    tower = models.CharField(max_length=128, blank=True, default="")
    tower2 = models.CharField(max_length=128, blank=True, default="")
    clearance_delivery = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["identifier"]
        indexes = [
            models.Index(fields=["state"]),
            models.Index(fields=["country"]),
            models.Index(fields=["city"]),
        ]

    def __str__(self):
        return f"{self.identifier} ({self.city}, {self.state})"


class Runway(models.Model):
    """One runway of an airport, unpacked from the RWY_*_N column groups."""

    airport = models.ForeignKey(
        Airport, related_name="runways", on_delete=models.CASCADE
    )
    # Position of the RWY_*_N group this row came from (0-10).
    slot = models.PositiveSmallIntegerField()

    rwy_id = models.CharField(max_length=16)
    tpa = models.IntegerField(null=True, blank=True)
    rgt_tfc = models.CharField(max_length=16, blank=True, default="")
    length_ft = models.IntegerField(null=True, blank=True)
    width_ft = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["airport_id", "slot"]
        constraints = [
            models.UniqueConstraint(
                fields=["airport", "slot"], name="unique_runway_slot_per_airport"
            )
        ]

    def __str__(self):
        return f"{self.airport_id} {self.rwy_id}"
