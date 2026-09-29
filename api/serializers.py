from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text="'City, ST', 'lat,lon' or an address")
    finish = serializers.CharField(max_length=200)
    start_fuel_gallons = serializers.FloatField(required=False, min_value=0)
    range_miles = serializers.FloatField(required=False, min_value=50, max_value=2000)
    mpg = serializers.FloatField(required=False, min_value=1, max_value=100)
    max_offset_miles = serializers.FloatField(required=False, min_value=0.5, max_value=50)
    reserve_miles = serializers.FloatField(required=False, min_value=0, max_value=200)
    stop_penalty_usd = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=200,
        help_text="Driver time charged per stop when choosing stops. 0 means fuel price only.",
    )
    nocache = serializers.BooleanField(required=False, default=False)
