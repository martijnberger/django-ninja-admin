from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from ninja.security import SessionAuthIsStaff

from django_ninja_admin import NinjaAdminSite, site
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Product


def test_site_routes_return_typed_auth_errors(db):
    response = Client().get("/admin-api/apps")

    assert response.status_code in {401, 403}
    body = response.json()
    assert set(body) == {"errors"}
    assert body["errors"][0]["param"] == "non_field_errors"


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
    ]
)
def test_session_bootstrap_login_csrf_mutation_and_logout(db, sample):
    user = get_user_model().objects.create_user("bootstrap-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client = Client(enforce_csrf_checks=True)

    csrf_response = client.get("/admin-api/csrf")
    assert csrf_response.status_code == 200
    csrf_token = csrf_response.json()["csrf_token"]
    assert csrf_token
    assert client.get("/admin-api/apps").status_code == 401

    bad_login = client.post(
        "/admin-api/login",
        data={"username": "bootstrap-admin", "password": "wrong"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert bad_login.status_code == 400
    ErrorResponse.model_validate(bad_login.json())
    assert bad_login.json()["errors"] == [{"message": "Invalid username or password.", "param": "username"}]

    login_response = client.post(
        "/admin-api/login",
        data={"username": "bootstrap-admin", "password": "pw"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body["is_authenticated"] is True
    assert login_body["is_staff"] is True
    assert login_body["has_permission"] is True
    assert login_body["csrf_token"]

    mutation = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"description": "Bootstrapped session"}},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_body["csrf_token"],
    )
    assert mutation.status_code == 200
    sample.refresh_from_db()
    assert sample.description == "Bootstrapped session"

    logout_response = client.post(
        "/admin-api/logout",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_body["csrf_token"],
    )
    assert logout_response.status_code == 200
    assert logout_response.json()["is_authenticated"] is False
    assert client.get("/admin-api/apps").status_code == 401


def test_permissions_route_reports_site_permission(admin_client):
    staff_response = admin_client.get("/admin-api/permissions")

    assert staff_response.status_code == 200
    body = staff_response.json()
    permission_state_keys = ("is_authenticated", "is_active", "is_staff", "is_superuser", "has_permission")
    assert {key: body[key] for key in permission_state_keys} == {
        "is_authenticated": True,
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "has_permission": True,
    }
    assert isinstance(body["models"], list)
    model_keys = {(model["app_label"], model["model_name"]) for model in body["models"]}
    assert {("testapp", "category"), ("testapp", "product"), ("testapp", "tag")} <= model_keys
    product_permissions = next(model["perms"] for model in body["models"] if model["model_name"] == "product")
    assert product_permissions == {
        "has_add_permission": True,
        "has_change_permission": True,
        "has_delete_permission": True,
        "has_view_permission": True,
    }


def test_permissions_route_uses_custom_model_permission_hooks(admin_client, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "has_add_permission", lambda request: False)
    monkeypatch.setattr(product_admin, "has_delete_permission", lambda request, obj=None: False)

    response = admin_client.get("/admin-api/permissions")

    assert response.status_code == 200
    product = next(model for model in response.json()["models"] if model["model_name"] == "product")
    assert product["perms"] == {
        "has_add_permission": False,
        "has_change_permission": True,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_permissions_route_supports_auth_none_sites():
    public_response = Client().get("/public-permissions-admin/permissions")

    assert public_response.status_code == 200
    assert public_response.json() == {
        "is_authenticated": False,
        "is_active": False,
        "is_staff": False,
        "is_superuser": False,
        "has_permission": False,
        "models": [],
    }

    schema = Client().get("/public-permissions-admin/openapi.json").json()
    operation = schema["paths"]["/public-permissions-admin/permissions"]["get"]
    assert "security" not in operation
    assert "401" not in operation["responses"]
    assert "403" not in operation["responses"]


def _component_properties(schema, component_name):
    return set(schema["components"]["schemas"][component_name]["properties"])


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_include_auth_uses_safe_user_and_group_admins(db):
    client = Client()
    user = get_user_model().objects.create_user("auth-safe", password="hashed", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client.force_login(user)

    user_form = client.get("/auth-models-admin/auth/user/form")
    assert user_form.status_code == 200
    user_field_names = {field["name"] for field in user_form.json()["form"]["fields"]}
    assert {"password", "is_superuser", "user_permissions", "groups"}.isdisjoint(user_field_names)

    group_form = client.get("/auth-models-admin/auth/group/form")
    assert group_form.status_code == 200
    group_field_names = {field["name"] for field in group_form.json()["form"]["fields"]}
    assert "permissions" not in group_field_names

    schema = client.get("/auth-models-admin/openapi.json").json()
    sensitive_user_write_fields = {"password", "is_superuser", "user_permissions", "groups"}
    for component_name in ("UserAdminCreateData", "UserAdminUpdateData", "UserAdminPartialUpdateData"):
        assert sensitive_user_write_fields.isdisjoint(_component_properties(schema, component_name))
    for component_name in ("UserAdminOut", "UserAdminMutationData"):
        assert "password" not in _component_properties(schema, component_name)
    for component_name in ("GroupAdminCreateData", "GroupAdminUpdateData", "GroupAdminPartialUpdateData"):
        assert "permissions" not in _component_properties(schema, component_name)

    response = client.patch(
        f"/auth-models-admin/auth/user/{user.pk}",
        data={
            "data": {
                "password": "plain",
                "is_superuser": True,
                "user_permissions": [Permission.objects.first().pk],
                "groups": [],
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 422
    assert {
        "data.password",
        "data.is_superuser",
        "data.user_permissions",
        "data.groups",
    }.issubset({error["param"] for error in response.json()["errors"]})
    user.refresh_from_db()
    assert user.check_password("hashed")
    assert user.is_superuser is False


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_site_auth_accepts_ninja_auth_sequences():
    client = Client()

    assert client.get("/multi-auth-admin/whoami").status_code == 401
    assert client.get("/multi-auth-admin/openapi.json").status_code == 401
    primary = client.get("/multi-auth-admin/whoami", headers={"X-Primary-Token": "primary"})
    secondary = client.get("/multi-auth-admin/whoami", headers={"X-Secondary-Token": "secondary"})
    invalid = client.get("/multi-auth-admin/whoami", headers={"X-Primary-Token": "wrong"})
    schema_response = client.get("/multi-auth-admin/openapi.json", headers={"X-Primary-Token": "primary"})

    assert primary.status_code == 200
    assert primary.json() == {"auth": "primary"}
    assert secondary.status_code == 200
    assert secondary.json() == {"auth": "secondary"}
    assert invalid.status_code == 401
    assert schema_response.status_code == 200

    schema = schema_response.json()
    operation = schema["paths"]["/multi-auth-admin/whoami"]["get"]
    assert operation["operationId"] == "multi_auth_whoami"
    assert {"PrimaryTokenAuth": []} in operation["security"]
    assert {"SecondaryTokenAuth": []} in operation["security"]
    assert schema["components"]["securitySchemes"]["PrimaryTokenAuth"]["in"] == "header"
    assert schema["components"]["securitySchemes"]["SecondaryTokenAuth"]["name"] == "X-Secondary-Token"


def test_unauthenticated_is_rejected(db):
    response = Client().get("/admin-api/apps")
    assert response.status_code in {401, 403}


def test_admin_site_auth_contracts():
    default_site = NinjaAdminSite(include_auth=False)
    assert isinstance(default_site.auth, SessionAuthIsStaff)

    no_auth_site = NinjaAdminSite(auth=None, include_auth=False)
    assert no_auth_site.auth is None

    def custom_auth(request):
        return "token"

    custom_auth_site = NinjaAdminSite(auth=custom_auth, include_auth=False)
    assert custom_auth_site.auth is custom_auth
