-- Aydın Campus Map: buildings, the walking graph, places and the assistant's
-- knowledge base. Everything lives in the `amap` schema, which Supabase's
-- REST API does not expose; RLS is on and only the API role gets policies.

create extension if not exists postgis with schema extensions;
create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;

create schema if not exists amap;

-- The API connects as this role (login and password are set by
-- `amap db api-role`, never in a migration).
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'amap_api') then
    create role amap_api nologin;
  end if;
end
$$;

create table amap.buildings (
  id text primary key,                 -- OSM way id
  code text,                           -- campus block letter, e.g. 'A'
  name text,
  campus boolean not null default false,
  height_m real not null,
  height_source text not null,         -- osm_levels | default | sfm
  footprint extensions.geometry(Polygon, 4326) not null,
  outline_local jsonb not null         -- [[east, north], ...] in local metres
);
create index buildings_footprint_idx on amap.buildings using gist (footprint);

create table amap.nodes (
  id text primary key,                 -- panorama scene id
  kind text not null,                  -- outdoor | entrance | indoor
  building text,
  floor smallint,
  label_tr text not null,
  label_en text not null,
  area_tr text,
  area_en text,
  heading_deg real not null,
  pose_source text not null,
  enu real[] not null,                 -- east, north, up in local metres
  geom extensions.geometry(PointZ, 4326) not null
);
create index nodes_geom_idx on amap.nodes using gist (geom);

create table amap.edges (
  id text primary key,
  source text not null references amap.nodes (id) on delete cascade,
  target text not null references amap.nodes (id) on delete cascade,
  kind text not null,
  origin text not null,
  length_m real not null,
  cost_s real not null,
  length_source text not null,
  geom extensions.geometry(LineStringZ, 4326) not null
);
create index edges_source_idx on amap.edges (source);
create index edges_target_idx on amap.edges (target);

create table amap.places (
  id text primary key,                 -- representative node id
  name_tr text not null,
  name_en text not null,
  kind text not null,
  building text,
  node_ids text[] not null,
  aliases text[] not null default '{}',
  search_key text not null             -- amap_contracts.text.search_key
);
create index places_search_trgm_idx
  on amap.places using gin (search_key extensions.gin_trgm_ops);

create table amap.chunks (
  id bigint generated always as identity primary key,
  content_hash text not null unique,
  source text not null,                -- label | building | vision | web
  source_ref text,                     -- scene id, building id or URL
  lang text not null check (lang in ('tr', 'en')),
  title text,
  content text not null,
  metadata jsonb not null default '{}',
  embedding extensions.vector(768) not null
);
create index chunks_embedding_idx
  on amap.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index chunks_lang_idx on amap.chunks (lang);

create table amap.answer_cache (
  key text primary key,                -- normalised question + language
  lang text not null,
  answer jsonb not null,
  hits integer not null default 0,
  created_at timestamptz not null default now()
);

alter table amap.buildings enable row level security;
alter table amap.nodes enable row level security;
alter table amap.edges enable row level security;
alter table amap.places enable row level security;
alter table amap.chunks enable row level security;
alter table amap.answer_cache enable row level security;

grant usage on schema amap to amap_api;
grant usage on schema extensions to amap_api;
grant select on all tables in schema amap to amap_api;
grant insert, update, delete on amap.answer_cache to amap_api;

create policy api_read on amap.buildings for select to amap_api using (true);
create policy api_read on amap.nodes for select to amap_api using (true);
create policy api_read on amap.edges for select to amap_api using (true);
create policy api_read on amap.places for select to amap_api using (true);
create policy api_read on amap.chunks for select to amap_api using (true);
create policy api_all on amap.answer_cache for all to amap_api
  using (true) with check (true);
