-- MOT XA Energy: automatic licences. Run once in Supabase > SQL Editor (after supabase_setup.sql).
-- Everyone who creates an account with their email gets a licence key made for them automatically.

create table if not exists public.app_config (key text primary key, value text);
alter table public.app_config enable row level security;
insert into public.app_config(key, value) values ('licence_days', '365') on conflict (key) do nothing;
-- change the length any time:   update app_config set value = '30' where key = 'licence_days';     (0 = never expires)

create or replace function public.make_auto_licence(p_user uuid, p_email text) returns void
language plpgsql security definer set search_path = public as $$
declare k text; d int;
begin
  if exists (select 1 from public.licence_users where user_id = p_user) then return; end if;
  select coalesce((select value::int from public.app_config where key = 'licence_days'), 365) into d;
  k := 'MCP-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
              || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
              || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4));
  insert into public.licences(key, note, valid_until, max_users)
  values (k, 'auto: ' || coalesce(p_email, ''), case when d > 0 then current_date + d end, 1);
  insert into public.licence_users(user_id, key) values (p_user, k);
end $$;
revoke all on function public.make_auto_licence(uuid, text) from public, anon, authenticated;

create or replace function public.auto_licence_trigger() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.make_auto_licence(new.id, new.email);
  return new;
end $$;

drop trigger if exists on_user_created_licence on auth.users;
create trigger on_user_created_licence after insert on auth.users
for each row execute function public.auto_licence_trigger();

-- people who already registered
do $$ declare r record; begin
  for r in select id, email from auth.users loop perform public.make_auto_licence(r.id, r.email); end loop;
end $$;

-- switch one person off / back on / give more time (run by you in the SQL Editor):
--   select block_user('name@example.com');
--   select unblock_user('name@example.com');
--   select extend_user('name@example.com', 365);       -- days counted from today
create or replace function public.block_user(p_email text) returns void language sql security definer set search_path = public as $$
  update public.licences set status = 'revoked' where key in
    (select u.key from public.licence_users u join auth.users a on a.id = u.user_id where a.email = lower(trim(p_email)));
$$;
create or replace function public.unblock_user(p_email text) returns void language sql security definer set search_path = public as $$
  update public.licences set status = 'active' where key in
    (select u.key from public.licence_users u join auth.users a on a.id = u.user_id where a.email = lower(trim(p_email)));
$$;
create or replace function public.extend_user(p_email text, p_days int) returns void language sql security definer set search_path = public as $$
  update public.licences set valid_until = current_date + p_days, status = 'active' where key in
    (select u.key from public.licence_users u join auth.users a on a.id = u.user_id where a.email = lower(trim(p_email)));
$$;
revoke all on function public.block_user(text), public.unblock_user(text), public.extend_user(text, int) from public, anon, authenticated;
