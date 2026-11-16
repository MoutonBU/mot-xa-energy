-- MOT XA Energy: private update store. Run once in Supabase > SQL Editor.
-- Only people who are signed in AND have an active licence can download the program updates. Nothing is public.
insert into storage.buckets (id, name, public) values ('releases', 'releases', false)
on conflict (id) do update set public = false;

drop policy if exists "licensed users read releases" on storage.objects;
create policy "licensed users read releases" on storage.objects for select to authenticated
using (bucket_id = 'releases' and (public.licence_status() ->> 'state') = 'ok');
