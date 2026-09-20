-- Run once in YOUR Supabase project's SQL Editor. No service-role key goes into Android.
-- PRIVATE bucket: a submitted photo is not visible to other app users before moderation.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('garden-photos', 'garden-photos', false, 1000000, array['image/jpeg'])
on conflict (id) do nothing;

create table if not exists public.garden_photos (
  id uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  storage_path text not null unique,
  nickname text not null check (char_length(nickname) between 1 and 24 and nickname !~ '[@:/]'),
  variety text not null default '' check (char_length(variety) <= 60),
  caption text not null default '' check (char_length(caption) <= 180),
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  created_at timestamptz not null default now(),
  constraint secure_path check (storage_path = owner_id::text || '/' || id::text || '.jpg')
);
create index if not exists garden_photos_gallery_idx on public.garden_photos(status,created_at desc);
create index if not exists garden_photos_owner_idx on public.garden_photos(owner_id,status,created_at desc);

create table if not exists public.garden_reports (
  photo_id uuid not null references public.garden_photos(id) on delete cascade,
  reporter_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (photo_id, reporter_id)
);

alter table public.garden_photos enable row level security;
alter table public.garden_reports enable row level security;
grant usage on schema public to authenticated;
grant select, insert, delete on public.garden_photos to authenticated;
grant insert on public.garden_reports to authenticated;

create policy "gallery: approved or own pending" on public.garden_photos
  for select to authenticated using (
    status = 'approved' or (owner_id = (select auth.uid()) and status = 'pending')
  );
create policy "gallery: create own pending, max 10 per 24h" on public.garden_photos
  for insert to authenticated with check (
    owner_id = (select auth.uid()) and status = 'pending'
    and (select count(*) from public.garden_photos mine
      where mine.owner_id = (select auth.uid())
      and mine.created_at > now() - interval '24 hours') < 10
  );
create policy "gallery: remove own posts" on public.garden_photos
  for delete to authenticated using (owner_id = (select auth.uid()));
-- No UPDATE policy: only administrators can approve/reject through SQL Editor.

create policy "gallery files: owner or approved photo may read" on storage.objects
  for select to authenticated using (
    bucket_id = 'garden-photos' and exists (
      select 1 from public.garden_photos p
      where p.storage_path = name and
      (p.status = 'approved' or (p.owner_id = (select auth.uid()) and p.status = 'pending'))
    )
  );
create policy "gallery files: only own pending row" on storage.objects
  for insert to authenticated with check (
    bucket_id = 'garden-photos' and
    (storage.foldername(name))[1] = (select auth.uid())::text and
    exists (select 1 from public.garden_photos p
      where p.storage_path = name and p.owner_id = (select auth.uid()) and p.status = 'pending')
  );
create policy "gallery files: delete own files" on storage.objects
  for delete to authenticated using (
    bucket_id = 'garden-photos' and
    (storage.foldername(name))[1] = (select auth.uid())::text
  );

create policy "reports: one report per other user's approved photo" on public.garden_reports
  for insert to authenticated with check (
    reporter_id = (select auth.uid())
    and exists (select 1 from public.garden_photos p
       where p.id = photo_id and p.status = 'approved' and p.owner_id <> (select auth.uid()))
  );
-- No public read of reports; moderators review them in the dashboard/SQL Editor.
