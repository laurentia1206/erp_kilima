'use client';
import { useEffect, useRef, useState } from 'react';
import { loadRuntime, type Bridge, type Snapshot } from '../lib/runtime';
import { VIEWS } from '../lib/views';
import { Login } from './login';
import { Home } from './home';
import { BusinessScreen, BUSINESS_VIEWS } from './business';

const EMPTY: Snapshot = { user: null, companies: [], companyId: null, view: 'accueil', title: 'Accueil', subtitle: '', groups: [] };
const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
export function ERP() {
  const [state, setState] = useState<Snapshot>(EMPTY);
  const [bridge, setBridge] = useState<Bridge | null>(null);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [openGroup, setOpenGroup] = useState<string | null>('Pilotage');
  const [mobile, setMobile] = useState(false);
  const [smallScreen, setSmallScreen] = useState(false);
  const [offline, setOffline] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLElement>(null);
  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [state.view, state.companyId, state.user?.id]);
  useEffect(() => {
    let alive = true;
    const update = (event: Event) => {
      const next = (event as CustomEvent<Snapshot>).detail;
      if (!alive) return;
      setState(next);
      if (next.navigated) {
        setSearch(''); setMobile(false);
        setOpenGroup(previous => next.groups.find(group => group.name === (next.preferredGroup || previous) && group.items.some(item => item.view === next.view))?.name || next.groups.find(group => group.items.some(item => item.view === next.view))?.name || null);
      }
    };
    window.addEventListener('kilima:state', update);
    loadRuntime().then(runtime => {
      if (!alive) return;
      const current = runtime.snapshot();
      setBridge(runtime); setState(current);
      setOpenGroup(current.groups.find(group => group.items.some(item => item.view === current.view))?.name || 'Pilotage');
      requestAnimationFrame(() => { if (alive) void runtime.restore(); });
    }).catch(error => { if (alive) setLoadError(error.message); });
    return () => { alive = false; window.removeEventListener('kilima:state', update); };
  }, []);
  useEffect(() => {
    const query = window.matchMedia('(max-width:760px)');
    const resize = () => { setSmallScreen(query.matches); setMobile(false); };
    const connection = () => setOffline(!navigator.onLine);
    resize(); connection();
    query.addEventListener('change', resize);
    window.addEventListener('online', connection); window.addEventListener('offline', connection);
    return () => { query.removeEventListener('change', resize); window.removeEventListener('online', connection); window.removeEventListener('offline', connection); };
  }, []);
  useEffect(() => {
    document.body.classList.toggle('menu-open', mobile);
    return () => document.body.classList.remove('menu-open');
  }, [mobile]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && state.user) { event.preventDefault(); setMobile(true); setTimeout(() => searchRef.current?.focus(), 0); }
      if (event.key === 'Escape') setMobile(false);
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [state.user]);
  const terms = normalize(search).trim().split(/\s+/).filter(Boolean);
  const groups = state.groups.map(group => ({ ...group, items: group.items.filter(item => terms.every(term => normalize(group.name + ' ' + item.label).includes(term))) })).filter(group => group.items.length);
  const shownGroup = search && !groups.some(group => group.name === openGroup) ? groups[0]?.name : openGroup;
  return <>
    {!state.user ? <Login bridge={bridge} loadError={loadError} /> : <div id="login" className="hidden"><input id="password" type="hidden" /></div>}
    <div id="app" className={`app${state.user ? '' : ' hidden'}`}>
      <a className="skip-link" href="#main-content">Aller au contenu</a>
      <button id="sidebar-backdrop" className={`sidebar-backdrop${mobile ? '' : ' hidden'}`} aria-label="Fermer le menu" onClick={() => setMobile(false)} />
      <aside id="sidebar" className="sidebar" aria-label="Navigation principale" inert={smallScreen && !mobile}>
        <div className="sidebar-logo"><div className="logo-icon"><i className="ti ti-building-bank" aria-hidden="true" /></div><div><div className="logo-title">KILIMA HOLDINGS</div><div className="logo-sub">Espace de gestion du groupe</div></div></div>
        <div className="nav-search-wrap"><label htmlFor="nav-search" className="sr-only">Rechercher un module</label><input id="nav-search" ref={searchRef} type="search" placeholder="Rechercher un module…" autoComplete="off" value={search} onChange={event => setSearch(event.target.value)} /><kbd>Ctrl K</kbd></div>
        <nav id="sidebar-nav" aria-label="Modules">{groups.map(group => <div key={group.name} className={`nav-group${shownGroup === group.name ? '' : ' collapsed'}`}>
          <button type="button" className="nav-group-hdr" data-toggle={group.name} aria-expanded={shownGroup === group.name} onClick={() => setOpenGroup(shownGroup === group.name ? null : group.name)}>{group.name}<i className="ti ti-chevron-down chev" aria-hidden="true" /></button>
          <div className="nav-children">{group.items.map(item => <button key={item.view} type="button" className={`nav-item${state.view === item.view && shownGroup === group.name ? ' active' : ''}`} data-view={item.view} aria-current={state.view === item.view && shownGroup === group.name ? 'page' : undefined} onClick={() => bridge?.navigate(item.view, group.name)}><i className={`ti ${item.icon}`} aria-hidden="true" /> {item.label}{item.badge && <span className="nav-badge hidden" data-badge={item.badge} />}</button>)}</div>
        </div>)}</nav>
        <div id="nav-empty" className={`nav-empty${groups.length ? ' hidden' : ''}`}>Aucun module trouvé.</div>
        <div className="sidebar-footer"><span className="status-dot" /> Finance · Commerce · Opérations</div>
      </aside>
      <div className="main"><header className="topbar">
        <button className="btn menu-toggle" id="btn-menu" aria-label="Ouvrir le menu" aria-controls="sidebar" aria-expanded={mobile} onClick={() => setMobile(value => !value)}>☰</button>
        <div className="topbar-left"><h1 id="page-title">{state.title}</h1><p id="page-sub">{state.subtitle}</p></div>
        <div className="topbar-right">
          <button id="pilotage-alertes" className={`btn btn-sm${state.user?.super_administrateur ? ' hidden' : ''}`} onClick={() => bridge?.navigate('pilotage')}>Suivi des tâches</button>
          <select id="societe-select" className={`form-select${state.user?.super_administrateur ? ' hidden' : ''}`} aria-label="Société active" style={{ width: 'auto' }} value={state.companyId || ''} onChange={event => { const id = event.target.value; event.target.value = state.companyId || ''; void bridge?.selectCompany(id); }}>{state.companies.map(company => <option key={company.id} value={company.id}>{company.nom}</option>)}</select>
          <div className="who"><span className="nm" id="who-nm">{[state.user?.nom, state.user?.prenom].filter(Boolean).join(' ')}</span><span className="em" id="who-em">{state.user?.email}</span></div>
          <div className="avatar" id="avatar">{state.user?.nom?.slice(0, 1).toUpperCase() || '?'}</div>
          <button id="btn-logout" className="btn btn-sm" aria-label="Se déconnecter" title="Se déconnecter" onClick={() => { bridge?.logout(); setMobile(false); }}><i className="ti ti-logout" aria-hidden="true" /></button>
        </div>
      </header>
      <div id="connection-banner" className={`connection-banner${offline ? '' : ' hidden'}`} role="status">{offline && 'Connexion interrompue. Conservez vos saisies et vérifiez la connexion avant de valider.'}</div>
      <main ref={contentRef} id="main-content" className="content" tabIndex={-1}>{VIEWS.map(view => <div key={view} id={`view-${view}`} className={`view${state.view === view ? ' active' : ''}`} data-react-owned={view === 'accueil' || BUSINESS_VIEWS.includes(view) ? 'true' : undefined}>{state.view === view && state.user && bridge ? view === 'accueil' && !state.user.super_administrateur ? <Home key={state.companyId} state={state} bridge={bridge} /> : BUSINESS_VIEWS.includes(view) ? <BusinessScreen key={`${state.user.id}:${state.companyId}:${view}`} state={state} bridge={bridge} /> : null : null}</div>)}</main>
      </div>
    </div>
    <div id="modal-root" /><div id="react-modal-root" /><div className="toast" id="toast" role="status" aria-live="polite" />
  </>;
}
