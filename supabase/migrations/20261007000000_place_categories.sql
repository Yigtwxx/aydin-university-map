-- Points of interest enrich places: a category for businesses and services
-- (amap_contracts.pois.PoiCategory) and, through aliases, brand names.
alter table amap.places add column category text;
alter table amap.places add column closed boolean not null default false;
