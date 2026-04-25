create table community_reports (
  id            uuid primary key default gen_random_uuid(),
  lat           double precision not null,
  lng           double precision not null,
  photo_url     text not null,
  submitted_at  timestamptz not null default now(),
  sender_hash   text not null,
  status        text not null default 'pending',
  source        text not null default 'community',
  constraint status_values check (status in ('pending','approved','rejected'))
);

-- Public read of approved rows only
create policy "public read approved"
  on community_reports for select
  using (status = 'approved');

alter table community_reports enable row level security;
