from django.urls import path
from ninja import NinjaAPI
from pydantic import Field, RootModel, field_serializer

from django_veo_admin_api.schemas import AdminSchema


class CompatPayload(AdminSchema):
    message: str = Field(alias="inputMessage")


class CompatItem(AdminSchema):
    value: str = Field(serialization_alias="outputValue")

    @field_serializer("value")
    def serialize_value(self, value, info):
        request = info.context["request"]
        return f"{request.method}:{value}"


class CompatResponse(RootModel[list[CompatItem]]):
    pass


api = NinjaAPI(
    title="Pydantic compatibility",
    urls_namespace="ninja-pydantic-compat",
    auth=None,
    docs_url=None,
)


@api.post("/echo", response=CompatResponse, by_alias=True)
def echo(request, payload: CompatPayload):
    return [CompatItem(value=payload.message)]


urlpatterns = [path("compat/", api.urls)]
