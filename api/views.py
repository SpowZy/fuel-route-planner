from rest_framework.response import Response
from rest_framework.views import APIView

from planner.optimizer import InfeasibleRoute
from routing.calls import CallLog
from routing.client import RoutingError
from routing.locations import LocationError, warm_places
from stations.index import get_index

from .serializers import RouteRequestSerializer
from .service import plan_trip


def _error(code: str, message: str, status: int, **extra) -> Response:
    return Response({"error": {"code": code, "message": message, **extra}}, status=status)


class RoutePlanView(APIView):
    """Plan the cheapest fuel stops between two US locations.

    GET  /api/v1/route/?start=New York, NY&finish=Los Angeles, CA
    POST /api/v1/route/  {"start": "...", "finish": "..."}
    """

    def get(self, request):
        return self._plan(request, request.query_params)

    def post(self, request):
        return self._plan(request, request.data)

    def _plan(self, request, data) -> Response:
        serializer = RouteRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        if params["start"].strip().lower() == params["finish"].strip().lower():
            return _error("same_location", "Start and finish are the same place", 422)

        log = CallLog()
        try:
            payload, timings = plan_trip(params, log, base_url=request.build_absolute_uri("/"))
        except LocationError as error:
            return _error(error.code, str(error), 422)
        except RoutingError as error:
            return _error(error.code, str(error), error.status)
        except InfeasibleRoute as error:
            return _error(
                "no_fuel_within_range",
                str(error) + ". Raise max_offset_miles or range_miles.",
                422,
                gap={
                    "from_mile": round(error.gap_start_mile),
                    "to_mile": error.gap_end_mile and round(error.gap_end_mile),
                },
            )
        response = Response(payload)
        response["Server-Timing"] = ", ".join(f"{name};dur={ms}" for name, ms in timings.items())
        return response


class HealthView(APIView):
    """Also warms the in-memory tables, so the first real request is as fast as the rest."""

    def get(self, request):
        warm_places()
        return Response({"status": "ok", "stations_with_coordinates": len(get_index())})
