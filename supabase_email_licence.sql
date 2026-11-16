-- MOT XA Energy: e-mail every new user their licence key, from your own domain.
-- Run once in Supabase > SQL Editor, AFTER supabase_setup.sql and supabase_auto_licence.sql.
--
-- STEP 1: edit the two values marked  <== EDIT  (your Resend API key, and your domain's sender address), then Run.

create extension if not exists pg_net with schema extensions;

insert into public.app_config(key, value) values
  ('resend_key', 're_PASTE_YOUR_RESEND_KEY_HERE'),                                   -- <== EDIT (from resend.com > API Keys)
  ('mail_from',  'MCP Architecture & Interiors <licence@YOURDOMAIN.co.za>')         -- <== EDIT (an address on your domain)
on conflict (key) do update set value = excluded.value;

create or replace function public.send_licence_mail(p_email text, p_key text, p_until date)
returns void language plpgsql security definer set search_path = public, extensions as $$
declare rk text; fr text; body text;
begin
  select value into rk from public.app_config where key = 'resend_key';
  select value into fr from public.app_config where key = 'mail_from';
  if rk is null or rk like 're_PASTE%' then return; end if;
  body := '<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1c1f23">'
       || '<h2 style="margin:0 0 4px">MCP Architecture &amp; Interiors</h2>'
       || '<div style="color:#5c636b;margin-bottom:22px">SANS Compliance Suite</div>'
       || '<p>Welcome, your account is ready and the program is already unlocked on the PC where you registered.</p>'
       || '<p>Your licence key:</p>'
       || '<p style="font-size:22px;letter-spacing:2px;font-weight:bold;background:#f1f2f4;padding:14px 18px;border-radius:8px;display:inline-block">' || p_key || '</p>'
       || '<p>' || case when p_until is null then 'This licence does not expire.' else 'Valid until ' || to_char(p_until, 'DD Month YYYY') || '.' end || '</p>'
       || '<p>Keep this e-mail. Sign in with your e-mail address and password whenever the program asks.</p>'
       || '<p style="color:#8f969e;font-size:12px;margin-top:28px">MCP Architecture &amp; Interiors</p></div>';
  begin
    perform net.http_post(
      url     := 'https://api.resend.com/emails',
      headers := jsonb_build_object('Authorization', 'Bearer ' || rk, 'Content-Type', 'application/json'),
      body    := jsonb_build_object('from', fr, 'to', jsonb_build_array(p_email),
                                    'subject', 'Your MCP SANS Compliance Suite licence key', 'html', body));
  exception when others then null;     -- a mail problem must never stop someone from registering
  end;
end $$;
revoke all on function public.send_licence_mail(text, text, date) from public, anon, authenticated;

-- the automatic licence now also sends the mail
drop function if exists public.make_auto_licence(uuid, text);
create or replace function public.make_auto_licence(p_user uuid, p_email text, p_mail boolean default true) returns void
language plpgsql security definer set search_path = public as $$
declare k text; d int; u date;
begin
  if exists (select 1 from public.licence_users where user_id = p_user) then return; end if;
  select coalesce((select value::int from public.app_config where key = 'licence_days'), 365) into d;
  k := 'MCP-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
              || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4)) || '-'
              || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 4));
  u := case when d > 0 then current_date + d end;
  insert into public.licences(key, note, valid_until, max_users) values (k, 'auto: ' || coalesce(p_email, ''), u, 1);
  insert into public.licence_users(user_id, key) values (p_user, k);
  if p_mail and p_email is not null then perform public.send_licence_mail(p_email, k, u); end if;
end $$;
revoke all on function public.make_auto_licence(uuid, text, boolean) from public, anon, authenticated;

-- send the key again to one person:   select resend_licence_mail('name@example.com');
create or replace function public.resend_licence_mail(p_email text) returns void language plpgsql security definer set search_path = public as $$
declare r record;
begin
  select l.key, l.valid_until into r from public.licence_users u join public.licences l on l.key = u.key
    join auth.users a on a.id = u.user_id where a.email = lower(trim(p_email));
  if found then perform public.send_licence_mail(lower(trim(p_email)), r.key, r.valid_until); end if;
end $$;
revoke all on function public.resend_licence_mail(text) from public, anon, authenticated;
