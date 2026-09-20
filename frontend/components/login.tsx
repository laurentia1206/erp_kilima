'use client';
import { useState } from 'react';
import type { Bridge } from '../lib/runtime';

export function Login({ bridge, loadError }: { bridge: Bridge | null; loadError: string }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!bridge || busy) return;
    setBusy(true); setError('');
    try { await bridge.login(email.trim(), password); setPassword(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Connexion impossible.'); }
    finally { setBusy(false); }
  }
  return <div id="login">
    <div className="login-intro"><div className="brand-eyebrow">KILIMA HOLDINGS · ESPACE DE GESTION</div>
      <h2>Vos sociétés.<br />Une vision commune.</h2>
      <p>Les finances, les équipes et les opérations du groupe réunies dans votre espace de travail.</p>
      <div className="login-domains"><span>Finance & trésorerie</span><span>Commerce & stocks</span><span>Opérations & services</span></div>
      <div className="login-baseline">Un outil de travail au service de vos métiers.</div>
    </div>
    <div className="login-box"><div className="login-logo"><i className="ti ti-building-bank" aria-hidden="true" /></div>
      <h1>KILIMA HOLDINGS</h1><div className="sub">Système intégré de gestion — Connexion</div>
      <form onSubmit={submit} aria-busy={busy}>
        <div className="form-group"><label className="form-label" htmlFor="email">Email professionnel</label><input id="email" className="form-input" type="email" autoComplete="username" required value={email} onChange={event => setEmail(event.target.value)} /></div>
        <div className="form-group"><label className="form-label" htmlFor="password">Mot de passe</label><input id="password" className="form-input" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></div>
        <button className="btn btn-primary" id="btn-login" disabled={!bridge || busy}>{busy ? 'Connexion…' : 'Se connecter'}</button>
        <div className="err" id="login-err" role="alert">{error || loadError}</div>
        {!bridge && !loadError && <p className="next-login-state" role="status">Préparation de votre espace…</p>}
        {loadError && <button type="button" className="btn" onClick={() => location.reload()}>Recharger la page</button>}
      </form>
    </div>
  </div>;
}
