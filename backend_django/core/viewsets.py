"""ViewSets métier : seules les opérations explicitement raccordées sont ouvertes."""
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.metadata import SimpleMetadata
from rest_framework.viewsets import ModelViewSet, ViewSet


class MetierMetadata(SimpleMetadata):
    def determine_actions(self, request, view):
        # OPTIONS reste descriptif : ni lecture de dossier ni validation métier.
        return {}


class MetierViewSet(ViewSet):
    metadata_class = MetierMetadata
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'options']


class MetierModelViewSet(ModelViewSet):
    """Chaque ressource implémente ses actions avec ses autorisations métier.

    Aucun CRUD hérité ne doit permettre de contourner une validation ou un
    contrôle de société. Les querysets génériques restent fermés tant qu'un
    domaine n'a pas défini explicitement son périmètre dans get_queryset().
    """
    metadata_class = MetierMetadata
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'options']
    pagination_class = None

    def get_queryset(self):
        return super().get_queryset().none()

    def list(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def retrieve(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)
