-- Read-only security and migration inventory for Cataran/Supabase.
-- Run in the Supabase SQL Editor using a privileged inspection role.
-- This script deliberately performs SELECT statements only and opens a read-only transaction.

BEGIN TRANSACTION READ ONLY;

-- 1. Schema existence and API-role USAGE.
select
    n.nspname as schema_name,
    pg_get_userbyid(n.nspowner) as owner_name,
    has_schema_privilege('anon', n.oid, 'USAGE') as anon_usage,
    has_schema_privilege('authenticated', n.oid, 'USAGE') as authenticated_usage,
    has_schema_privilege('service_role', n.oid, 'USAGE') as service_role_usage
from pg_namespace n
where n.nspname in ('public', 'rag', 'institutional_rag', 'im19')
order by n.nspname;

-- 2. Table/view RLS and direct API-role privileges.
select
    n.nspname as schema_name,
    c.relname as relation_name,
    c.relkind as relation_kind,
    c.relrowsecurity as rls_enabled,
    c.relforcerowsecurity as force_rls,
    (select count(*) from pg_policies p
      where p.schemaname = n.nspname and p.tablename = c.relname) as policy_count,
    (
        has_table_privilege('anon', c.oid, 'SELECT')
        or has_table_privilege('anon', c.oid, 'INSERT')
        or has_table_privilege('anon', c.oid, 'UPDATE')
        or has_table_privilege('anon', c.oid, 'DELETE')
        or has_table_privilege('anon', c.oid, 'TRUNCATE')
        or has_table_privilege('anon', c.oid, 'REFERENCES')
        or has_table_privilege('anon', c.oid, 'TRIGGER')
    ) as anon_any_table_privilege,
    (
        has_table_privilege('authenticated', c.oid, 'SELECT')
        or has_table_privilege('authenticated', c.oid, 'INSERT')
        or has_table_privilege('authenticated', c.oid, 'UPDATE')
        or has_table_privilege('authenticated', c.oid, 'DELETE')
        or has_table_privilege('authenticated', c.oid, 'TRUNCATE')
        or has_table_privilege('authenticated', c.oid, 'REFERENCES')
        or has_table_privilege('authenticated', c.oid, 'TRIGGER')
    ) as authenticated_any_table_privilege,
    (
        has_table_privilege('service_role', c.oid, 'SELECT')
        or has_table_privilege('service_role', c.oid, 'INSERT')
        or has_table_privilege('service_role', c.oid, 'UPDATE')
        or has_table_privilege('service_role', c.oid, 'DELETE')
    ) as service_role_any_data_privilege
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname in ('public', 'rag', 'institutional_rag', 'im19')
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
order by n.nspname, c.relname;

-- 3. Function/RPC execution grants and SECURITY DEFINER surface.
select
    n.nspname as schema_name,
    p.proname as function_name,
    pg_get_function_identity_arguments(p.oid) as arguments,
    p.prosecdef as security_definer,
    pg_get_userbyid(p.proowner) as owner_name,
    has_function_privilege('anon', p.oid, 'EXECUTE') as anon_execute,
    has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_execute,
    has_function_privilege('service_role', p.oid, 'EXECUTE') as service_role_execute,
    p.proconfig as function_settings
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname in ('public', 'rag', 'institutional_rag', 'im19')
  and p.prokind in ('f', 'p')
order by n.nspname, p.proname, pg_get_function_identity_arguments(p.oid);

-- 4. Applied migration ledger. Compare this list to the authoritative,
-- cross-repository migration ownership manifest before creating new migrations.
select version, name
from supabase_migrations.schema_migrations
order by version;

-- 5. Installed extensions and versions.
select
    e.extname as extension_name,
    e.extversion as installed_version,
    n.nspname as extension_schema
from pg_extension e
join pg_namespace n on n.oid = e.extnamespace
order by e.extname;

COMMIT;
