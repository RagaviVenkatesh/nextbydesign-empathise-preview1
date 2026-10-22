begin;
create table if not exists public.ntd_research_projects (
 id text primary key, payload jsonb not null,
 revision integer not null check(revision>0),
 created_by uuid not null references auth.users(id),
 updated_at timestamptz not null default now(),
 check(payload->>'id'=id), check((payload->>'revision')::int=revision)
);
create table if not exists public.ntd_research_members (
 project_id text not null references public.ntd_research_projects(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 role text not null check(role in ('owner','researcher','reviewer','viewer')),
 primary key(project_id,user_id)
);
create table if not exists public.ntd_research_events (
 id bigint generated always as identity primary key,
 project_id text not null references public.ntd_research_projects(id) on delete cascade,
 actor uuid not null, action text not null, revision integer not null,
 at timestamptz not null default now()
);
alter table public.ntd_research_projects enable row level security;
alter table public.ntd_research_members enable row level security;
alter table public.ntd_research_events enable row level security;
-- Only the Python API writes research; it validates sources, claims and baselines.
revoke all on public.ntd_research_projects,public.ntd_research_members,public.ntd_research_events from anon,authenticated;
grant select on public.ntd_research_projects,public.ntd_research_members,public.ntd_research_events to authenticated;
grant all on public.ntd_research_projects,public.ntd_research_members,public.ntd_research_events to service_role;
grant usage,select on sequence public.ntd_research_events_id_seq to service_role;
drop policy if exists "Own research memberships" on public.ntd_research_members;
create policy "Own research memberships" on public.ntd_research_members for select to authenticated using(user_id=(select auth.uid()));
drop policy if exists "Project members read research" on public.ntd_research_projects;
create policy "Project members read research" on public.ntd_research_projects for select to authenticated using(exists(select 1 from public.ntd_research_members m where m.project_id=id and m.user_id=(select auth.uid())));
drop policy if exists "Project members read events" on public.ntd_research_events;
create policy "Project members read events" on public.ntd_research_events for select to authenticated using(exists(select 1 from public.ntd_research_members m where m.project_id=ntd_research_events.project_id and m.user_id=(select auth.uid())));
create or replace function public.ntd_research_create(actor uuid, document jsonb)
returns text language plpgsql security definer set search_path='' as $$
declare pid text:=document->>'id';
begin
 if not exists(select 1 from public.team_members where user_id=actor) then raise exception 'Team membership required' using errcode='42501'; end if;
 insert into public.ntd_research_projects(id,payload,revision,created_by) values(pid,document,1,actor);
 insert into public.ntd_research_members values(pid,actor,'owner');
 insert into public.ntd_research_events(project_id,actor,action,revision) values(pid,actor,'create',1);
 return pid;
end; $$;
create or replace function public.ntd_research_commit(actor uuid,pid text,expected_revision integer,document jsonb,operation text)
returns boolean language plpgsql security definer set search_path='' as $$
declare current_revision integer; member_role text;
begin
 select revision into current_revision from public.ntd_research_projects where id=pid for update;
 if not found then raise exception 'Project not found' using errcode='42501'; end if;
 select role into member_role from public.ntd_research_members where project_id=pid and user_id=actor for update;
 if member_role is null or member_role='viewer' then raise exception 'Write access required' using errcode='42501'; end if;
 if operation in ('review_evidence','review_claim','baseline','delete_source') and member_role not in ('owner','reviewer') then raise exception 'Reviewer access required' using errcode='42501'; end if;
 if current_revision<>expected_revision then return false; end if;
 if operation='delete_project' then
  if member_role<>'owner' then raise exception 'Owner access required' using errcode='42501'; end if;
  delete from public.ntd_research_projects where id=pid; return true;
 end if;
 if document->>'id' is distinct from pid or (document->>'revision')::int<>expected_revision+1 then raise exception 'Invalid revision'; end if;
 update public.ntd_research_projects set payload=document,revision=expected_revision+1,updated_at=now() where id=pid;
 insert into public.ntd_research_events(project_id,actor,action,revision) values(pid,actor,operation,expected_revision+1);
 return true;
end; $$;
-- Existing registered users can be assigned or revoked by a project's owner.
create or replace function public.ntd_research_member(actor uuid,pid text,member_email text,member_role text)
returns boolean language plpgsql security definer set search_path='' as $$
declare target uuid;
begin
 perform 1 from public.ntd_research_projects where id=pid for update;
 if not exists(select 1 from public.ntd_research_members where project_id=pid and user_id=actor and role='owner') then raise exception 'Owner access required' using errcode='42501'; end if;
 select id into target from auth.users where lower(email)=lower(trim(member_email));
 if target is null then raise exception 'Create this account in Supabase Authentication first'; end if;
 if target=actor then raise exception 'Your own owner access cannot be changed here'; end if;
 if member_role='revoke' then delete from public.ntd_research_members where project_id=pid and user_id=target;
 elsif member_role in ('researcher','reviewer','viewer') then
  insert into public.ntd_research_members values(pid,target,member_role) on conflict(project_id,user_id) do update set role=excluded.role;
 else raise exception 'Invalid member role'; end if;
 insert into public.ntd_research_events(project_id,actor,action,revision) select pid,actor,'membership:'||member_role,revision from public.ntd_research_projects where id=pid;
 return true;
end; $$;
revoke all on function public.ntd_research_create(uuid,jsonb),public.ntd_research_commit(uuid,text,integer,jsonb,text),public.ntd_research_member(uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.ntd_research_create(uuid,jsonb),public.ntd_research_commit(uuid,text,integer,jsonb,text),public.ntd_research_member(uuid,text,text,text) to service_role;
commit;
