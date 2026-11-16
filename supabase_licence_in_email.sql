-- MOT XA Energy: the licence key goes out in the sign-up e-mail, sent from YOUR OWN mailbox (no extra service).
-- Run once in Supabase > SQL Editor (after supabase_setup.sql and supabase_auto_licence.sql).

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

create or replace function public.auto_licence_trigger() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.make_auto_licence(new.id, new.email, new.raw_user_meta_data ->> 'licence_key');
  return new;
end $$;

-- people who registered before get a licence too
do $$ declare r record; begin
  for r in select id, email from auth.users loop perform public.make_auto_licence(r.id, r.email, null); end loop;
end $$;

-- to see a person's key:    select l.key, l.valid_until, l.status from licence_users u join licences l on l.key = u.key join auth.users a on a.id = u.user_id where a.email = 'name@example.com';
