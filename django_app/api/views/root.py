from django.http import JsonResponse


def read_root(request):
    """Test endpoint."""
    return JsonResponse({"Privet": "Mir"})
