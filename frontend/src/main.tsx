import React,{useState,useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient,QueryClientProvider,useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {Store,LayoutDashboard,GitBranch,Users,ShieldCheck,LogOut,Plus,ArrowUpRight,Check,Cloud,Activity} from 'lucide-react';
import {Button} from './components/ui/button';
import {api,setToken,refresh} from './api';
import './style.css';
import {Billing,BillingAdmin} from './features/Billing';
const client=new QueryClient({defaultOptions:{queries:{retry:false,refetchOnWindowFocus:false}}});
type User={id:string;email:string;platform_admin:boolean};
type Tenant={id:string;name:string;status:string;role?:string};
type Branch={id:string;name:string};
type Member={id:string;email:string;role:string;active:boolean};
const schema=z.object({email:z.email(),password:z.string().min(12,'Use at least 12 characters').max(128)});
function ErrorBox({error}:{error:unknown}){return error?<div className="error" role="alert">{error instanceof Error?error.message:'Something went wrong'}</div>:null;}
function Login({done}:{done:()=>void}){
 const[register,setRegister]=useState(false);const form=useForm<z.infer<typeof schema>>({resolver:zodResolver(schema)});
 const mutation=useMutation({mutationFn:(body:z.infer<typeof schema>)=>api<{access_token:string}>(register?'/auth/register':'/auth/login',{method:'POST',body:JSON.stringify(body)}),onSuccess:r=>{setToken(r.access_token);done();}});
 return <main className="login"><div className="intro"><div className="brand"><Store/> SmartRetail <span>CLOUD</span></div><div><span className="eyebrow">A HOME FOR YOUR BUSINESS</span><h1>Small beginnings.<br/>Room to grow.</h1><p>Bring your branches and your team together in one thoughtfully organized workspace.</p><div className="intro-note"><ShieldCheck/> Separate workspaces. Access you control.</div></div><small>SmartRetail Cloud · Foundation release</small></div><section className="login-panel"><div className="form-wrap"><span className="eyebrow">YOUR NEXT CHAPTER</span><h2>{register?'Create your account':'Welcome back'}</h2><p>{register?'Start with your account. Set up your business next.':'Sign in to your business workspace.'}</p><form onSubmit={form.handleSubmit(v=>mutation.mutate(v))}><label>Email address<input type="email" autoComplete="email" {...form.register('email')}/></label><label>Password<input type="password" autoComplete={register?'new-password':'current-password'} {...form.register('password')}/></label>{Object.values(form.formState.errors).map((e,i)=><small className="error-text" key={i}>{e.message}</small>)}<ErrorBox error={mutation.error}/><Button disabled={mutation.isPending} type="submit">{mutation.isPending?'Please wait…':register?'Create account':'Sign in'}<ArrowUpRight size={16}/></Button></form><button className="text-button" onClick={()=>{setRegister(!register);mutation.reset();}}>{register?'Already registered? Sign in':'New here? Create an account'}</button><p className="note">Development foundation. Subscription billing is available. Retail sales arrive in Milestone 3.</p></div></section></main>;
}
function App(){
 const[ready,setReady]=useState(false);const[signed,setSigned]=useState(false);const[tenantId,setTenantId]=useState('');const[page,setPage]=useState('Overview');
 const cache=useQueryClient();
 useEffect(()=>{refresh().then(ok=>{setSigned(ok);setReady(true);});},[]);
 const me=useQuery({queryKey:['me',signed],queryFn:()=>api<User>('/auth/me'),enabled:signed});
 const tenants=useQuery({queryKey:['tenants',signed],queryFn:()=>api<Tenant[]>('/tenants'),enabled:signed});
 useEffect(()=>{if(tenants.data?.length && !tenantId)setTenantId(tenants.data[0].id);},[tenants.data,tenantId]);
 const logout=useMutation({mutationFn:()=>api('/auth/logout',{method:'POST'}),onSuccess:()=>{setToken(null);setSigned(false);setTenantId('');cache.clear();}});
 if(!ready)return <main className="loading">Opening your workspace…</main>;
 if(!signed)return <Login done={()=>{cache.clear();setSigned(true);}}/>;
 const selected=tenants.data?.find(t=>t.id===tenantId);
 return <div className="shell"><aside><div className="brand"><Store/> SmartRetail <span>CLOUD</span></div><label className="switcher">BUSINESS WORKSPACE<select value={tenantId} onChange={e=>{setTenantId(e.target.value);setPage('Overview');}}><option value="">Select a business</option>{tenants.data?.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</select></label><div className="nav-label">WORKSPACE</div><nav>{[['Overview',LayoutDashboard],['Branches',GitBranch],['Team',Users],['Audit trail',Activity],['Subscription',Cloud],...(me.data?.platform_admin?[['Platform',ShieldCheck]]:[])].map(([label,Icon])=>{const I=Icon as typeof Store;return <button key={String(label)} className={page===label?'active':''} onClick={()=>setPage(String(label))}><I size={18}/>{String(label)}</button>;})}</nav><div className="aside-bottom"><Cloud size={20}/><strong>Built for your next step</strong><p>Your foundation for connected retail.</p><span>SUBSCRIPTIONS · v0.2</span></div></aside><div className="workspace"><header><span>Workspace <span className="slash">/</span> <strong>{page}</strong></span><div className="account"><span>{me.data?.email}</span><Button variant="outline" size="sm" disabled={logout.isPending} onClick={()=>logout.mutate()} aria-label="Sign out"><LogOut size={15}/></Button></div></header><main className="content"><ErrorBox error={me.error||tenants.error||logout.error}/><div className="page-heading"><div><span className="eyebrow">SMARTRETAIL CLOUD</span><h1>{page==='Overview'?'Your business, together.':page}</h1><p>{selected?.name||'Create a workspace to get started.'} {selected&&<span className="badge">{selected.status}</span>}</p></div><div className="secure"><ShieldCheck size={16}/> Membership verified by server</div></div>{page==='Platform'?<><Platform/><BillingAdmin/></>:<>{page==='Overview'&&<Overview tenant={selected}/>} {page==='Branches'&&<Branches tenant={selected}/>} {page==='Team'&&<Team tenant={selected}/>} {page==='Audit trail'&&<Audit tenant={selected}/>} {page==='Subscription'&&<Billing tenant={selected}/>}</>}</main><footer>SmartRetail Cloud <span>One workspace. A stronger foundation.</span></footer></div></div>;
}
function Overview({tenant}:{tenant?:Tenant}){
 const cache=useQueryClient();const[name,setName]=useState('');const[key,setKey]=useState(()=>crypto.randomUUID());
 const create=useMutation({mutationFn:()=>api('/tenants',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({name})}),onSuccess:()=>{cache.invalidateQueries({queryKey:['tenants']});setName('');setKey(crypto.randomUUID());}});
 return <><div className="welcome-card"><div><span className="eyebrow">MAKE IT YOURS</span><h2>A good start for<br/>your growing business.</h2><p>Set up your branches, give your team the right access, and keep a clear record of changes.</p></div><div className="store-art" aria-hidden="true"><Store size={106} strokeWidth={1}/><span className="art-pill"><Check size={14}/> Workspace connected</span></div></div><div className="grid-two"><section className="panel"><div className="panel-title"><h3>Workspace essentials</h3><span className="muted">Milestone 01</span></div>{[['01','Your business workspace',tenant?.name||'Create a business below'],['02','Branches & locations','Organize where your team works'],['03','People & permissions','Owner, manager and cashier access']].map(([n,t,d])=><div className="checklist" key={n}><span>{n}</span><div><strong>{t}</strong><p>{d}</p></div><ArrowUpRight size={17}/></div>)}</section><section className="panel"><h3>Create a business</h3><p className="muted">Each business has its own branches, members and audit history.</p><form onSubmit={e=>{e.preventDefault();create.mutate();}}><label>Business name<input required maxLength={100} value={name} onChange={e=>{setName(e.target.value);setKey(crypto.randomUUID());}} placeholder="e.g. Lotus Retail"/></label><Button disabled={create.isPending||!name.trim()}><Plus size={16}/>{create.isPending?'Creating…':'Create workspace'}</Button><ErrorBox error={create.error}/>{create.isSuccess&&<p role="status">Business created. Select it from the workspace menu.</p>}</form></section></div></>;
}
function Branches({tenant}:{tenant?:Tenant}){
 const cache=useQueryClient();const[name,setName]=useState('');
 const q=useQuery({queryKey:['branches',tenant?.id],queryFn:()=>api<Branch[]>('/branches',{},tenant?.id),enabled:!!tenant});
 const create=useMutation({mutationFn:()=>api('/branches',{method:'POST',body:JSON.stringify({name})},tenant?.id),onSuccess:()=>{cache.invalidateQueries({queryKey:['branches',tenant?.id]});setName('');}});
 if(!tenant)return <Empty/>;
 return <section className="panel"><h3>Your locations</h3><ErrorBox error={q.error||create.error}/>{q.isPending?<p>Loading branches…</p>:<div className="branch-grid">{q.data?.map(b=><div className="branch-card" key={b.id}><GitBranch/><h3>{b.name}</h3><span className="badge">Connected workspace</span></div>)}</div>}{tenant.role!=='cashier'&&<form className="inline-form" onSubmit={e=>{e.preventDefault();create.mutate();}}><label>New branch<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)} placeholder="Branch name"/></label><Button disabled={create.isPending||!name.trim()}><Plus size={16}/>Add branch</Button></form>}</section>;
}
function Team({tenant}:{tenant?:Tenant}){
 const cache=useQueryClient();const[email,setEmail]=useState('');const[role,setRole]=useState('cashier');
 const q=useQuery({queryKey:['members',tenant?.id],queryFn:()=>api<Member[]>('/members',{},tenant?.id),enabled:tenant?.role==='owner'});
 const add=useMutation({mutationFn:()=>api('/members',{method:'POST',body:JSON.stringify({email,role})},tenant?.id),onSuccess:()=>{cache.invalidateQueries({queryKey:['members',tenant?.id]});setEmail('');}});
 const revoke=useMutation({mutationFn:(id:string)=>api('/members/'+id,{method:'DELETE'},tenant?.id),onSuccess:()=>cache.invalidateQueries({queryKey:['members',tenant?.id]})});
 if(!tenant)return <Empty/>;if(tenant.role!=='owner')return <section className="panel">Only business owners can manage members.</section>;
 return <section className="panel"><h3>People with access</h3><p className="muted">Add an existing registered account. Email invitations are planned for a later milestone.</p><ErrorBox error={q.error||add.error||revoke.error}/>{q.isPending?<p>Loading team…</p>:<div className="table-wrap"><table><thead><tr><th>Member</th><th>Role</th><th>Status</th><th>Access</th></tr></thead><tbody>{q.data?.map(m=><tr key={m.id}><td>{m.email}</td><td>{m.role}</td><td>{m.active?'Active':'Revoked'}</td><td>{m.active&&m.role!=='owner'&&<Button variant="outline" size="sm" disabled={revoke.isPending} onClick={()=>revoke.mutate(m.id)}>Revoke access</Button>}</td></tr>)}</tbody></table></div>}<form className="inline-form" onSubmit={e=>{e.preventDefault();add.mutate();}}><label>Email<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Role<select value={role} onChange={e=>setRole(e.target.value)}><option value="cashier">Cashier</option><option value="manager">Manager</option></select></label><Button disabled={add.isPending}>Add member</Button></form></section>;
}
function Audit({tenant}:{tenant?:Tenant}){
 const q=useQuery({queryKey:['audit',tenant?.id],queryFn:()=>api<{id:string;action:string;created_at:string}[]>('/audit',{},tenant?.id),enabled:tenant?.role==='owner'});
 if(!tenant)return <Empty/>;if(tenant.role!=='owner')return <section className="panel">Audit history is available to business owners.</section>;
 return <section className="panel"><h3>Recent workspace activity</h3><ErrorBox error={q.error}/>{q.isPending?<p>Loading activity…</p>:q.data?.length?q.data.map(a=><div className="checklist" key={a.id}><Activity size={18}/><strong>{a.action.replaceAll('.',' · ')}</strong><time>{new Date(a.created_at).toLocaleString()}</time></div>):<p>No recorded activity yet.</p>}</section>;
}
function Platform(){
 const cache=useQueryClient();const q=useQuery({queryKey:['platform'],queryFn:()=>api<Tenant[]>('/platform/tenants')});
 const update=useMutation({mutationFn:(t:Tenant)=>api('/platform/tenants/'+t.id,{method:'PATCH',body:JSON.stringify({status:t.status==='active'?'suspended':'active'})}),onSuccess:()=>{cache.invalidateQueries({queryKey:['platform']});cache.invalidateQueries({queryKey:['tenants']});}});
 return <section className="panel"><h3>Platform businesses</h3><p className="muted">Administrative metadata only. Business data requires an authorized tenant membership.</p><ErrorBox error={q.error||update.error}/>{q.isPending?<p>Loading businesses…</p>:q.data?.length?<div className="table-wrap"><table><thead><tr><th>Business</th><th>Status</th><th>Action</th></tr></thead><tbody>{q.data.map(t=><tr key={t.id}><td>{t.name}</td><td>{t.status}</td><td><Button variant="outline" size="sm" disabled={update.isPending} onClick={()=>update.mutate(t)}>{t.status==='active'?'Suspend':'Reactivate'}</Button></td></tr>)}</tbody></table></div>:<p>No businesses yet.</p>}</section>;
}
function Empty(){return <section className="panel">Select or create a business from Overview to continue.</section>;}
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><App/></QueryClientProvider></React.StrictMode>);
