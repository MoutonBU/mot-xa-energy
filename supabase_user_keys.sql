-- MOT XA Energy: make sure EVERY new account gets its own licence key automatically, and see them all in one table.
-- Safe to run more than once. Supabase > SQL Editor > paste > Run.
-- (needs supabase_setup.sql and supabase_auto_licence.sql to have been run before)

-- 1. the trigger: the moment an account is created, a key is made and linked to it
create or replace function public.auto_licence_trigger() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.make_auto_licence(new.id, new.email, new.raw_user_meta_data ->> 'licence_key');
  return new;
end $$;

drop trigger if exists on_user_created_licence on auth.users;
create trigger on_user_created_licence after insert on auth.users
for each row execute function public.auto_licence_trigger();

-- 2. anybody who already has an account but no key gets one now
do $$ declare r record; begin
  for r in select id, email from auth.users loop perform public.make_auto_licence(r.id, r.email, null); end loop;
end $$;

-- 3. one table with everybody: e-mail, key, status and expiry  (Supabase > Table Editor > user_keys)
create or replace view public.user_keys as
select a.email, l.key as licence_key, l.status, l.valid_until, a.created_at as registered, a.last_sign_in_at
from auth.users a
left join public.licence_users u on u.user_id = a.id
left join public.licences l on l.key = u.key
order by a.created_at desc;
revoke all on public.user_keys from public, anon, authenticated;

-- 4. check it worked: this should list every account with a key and no empty licence_key
select * from public.user_keys;
