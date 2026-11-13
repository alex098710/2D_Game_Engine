-- The admin panel of each account.
--
-- user_balance: the health and damage this user gave to each hero and enemy
-- (only the values that differ from the game's defaults are stored).
-- custom_entities: heroes, enemies and objects this user created; each one
-- starts from a base kind of the engine (its picture and behaviour) and has
-- its own name, colour and numbers. Nobody else ever sees them.
create table if not exists user_balance (
    user_id    bigint      primary key references users (id) on delete cascade,
    heroes     jsonb       not null default '{}'::jsonb,
    enemies    jsonb       not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists custom_entities (
    id         bigserial   primary key,
    owner_id   bigint      not null references users (id) on delete cascade,
    category   text        not null check (category in ('hero', 'enemy', 'object')),
    base_kind  text        not null check (length(base_kind) between 1 and 32),
    name       text        not null check (length(name) between 1 and 24),
    tint       text        not null default '#ffffff' check (tint ~ '^#[0-9a-f]{6}$'),
    health     smallint    not null default 0 check (health between 0 and 99),
    damage     smallint    not null default 0 check (damage between 0 and 20),
    speed      smallint    not null default 0 check (speed between 0 and 400),
    value      smallint    not null default 0 check (value between 0 and 20),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists custom_entities_owner on custom_entities (owner_id, category);

-- Same lock as every other table (migration 091): only the API reads them.
alter table user_balance enable row level security;
alter table custom_entities enable row level security;
