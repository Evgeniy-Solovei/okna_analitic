DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'metabase_reader') THEN
      CREATE ROLE metabase_reader LOGIN PASSWORD 'change-me';
   END IF;
END
$$;

