"""Official-SDK MCP projection of the shared admin operation services."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from asgiref.sync import sync_to_async
from django.http import HttpRequest, QueryDict
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ListToolsResult, ToolAnnotations
from pydantic import Field

from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.core.site import CoreAdminSite
from django_veo_admin_api.integrations.mcp.context import DjangoRequestFactory, MCPRequestInfo, request_info
from django_veo_admin_api.integrations.mcp.policy import MCPToolPolicy
from django_veo_admin_api.integrations.mcp.results import operation_error_result, operation_result_error
from django_veo_admin_api.integrations.mcp.schemas import MCPDeleteResult, MCPToolResponse
from django_veo_admin_api.schemas import (
    AppSummary,
    AutocompleteResponse,
    ChangelistResponse,
    DeletionPreview,
    ErrorResponse,
    FormResponse,
    HistoryActionFlag,
    HistoryResponse,
    PermissionsResponse,
    SiteContext,
)

type ToolPermission = Callable[[HttpRequest], bool]
type OperationCall = Callable[[AdminRequestContext], OperationResult[Any]]
PositiveInt = Annotated[int, Field(ge=1)]

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


class MCPAdminServer:
    """Project a ``CoreAdminSite`` through the official MCP SDK."""

    def __init__(
        self,
        admin_site: CoreAdminSite,
        request_factory: DjangoRequestFactory,
        *,
        name: str = "Django Veo Admin API",
        version: str = "2.0.0",
        policy: MCPToolPolicy | None = None,
        admin_url_prefix: str = "/admin-api",
        token_verifier=None,
        auth=None,
    ):
        self.admin_site = admin_site
        self.request_factory = request_factory
        self.policy = policy or MCPToolPolicy()
        self.admin_url_prefix = admin_url_prefix.rstrip("/")
        self._tool_permissions: dict[str, ToolPermission | None] = {}
        self.server = MCPServer(
            name=name,
            version=version,
            description="Permission-aware Django admin operations.",
            instructions="Use discovery first; every call repeats Django admin permission checks.",
            token_verifier=token_verifier,
            auth=auth,
            middleware=[self._filter_tools],
        )
        self._register_read_tools()
        self._register_mutation_tools()

    def streamable_http_app(
        self,
        *,
        path: str = "/mcp",
        json_response: bool = True,
        max_request_body_size: int = 4 * 1024 * 1024,
        transport_security=None,
        host: str = "127.0.0.1",
    ):
        return self.server.streamable_http_app(
            streamable_http_path=path,
            json_response=json_response,
            stateless_http=True,
            max_request_body_size=max_request_body_size,
            transport_security=transport_security,
            host=host,
        )

    async def _filter_tools(self, ctx, call_next):
        result = await call_next(ctx)
        if ctx.method != "tools/list" or not isinstance(result, ListToolsResult):
            return result
        try:
            allowed = await sync_to_async(self._allowed_tool_names_sync, thread_sensitive=True)(request_info(ctx))
        except Exception:
            return result.model_copy(update={"tools": []})
        return result.model_copy(update={"tools": [tool for tool in result.tools if tool.name in allowed]})

    def _allowed_tool_names_sync(self, info: MCPRequestInfo) -> set[str]:
        request = self._request(info)
        return {
            name
            for name, permission in self._tool_permissions.items()
            if self.policy.allows(name)
            and self.admin_site.has_permission(request)
            and (permission is None or permission(request))
        }

    def _register_read_tools(self):
        self._add_tool(
            self._apps,
            name="admin.apps",
            description="List registered apps and models visible to the current Django user.",
        )
        self._add_tool(
            self._context,
            name="admin.context",
            description="Return permission-filtered admin site context.",
        )
        self._add_tool(
            self._permissions,
            name="admin.permissions",
            description="Return current Django admin permission state.",
        )
        self._add_tool(
            self._history,
            name="admin.history",
            description="List permission-filtered Django admin audit history.",
        )
        for model, model_admin in self.admin_site.get_registered_model_admins():
            self._register_model_read_tools(model, model_admin)

    def _register_model_read_tools(self, model, model_admin):
        prefix = f"admin.{model._meta.app_label}.{model._meta.model_name}"
        visible = model_admin.has_view_or_change_permission

        async def list_objects(
            ctx: Context,
            params: dict[str, str | list[str]] | None = None,
        ) -> MCPToolResponse[ChangelistResponse]:
            def operation(context):
                self._prepare_model_request(context.request, model, query=params)
                return self.admin_site.changelist_operations.list(context, model_admin)

            return await self._invoke(ctx, f"{prefix}.list", visible, operation)

        self._add_tool(
            list_objects,
            name=f"{prefix}.list",
            description=f"List {model._meta.verbose_name_plural} with Django changelist semantics.",
            permission=visible,
        )

        output_schema = model_admin.get_output_schema(None)

        async def detail(
            object_id: str,
            ctx: Context,
            to_field: str | None = None,
        ):
            def operation(context):
                self._prepare_model_request(context.request, model, object_id=object_id)
                return self.admin_site.object_operations.detail(context, model_admin, object_id, to_field)

            return await self._invoke(ctx, f"{prefix}.detail", visible, operation)

        detail.__annotations__["return"] = MCPToolResponse[output_schema]
        self._add_tool(
            detail,
            name=f"{prefix}.detail",
            description=f"Get one {model._meta.verbose_name} after object-level permission checks.",
            permission=visible,
        )

        async def form(
            ctx: Context,
            object_id: str | None = None,
            to_field: str | None = None,
        ) -> MCPToolResponse[FormResponse]:
            def operation(context):
                self._prepare_model_request(context.request, model, object_id=object_id, suffix="form")
                obj = None
                if object_id is not None:
                    obj = self.admin_site.object_operations.get_object(context, model_admin, object_id, to_field).data
                return self.admin_site.form_operations.describe(context, model_admin, obj)

            return await self._invoke(ctx, f"{prefix}.form", visible, operation)

        self._add_tool(
            form,
            name=f"{prefix}.form",
            description=f"Describe the request-aware form and inline formsets for {model._meta.verbose_name}.",
            permission=visible,
        )

        autocomplete_fields = tuple(model_admin.autocomplete_fields)
        if autocomplete_fields:
            field_type = Literal.__getitem__(autocomplete_fields)

            async def autocomplete(
                field_name: str,
                ctx: Context,
                term: str = "",
                page: PositiveInt = 1,
                per_page: PositiveInt = 20,
            ) -> MCPToolResponse[AutocompleteResponse]:
                def operation(context):
                    self._prepare_model_request(context.request, model)
                    return self.admin_site.autocomplete_operations.search(
                        context,
                        app_label=model._meta.app_label,
                        model_name=model._meta.model_name,
                        field_name=field_name,
                        term=term,
                        page=page,
                        per_page=min(per_page, self.admin_site.autocomplete_max_per_page),
                    )

                return await self._invoke(ctx, f"{prefix}.autocomplete", visible, operation)

            autocomplete.__annotations__["field_name"] = field_type
            self._add_tool(
                autocomplete,
                name=f"{prefix}.autocomplete",
                description=f"Search configured relation fields for {model._meta.verbose_name}.",
                permission=visible,
            )

    def _register_mutation_tools(self):
        for model, model_admin in self.admin_site.get_registered_model_admins():
            self._register_model_mutation_tools(model, model_admin)

    def _register_model_mutation_tools(self, model, model_admin):
        prefix = f"admin.{model._meta.app_label}.{model._meta.model_name}"
        can_add = model_admin.has_add_permission
        can_change = model_admin.has_change_permission
        can_view_or_change = model_admin.has_view_or_change_permission
        can_delete = model_admin.has_delete_permission
        create_payload_schema = model_admin.get_mutation_payload_schema(None, change=False, partial=False)
        update_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=True)
        mutation_response_schema = model_admin.get_mutation_response_schema(None)

        async def create(payload, ctx: Context):
            def operation(context):
                self._prepare_model_request(context.request, model, method="POST")
                return self.admin_site.mutation_operations.create(context, model_admin, payload)

            return await self._invoke(ctx, f"{prefix}.create", can_add, operation)

        create.__annotations__["payload"] = create_payload_schema
        create.__annotations__["return"] = MCPToolResponse[mutation_response_schema]
        self._add_tool(
            create,
            name=f"{prefix}.create",
            description=f"Create one {model._meta.verbose_name} through its Django admin form and inlines.",
            permission=can_add,
            annotations=MUTATING,
        )

        async def update(object_id: str, payload, ctx: Context, to_field: str | None = None):
            def operation(context):
                self._prepare_model_request(context.request, model, object_id=object_id, method="PATCH")
                return self.admin_site.mutation_operations.update(
                    context,
                    model_admin,
                    object_id,
                    payload,
                    partial=True,
                    to_field=to_field,
                )

            return await self._invoke(ctx, f"{prefix}.update", can_change, operation)

        update.__annotations__["payload"] = update_payload_schema
        update.__annotations__["return"] = MCPToolResponse[mutation_response_schema]
        self._add_tool(
            update,
            name=f"{prefix}.update",
            description=f"Partially update one {model._meta.verbose_name} through its Django admin form.",
            permission=can_change,
            annotations=MUTATING,
        )

        bulk_payload_schema = model_admin.get_bulk_payload_schema(None)
        bulk_response_schema = model_admin.get_bulk_response_schema(None)

        async def bulk_update(payload, ctx: Context):
            def operation(context):
                self._prepare_model_request(context.request, model, suffix="bulk", method="PUT")
                return self.admin_site.bulk_mutation_operations.update(context, model_admin, payload)

            return await self._invoke(ctx, f"{prefix}.bulk_update", can_change, operation)

        bulk_update.__annotations__["payload"] = bulk_payload_schema
        bulk_update.__annotations__["return"] = MCPToolResponse[bulk_response_schema]
        self._add_tool(
            bulk_update,
            name=f"{prefix}.bulk_update",
            description=f"Apply Django list-editable formset updates to {model._meta.verbose_name_plural}.",
            permission=can_change,
            annotations=MUTATING,
        )

        if model_admin.has_registered_actions():
            action_payload_schema = model_admin.get_action_payload_schema(None)
            action_response_schema = model_admin.get_action_response_schema(None)

            async def actions(payload, ctx: Context, to_field: str | None = None):
                def operation(context):
                    self._prepare_model_request(context.request, model, suffix="actions", method="POST")
                    return self.admin_site.action_operations.execute(
                        context,
                        model_admin,
                        payload,
                        to_field=to_field,
                    )

                return await self._invoke(ctx, f"{prefix}.actions", can_view_or_change, operation)

            actions.__annotations__["payload"] = action_payload_schema
            actions.__annotations__["return"] = MCPToolResponse[action_response_schema]
            self._add_tool(
                actions,
                name=f"{prefix}.actions",
                description=f"Execute one registered Django admin action for {model._meta.verbose_name_plural}.",
                permission=can_view_or_change,
                annotations=MUTATING,
            )

        async def delete_preview(
            object_id: str,
            ctx: Context,
            to_field: str | None = None,
        ) -> MCPToolResponse[DeletionPreview]:
            def operation(context):
                self._prepare_model_request(
                    context.request,
                    model,
                    object_id=object_id,
                    suffix="delete-preview",
                )
                return self.admin_site.deletion_operations.preview(
                    context,
                    model_admin,
                    object_id,
                    to_field,
                )

            return await self._invoke(ctx, f"{prefix}.delete_preview", can_delete, operation)

        self._add_tool(
            delete_preview,
            name=f"{prefix}.delete_preview",
            description=(
                f"Preview cascades, protection, and permissions before deleting one {model._meta.verbose_name}."
            ),
            permission=can_delete,
        )

        async def delete(
            object_id: str,
            ctx: Context,
            to_field: str | None = None,
        ) -> MCPToolResponse[MCPDeleteResult]:
            def operation(context):
                self._prepare_model_request(context.request, model, object_id=object_id, method="DELETE")
                result = self.admin_site.deletion_operations.delete(
                    context,
                    model_admin,
                    object_id,
                    to_field,
                )
                if result.status_code >= 400:
                    return result
                return OperationResult(
                    MCPDeleteResult(
                        status_code=result.status_code,
                        response=result.data,
                    )
                )

            return await self._invoke(ctx, f"{prefix}.delete", can_delete, operation)

        self._add_tool(
            delete,
            name=f"{prefix}.delete",
            description=f"Delete one {model._meta.verbose_name} after Django admin cascade and permission checks.",
            permission=can_delete,
            annotations=MUTATING,
        )

    async def _apps(self, ctx: Context) -> MCPToolResponse[list[AppSummary]]:
        return await self._invoke(
            ctx,
            "admin.apps",
            None,
            lambda context: self.admin_site.discovery_operations.list_apps(context),
        )

    async def _context(self, ctx: Context) -> MCPToolResponse[SiteContext]:
        return await self._invoke(
            ctx,
            "admin.context",
            None,
            lambda context: self.admin_site.discovery_operations.site_context(context),
        )

    async def _permissions(self, ctx: Context) -> MCPToolResponse[PermissionsResponse]:
        return await self._invoke(
            ctx,
            "admin.permissions",
            None,
            lambda context: self.admin_site.discovery_operations.permissions(context),
        )

    async def _history(
        self,
        ctx: Context,
        app_label: str | None = None,
        model_name: str | None = None,
        object_id: str | None = None,
        action_flag: HistoryActionFlag | None = None,
        ordering: Literal["action_time", "-action_time"] = "-action_time",
        page: PositiveInt = 1,
        per_page: PositiveInt = 20,
    ) -> MCPToolResponse[HistoryResponse]:
        return await self._invoke(
            ctx,
            "admin.history",
            None,
            lambda context: self.admin_site.history_operations.list(
                context,
                app_label=app_label,
                model_name=model_name,
                object_id=object_id,
                action_flag=action_flag,
                ordering=ordering,
                page=page,
                per_page=min(per_page, self.admin_site.history_max_per_page),
            ),
        )

    def _add_tool(
        self,
        function,
        *,
        name: str,
        description: str,
        permission: ToolPermission | None = None,
        annotations: ToolAnnotations = READ_ONLY,
    ):
        self._tool_permissions[name] = permission
        self.server.add_tool(
            function,
            name=name,
            description=description,
            annotations=annotations,
            meta={"django_veo_admin_api": {"operation": name}},
            structured_output=True,
        )

    async def _invoke(
        self,
        context: Context,
        tool_name: str,
        permission: ToolPermission | None,
        operation: OperationCall,
    ) -> Any:
        try:
            result = await sync_to_async(self._invoke_sync, thread_sensitive=True)(
                request_info(context), tool_name, permission, operation
            )
        except Exception as exc:
            return operation_error_result(exc, tool_name=tool_name)
        if result.status_code >= 400 and isinstance(result.data, ErrorResponse):
            return operation_result_error(result.data)
        return {"data": result.data, "error": None}

    def _invoke_sync(
        self,
        info: MCPRequestInfo,
        tool_name: str,
        permission: ToolPermission | None,
        operation: OperationCall,
    ) -> OperationResult[Any]:
        request = self._request(info)
        if not self.policy.allows(tool_name):
            raise AdminPermissionError([{"message": "Permission denied.", "param": "non_field_errors"}])
        if not self.admin_site.has_permission(request):
            raise AdminPermissionError([{"message": "Permission denied.", "param": "non_field_errors"}])
        if permission is not None and not permission(request):
            raise AdminPermissionError([{"message": "Permission denied.", "param": "non_field_errors"}])
        return operation(AdminRequestContext(request))

    def _request(self, info: MCPRequestInfo) -> HttpRequest:
        request = self.request_factory(info)
        if not isinstance(request, HttpRequest):
            raise TypeError("request_factory must return a Django HttpRequest.")
        if not hasattr(request, "user"):
            raise TypeError("request_factory must attach an authenticated Django user.")
        return request

    def _prepare_model_request(
        self,
        request,
        model,
        *,
        object_id=None,
        suffix=None,
        query=None,
        method="GET",
    ):
        parts = [self.admin_url_prefix, model._meta.app_label, model._meta.model_name]
        if object_id is not None:
            parts.append(str(object_id))
        if suffix:
            parts.append(suffix)
        path = "/".join(part.strip("/") for part in parts if part)
        request.path = f"/{path}"
        request.path_info = request.path
        request.method = method
        request.GET = self._query_dict(query)

    @staticmethod
    def _query_dict(params):
        query = QueryDict("", mutable=True)
        for key, value in (params or {}).items():
            values = value if isinstance(value, list) else [value]
            query.setlist(key, [str(item) for item in values])
        return query
