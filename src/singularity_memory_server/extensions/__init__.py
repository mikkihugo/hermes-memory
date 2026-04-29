"""
Singularity Memory Extensions System.

Extensions allow customizing and extending server behavior without modifying core code.
Extensions are loaded via environment variables pointing to implementation classes.

Example:
    SINGULARITY_OPERATION_VALIDATOR_EXTENSION=mypackage.validators:MyValidator
    SINGULARITY_OPERATION_VALIDATOR_MAX_RETRIES=3

    SINGULARITY_HTTP_EXTENSION=mypackage.http:MyHttpExtension
    SINGULARITY_HTTP_SOME_CONFIG=value

Extensions receive an ExtensionContext that provides a controlled API for interacting
with the system (e.g., running migrations for tenant schemas).
"""

from singularity_memory_server.extensions.base import Extension
from singularity_memory_server.extensions.builtin import ApiKeyTenantExtension, SupabaseTenantExtension
from singularity_memory_server.extensions.context import DefaultExtensionContext, ExtensionContext
from singularity_memory_server.extensions.http import HttpExtension
from singularity_memory_server.extensions.loader import load_extension
from singularity_memory_server.extensions.mcp import MCPExtension
from singularity_memory_server.extensions.operation_validator import (
    # Bank Management operations
    BankListContext,
    BankListResult,
    BankReadContext,
    BankWriteContext,
    # Consolidation operation
    ConsolidateContext,
    ConsolidateResult,
    # File Conversion
    FileConvertResult,
    # Mental Model operations
    MentalModelGetContext,
    MentalModelGetResult,
    MentalModelRefreshContext,
    MentalModelRefreshResult,
    # Core operations
    OperationValidationError,
    OperationValidatorExtension,
    RecallContext,
    RecallResult,
    ReflectContext,
    ReflectResultContext,
    RetainContext,
    RetainResult,
    ValidationResult,
)
from singularity_memory_server.extensions.tenant import (
    AuthenticationError,
    Tenant,
    TenantContext,
    TenantExtension,
)
from singularity_memory_server.models import RequestContext
from singularity_memory_server.worker.exceptions import DeferOperation

__all__ = [
    # Base
    "Extension",
    "load_extension",
    # Context
    "ExtensionContext",
    "DefaultExtensionContext",
    # HTTP Extension
    "HttpExtension",
    # MCP Extension
    "MCPExtension",
    # Operation Validator - Core
    "DeferOperation",
    "OperationValidationError",
    "OperationValidatorExtension",
    "RecallContext",
    "RecallResult",
    "ReflectContext",
    "ReflectResultContext",
    "RetainContext",
    "RetainResult",
    "ValidationResult",
    # Operation Validator - Bank Management
    "BankListContext",
    "BankListResult",
    "BankReadContext",
    "BankWriteContext",
    # Operation Validator - Consolidation
    "ConsolidateContext",
    "ConsolidateResult",
    # Operation Validator - File Conversion
    "FileConvertResult",
    # Operation Validator - Mental Model
    "MentalModelGetContext",
    "MentalModelGetResult",
    "MentalModelRefreshContext",
    "MentalModelRefreshResult",
    # Tenant/Auth
    "ApiKeyTenantExtension",
    "SupabaseTenantExtension",
    "AuthenticationError",
    "RequestContext",
    "Tenant",
    "TenantContext",
    "TenantExtension",
]
