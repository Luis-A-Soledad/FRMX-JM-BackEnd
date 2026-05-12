# from __future__ import annotations
# import os
# from dataclasses import dataclass
# from pathlib import Path
# from dotenv import load_dotenv, find_dotenv
# from langchain_openai import AzureChatOpenAI

# # Importaciones para usar Azure KeyVault
# from azure.identity import DefaultAzureCredential , ClientSecretCredential
# from azure.keyvault.secrets import SecretClient 

# # 1. Load .env , se sigue importando el env para cosas que son de config no sensibles
# _found = find_dotenv()
# if _found:
#     load_dotenv(_found, override=True)
# else:
#     print("[AVISO] .env no encontrado. Verifica tu ruta de ejecución.")

# # Credencial para KeyVault
# # Usa ClientSecretCredential si hay variables de Service Principal,
# # sino usa DefaultAzureCredential (az login)
# _tenant_id = os.getenv("AZURE_TENANT_ID")
# _client_id = os.getenv("AZURE_CLIENT_ID")
# _client_secret = os.getenv("AZURE_CLIENT_SECRET")

# if _tenant_id and _client_id and _client_secret:
#     credential = ClientSecretCredential(
#         tenant_id=_tenant_id,
#         client_id=_client_id,
#         client_secret=_client_secret,
#     )
# else:
#     credential = DefaultAzureCredential()

# # Se extrae del .env el nombre del Key Vault, del cual se obtendran las claves

# KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")

# # Configuramos el Cliente oficial de Secrets, con nuestra credencial y el keyvault url
# secret_client = SecretClient(
#     vault_url=KEY_VAULT_URL,
#     credential=credential
# )

# # Creamos una función  helper de extracción de secretos
# def get_secret(name: str) -> str:
#     try:
#         return secret_client.get_secret(name).value
#     except Exception as exc:
#         raise RuntimeError(f"No se pudo obtener el secret '{name}'") from exc

# def get_databricks_token() -> str:
#     """Obtiene token de Databricks via Service Principal de Azure."""
#     credential = ClientSecretCredential(
#         tenant_id=os.environ["AZURE_TENANT_ID"],
#         client_id=os.environ["AZURE_CLIENT_ID"],
#         client_secret=os.environ["AZURE_CLIENT_SECRET"],
#     )
#     token = credential.get_token("2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default")
#     return token.token

# # Secretos desde KeyVault
# AZURE_OPENAI_API_KEY = get_secret("AZURE-OPENAI-API-KEY")
# AZURE_SEARCH_ADMIN_KEY = get_secret("AZURE-SEARCH-ADMIN-KEY")

# # 2. Helpers

# def _get_required_env(name: str) -> str:
#     val = os.getenv(name, "").strip()
#     if not val:
#         raise ValueError(f"Missing required environment variable: {name}")
#     return val

# def _get_bool_env(name: str, default=False) -> bool:
#     val = os.getenv(name)
#     if val is None:
#         return default
#     return val.strip().lower() in {"1", "true", "yes", "on"}

# def _get_int_env(name: str, default: int) -> int:
#     val = os.getenv(name)
#     if val is None or not val.strip():
#         return default
#     try:
#         return int(val)
#     except ValueError:
#         raise ValueError(f"Environment variable {name} must be an integer.")

# # 3. Unified Settings

# @dataclass(frozen=True)
# class Settings:
#     databricks_host: str
#     databricks_token: str
#     genie_space_id: str
#     default_table_name: str
#     default_timezone: str
#     genie_timeout_seconds: int
#     genie_poll_interval_seconds: int
#     output_dir: Path
#     debug: bool
#     default_export_format: str = "xlsx"

#     aoai_endpoint: str = _get_required_env("AZURE_OPENAI_ENDPOINT")
#     #aoai_key: str = _get_required_env("AZURE_OPENAI_API_KEY")
#     aoai_key : str = AZURE_OPENAI_API_KEY
#     aoai_chat_deployment: str = _get_required_env("AZURE_OPENAI_DEPLOYMENT")
#     aoai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

# # Para configuraciones del RAG

# # ===== Recuperación: usa Azure AI Search como vector DB =====
# RETRIEVAL_BACKEND = (os.getenv("RETRIEVAL_BACKEND") or "azure-search").lower().strip()

# # ===== Embeddings (para la query) =====
# AZURE_EMB_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT")  # text-embedding-3-small

# # ===== Azure AI Search =====
# AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")  # https://<tu-servicio>.search.windows.net
# #AZURE_SEARCH_ADMIN_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY")
# AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")        # reglamentos_rag_p1
# AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # https://<tu-recurso>.openai.azure.com/
# #AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")          # tu clave de Azure OpenAI
# AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # tu deployment de Azure OpenAI para embeddings (ej: text-embedding-3-small)
# AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")  # API version

# # ===== Parámetros RAG =====
# RAG_BASE_TOP   = _get_int_env(os.getenv("RAG_BASE_TOP"), 2)
# RAG_WIN_CHUNKS = _get_int_env(os.getenv("RAG_WIN_CHUNKS"), 1)
# RAG_WIN_PAGES  = _get_int_env(os.getenv("RAG_WIN_PAGES"), 0)
# RAG_TOP_RETURN = _get_int_env(os.getenv("RAG_TOP_RETURN"), 6)

# # Presupuesto de contexto
# RAG_CTX_TOKEN_BUDGET  = _get_int_env(os.getenv("RAG_CTX_TOKEN_BUDGET"), 1800)
# RAG_CTX_CHAR_BUDGET   = _get_int_env(os.getenv("RAG_CTX_CHAR_BUDGET"), 9000)
# RAG_TRIM_CHUNK_CHARS  = _get_int_env(os.getenv("RAG_TRIM_CHUNK_CHARS"), 1200)

# # ===== Databricks SQL Warehouse (conexión directa a tablas) =====

# @dataclass(frozen=True)
# class SQLWarehouseSettings:
#     host: str
#     token: str
#     http_path: str
#     tables: dict  # nombre lógico → nombre completo en Databricks (catalog.schema.table)

# def get_sql_warehouse_settings() -> SQLWarehouseSettings:
#     return SQLWarehouseSettings(
#         host=_get_required_env("DATABRICKS_SQL_HOST"),
#         token=_get_required_env("DATABRICKS_SQL_TOKEN"),
#         http_path=_get_required_env("DATABRICKS_SQL_HTTP_PATH"),
#         tables={
#             "alertas": os.getenv(
#                 "DATABRICKS_SQL_TABLE_ALERTAS",
#                 "main.test_frmx.alertas_dummy_large",
#             ),
#             # Agregar más tablas aquí:
#             # "otra_tabla": os.getenv("DATABRICKS_SQL_TABLE_OTRA", "catalog.schema.tabla"),
#         },
#     )

# sql_warehouse_settings = get_sql_warehouse_settings()

# # 4. Validation

# def _validate_settings(s: Settings):
#     if not s.databricks_host.startswith(("http://", "https://")):
#         raise ValueError("DATABRICKS_HOST must start with http:// or https://")
#     if s.genie_poll_interval_seconds > s.genie_timeout_seconds:
#         raise ValueError(
#             "GENIE_POLL_INTERVAL_SECONDS cannot be greater than GENIE_TIMEOUT_SECONDS"
#         )

# # 5. Init

# def get_settings() -> Settings:
#     s = Settings(
#         databricks_host=_get_required_env("DATABRICKS_HOST"),
#         #databricks_token=_get_required_env("DATABRICKS_TOKEN"),
#         databricks_token=get_databricks_token(),
#         genie_space_id=_get_required_env("GENIE_SPACE_ID"),
#         default_table_name=_get_required_env("DEFAULT_TABLE_NAME"),
#         default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC").strip(),
#         genie_timeout_seconds=_get_int_env("GENIE_TIMEOUT_SECONDS", 60),
#         genie_poll_interval_seconds=_get_int_env("GENIE_POLL_INTERVAL_SECONDS", 2),
#         output_dir=Path(os.getenv("OUTPUT_DIR", "outputs")).resolve(),
#         debug=_get_bool_env("DEBUG", False),
#         default_export_format=os.getenv("DEFAULT_EXPORT_FORMAT", "xlsx"),
#     )
#     _validate_settings(s)
#     s.output_dir.mkdir(parents=True, exist_ok=True)
#     return s


# # guardamos settings
# settings = get_settings()
# # 6. LLM

# def get_llm(settings=settings) -> AzureChatOpenAI:
#     print(f"Estas obteniendo las variables para el llm")
#     if settings is None:
#         print(f'No se creo settings: {settings}')
#         #settings = get_settings()
#     return AzureChatOpenAI(
#         azure_endpoint=settings.aoai_endpoint,
#         api_key=settings.aoai_key,
#         azure_deployment=settings.aoai_chat_deployment,
#         api_version=settings.aoai_api_version,
#     )




from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from langchain_openai import AzureChatOpenAI
from azure.identity import ClientSecretCredential
from azure.keyvault.secrets import SecretClient

def _get_bool_env(name: str, default=False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}

def _get_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer.")

def _init_keyvault() -> SecretClient:
    credential = ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )
    return SecretClient(vault_url=os.environ["KEY_VAULT_URL"], credential=credential)

def get_secret(name: str) -> str:
    client = _init_keyvault()
    try:
        return client.get_secret(name).value
    except Exception as exc:
        raise RuntimeError(f"No se pudo obtener el secret: {name}") from exc

def get_databricks_token() -> str:
    """Obtiene token de Databricks via Service Principal de Azure."""
    credential = ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )
    token = credential.get_token("2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default")
    return token.token

@dataclass(frozen=True)
class Settings:
    databricks_host: str
    databricks_token: str
    genie_space_id: str
    default_table_name: str
    default_timezone: str
    genie_timeout_seconds: int
    genie_poll_interval_seconds: int
    output_dir: Path
    debug: bool
    default_export_format: str
    aoai_endpoint: str
    aoai_key: str
    aoai_chat_deployment: str
    aoai_api_version: str
    azure_search_endpoint: str
    azure_search_admin_key: str
    azure_search_index: str

RETRIEVAL_BACKEND = (os.getenv("RETRIEVAL_BACKEND") or "azure-search").lower().strip()
AZURE_EMB_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
#AZURE_SEARCH_ADMIN_KEY = get_secret("AZURE-SEARCH-ADMIN-KEY")
AZURE_SEARCH_ADMIN_KEY = ""
# AZURE_OPENAI_API_KEY = get_secret("AZURE-OPENAI-API-KEY")
AZURE_OPENAI_API_KEY = os.getenv("AZURE-OPENAI-API-KEY")
DATABRICKS_TOKEN = get_databricks_token()
# DJANGO_SECRET_KEY = get_secret("DJANGO-SECRET-KEY")
DJANGO_SECRET_KEY = os.getenv("DJANGO-SECRET-KEY")
# GENIE_SPACE_ID = get_secret("GENIE-SPACE-ID")
GENIE_SPACE_ID = os.getenv("GENIE-SPACE-ID")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

RAG_BASE_TOP   = _get_int_env("RAG_BASE_TOP", 2)
RAG_WIN_CHUNKS = _get_int_env("RAG_WIN_CHUNKS", 1)
RAG_WIN_PAGES  = _get_int_env("RAG_WIN_PAGES", 0)
RAG_TOP_RETURN = _get_int_env("RAG_TOP_RETURN", 6)
RAG_CTX_TOKEN_BUDGET  = _get_int_env("RAG_CTX_TOKEN_BUDGET", 1800)
RAG_CTX_CHAR_BUDGET   = _get_int_env("RAG_CTX_CHAR_BUDGET", 9000)
RAG_TRIM_CHUNK_CHARS  = _get_int_env("RAG_TRIM_CHUNK_CHARS", 1200)

def _validate_settings(s: Settings):
    if not s.databricks_host.startswith(("http://", "https://")):
        raise ValueError("DATABRICKS_HOST must start with http:// or https://")
    if s.genie_poll_interval_seconds > s.genie_timeout_seconds:
        raise ValueError("GENIE_POLL_INTERVAL_SECONDS cannot be greater than GENIE_TIMEOUT_SECONDS")

def get_settings() -> Settings:
    s = Settings(
        databricks_host=os.environ["DATABRICKS_HOST"],
        databricks_token=get_databricks_token(),
        #genie_space_id=get_secret("GENIE-SPACE-ID"),
        genie_space_id=os.getenv("GENIE-SPACE-ID"),
        default_table_name=os.getenv("DEFAULT_TABLE_NAME", "alertas"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC").strip(),
        genie_timeout_seconds=_get_int_env("GENIE_TIMEOUT_SECONDS", 60),
        genie_poll_interval_seconds=_get_int_env("GENIE_POLL_INTERVAL_SECONDS", 2),
        output_dir=Path(os.getenv("OUTPUT_DIR", "/tmp/outputs")).resolve(),
        debug=_get_bool_env("DEBUG", False),
        default_export_format=os.getenv("DEFAULT_EXPORT_FORMAT", "xlsx"),
        aoai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        #aoai_key=get_secret("AZURE-OPENAI-API-KEY"),
        aoai_key=os.getenv("AZURE-OPENAI-API-KEY"),
        aoai_chat_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        aoai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
        azure_search_endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        #azure_search_admin_key=get_secret("AZURE-SEARCH-ADMIN-KEY"),
        azure_search_admin_key=os.getenv("AZURE-SEARCH-ADMIN-KEY"),
        azure_search_index=os.environ["AZURE_SEARCH_INDEX"],
    )
    _validate_settings(s)
    s.output_dir.mkdir(parents=True, exist_ok=True)
    return s

settings = get_settings()

def get_llm(settings=settings) -> AzureChatOpenAI:
    print("Estas obteniendo las variables para el llm")
    return AzureChatOpenAI(
        azure_endpoint=settings.aoai_endpoint,
        api_key=settings.aoai_key,
        azure_deployment=settings.aoai_chat_deployment,
        api_version=settings.aoai_api_version,
    )

#--------------- Conexion a base de datos -----------------------------
# ===== Databricks SQL Warehouse (conexión directa a tablas) =====

#@dataclass(frozen=True)
#class SQLWarehouseSettings:
#    host: str
#    token: str
#    http_path: str
#    tables: dict  # nombre lógico → nombre completo en Databricks (catalog.schema.table)
#
#def get_sql_warehouse_settings() -> SQLWarehouseSettings:
#    return SQLWarehouseSettings(
#        host=_get_required_env("DATABRICKS_SQL_HOST"),
#        token=_get_required_env("DATABRICKS_SQL_TOKEN"),
#        http_path=_get_required_env("DATABRICKS_SQL_HTTP_PATH"),
#        tables={
#            "alertas": os.getenv(
#                "DATABRICKS_SQL_TABLE_ALERTAS",
#                "main.test_frmx.alertas_dummy_large",
#            ),
#            # Agregar más tablas aquí:
#            # "otra_tabla": os.getenv("DATABRICKS_SQL_TABLE_OTRA", "catalog.schema.tabla"),
#        },
#    )
#
#sql_warehouse_settings = get_sql_warehouse_settings()

