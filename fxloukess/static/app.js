function getCookie(name){return document.cookie.split('; ').find(row=>row.startsWith(name+'='))?.split('=')[1]||''}
function authHeaders(extra={}){const token=localStorage.getItem('token');const headers={'Content-Type':'application/json',...extra};if(token&&token!=='undefined'&&token!=='null')headers.Authorization='Bearer '+token;const csrf=getCookie('csrf_token');if(csrf)headers['X-CSRF-Token']=decodeURIComponent(csrf);return headers}
function sessionExpired(){localStorage.clear();location.replace('/session-expired')}
function logoutToLogin(){localStorage.clear();location.replace('/login')}
function copyText(text){navigator.clipboard?.writeText(text).then(()=>window.toast?.('Lien copié')||alert('Copié')).catch(()=>prompt('Copiez le lien',text))}
