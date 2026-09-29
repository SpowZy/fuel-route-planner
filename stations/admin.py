from django.contrib import admin

from .models import Station


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "price", "price_rows", "geo_source")
    list_filter = ("country", "state", "geo_source")
    search_fields = ("name", "city", "address", "opis_id")
    ordering = ("state", "city")
