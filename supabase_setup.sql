-- MCP Architecture and Interiors XA Energy: licence keys. Paste this whole file into Supabase > SQL Editor > New query > Run (once).

create table if not exists public.licences (
  key         text primary key,
  note        text,
  status      text not null default 'active',     -- 'active' or 'revoked'
  max_users   int  not null default 1,            -- how many people may use this key
  valid_until date,                                -- empty = never expires
  created_at  timestamptz default now()
);
create table if not exists public.licence_users (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  key          text not null references public.licences(key),
  activated_at timestamptz default now()
);
-- nobody can read or change these tables from the program directly
alter table public.licences enable row level security;
alter table public.licence_users enable row level security;

-- make a new key:   select new_licence('Client name', 365, 1);      (note, days valid (0 = forever), people allowed)
create or replace function public.new_licence(p_note text default '', p_days int default 365, p_max int default 1)
returns text language plpgsql security definer set search_path = public as $$
declare k text;
begin
  k := 'MCP-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
              || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
              || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4));
  insert into public.licences(key, note, valid_until, max_users)
  values (k, p_note, case when p_days > 0 then current_date + p_days end, p_max);
  return k;
end $$;
revoke all on function public.new_licence(text, int, int) from public, anon, authenticated;

-- what the program asks at every start
create or replace function public.licence_status()
returns json language plpgsql security definer set search_path = public as $$
declare r record;
begin
  if auth.uid() is null then return json_build_object('state', 'none'); end if;
  select l.* into r from public.licence_users u join public.licences l on l.key = u.key where u.user_id = auth.uid();
  if not found then return json_build_object('state', 'none'); end if;
  if r.status <> 'active' then return json_build_object('state', 'revoked'); end if;
  if r.valid_until is not null and r.valid_until < current_date then
    return json_build_object('state', 'expired', 'valid_until', r.valid_until);
  end if;
  return json_build_object('state', 'ok', 'valid_until', r.valid_until);
end $$;
grant execute on function public.licence_status() to authenticated;

-- a person enters their key once
create or replace function public.redeem_licence(p_key text)
returns json language plpgsql security definer set search_path = public as $$
declare l record; n int;
begin
  if auth.uid() is null then raise exception 'Sign in first.'; end if;
  select * into l from public.licences where key = upper(trim(p_key));
  if not found then raise exception 'That licence key is not valid.'; end if;
  if l.status <> 'active' then raise exception 'That licence key has been switched off.'; end if;
  if l.valid_until is not null and l.valid_until < current_date then raise exception 'That licence key has expired.'; end if;
  if exists (select 1 from public.licence_users where user_id = auth.uid()) then return public.licence_status(); end if;
  select count(*) into n from public.licence_users where key = l.key;
  if n >= l.max_users then raise exception 'That licence key is already used by the most people it allows.'; end if;
  insert into public.licence_users(user_id, key) values (auth.uid(), l.key);
  return public.licence_status();
end $$;
grant execute on function public.redeem_licence(text) to authenticated;

-- switch a key off (the person is locked out at their next start):   select revoke_licence('MCP-XXXX-XXXX-XXXX');
create or replace function public.revoke_licence(p_key text) returns void language sql security definer set search_path = public as $$
  update public.licences set status = 'revoked' where key = upper(trim(p_key));
$$;
revoke all on function public.revoke_licence(text) from public, anon, authenticated;
