-- Pictures each player uploads for their own heroes, enemies and objects.
--
-- Only the clean copy is stored: app/admin/sprite_scan.py checks every upload
-- (type, structure, hidden code, antivirus when configured, pixels) and writes a
-- new PNG from the pixel values alone. Each picture belongs to one account and is
-- only ever read by it; a creation may use one of its owner's pictures instead
-- of the drawing of its base.
create table if not exists user_sprites (
    id         bigserial   primary key,
    owner_id   bigint      not null references users (id) on delete cascade,
    name       text        not null check (length(name) between 1 and 24),
    png        bytea       not null check (octet_length(png) between 1 and 400000),
    width      smallint    not null check (width between 8 and 256),
    height     smallint    not null check (height between 8 and 256),
    sha256     text        not null check (sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default now(),
    unique (owner_id, sha256)
);
create index if not exists user_sprites_owner on user_sprites (owner_id, id);

alter table custom_entities add column if not exists sprite_id bigint references user_sprites (id) on delete set null;

-- Same lock as every other table (migration 091): only the API reads them.
alter table user_sprites enable row level security;
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on table public.user_sprites from anon';
        execute 'revoke all on sequence public.user_sprites_id_seq from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on table public.user_sprites from authenticated';
        execute 'revoke all on sequence public.user_sprites_id_seq from authenticated';
    end if;
end $$;
