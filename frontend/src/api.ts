let accessToken:string|null=null;
let refreshInFlight:Promise<boolean>|null=null;
export function setToken(value:string|null){accessToken=value;}
export async function refresh():Promise<boolean>{
  if(!refreshInFlight)refreshInFlight=(async()=>{try{const r=await fetch('/api/v1/auth/refresh',{method:'POST',credentials:'same-origin'});if(!r.ok){accessToken=null;return false;}accessToken=(await r.json()).access_token;return true;}catch{return false;}finally{refreshInFlight=null;}})();
  return refreshInFlight;
}
export async function api<T>(path:string,options:RequestInit={},tenant?:string,retry=true):Promise<T>{
  const r=await fetch('/api/v1'+path,{...options,credentials:'same-origin',headers:{'Content-Type':'application/json',...(accessToken?{Authorization:'Bearer '+accessToken}:{}),...(tenant?{'X-Tenant-ID':tenant}:{}),...options.headers}});
  if(r.status===401 && retry && !['/auth/login','/auth/register','/auth/refresh'].includes(path) && await refresh())return api<T>(path,options,tenant,false);
  if(!r.ok){const body=await r.json().catch(()=>({}));throw new Error(body.error?.message||body.detail||'Request failed. Please try again.');}
  return r.status===204?undefined as T:r.json();
}
