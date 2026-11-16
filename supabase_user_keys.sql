-- MOT XA Energy: make sure EVERY new account gets its own licence key automatically, and see them all in one table.
-- Safe to run more than once. Supabase > SQL Editor > paste > Run.
-- (needs supabase_setup.sql and supabase_auto_licence.sql to have been run before)

-- 0. the function that makes a key (included here so this one file is enough)
create table if not exists public.app_config (key text primary key, value text);
insert into public.app_config(key, value) values ('licence_days', '365') on conflict (key) do nothing;
drop function if exists public.make_auto_licence(uuid, text);
drop function if exists public.make_auto_licence(uuid, text, boolean);

-- the licence uses the key the program made for the new person (so the same key is in the e-mail)
create or replace function public.make_auto_licence(p_user uuid, p_email text, p_key text default null) returns void
language plpgsql security definer set search_path = public as $$
declare k text; d int;
begin
  if exists (select 1 from public.licence_users where user_id = p_user) then return; end if;
  select coalesce((select value::int from public.app_config where key = 'licence_days'), 365) into d;
  k := upper(trim(coalesce(p_key, '')));
  if k !~ '^MCP-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$' or exists (select 1 from public.licences where key = k) then
    k := 'MCP-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
                || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
                || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4));
  end if;
  insert into public.licences(key, note, valid_until, max_users)
  values (k, 'auto: ' || coalesce(p_email, ''), case when d > 0 then current_date + d end, 1);
  insert into public.licence_users(user_id, key) values (p_user, k);
end $$;
revoke all on function public.make_auto_licence(uuid, text, text) from public, anon, authenticated;


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

-- 1b. safety net: if an account ever has no key, the program asks for one and gets it, so nobody types a key
create or replace function public.ensure_my_licence() returns json
language plpgsql security definer set search_path = public, auth as $$
declare em text;
begin
  if auth.uid() is null then return json_build_object('state', 'none'); end if;
  select email into em from auth.users where id = auth.uid();
  perform public.make_auto_licence(auth.uid(), em, null);
  return public.licence_status();
end $$;
revoke all on function public.ensure_my_licence() from public, anon;
grant execute on function public.ensure_my_licence() to authenticated;

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
