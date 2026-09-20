'use client';
export default function ErrorPage({ reset }: { reset: () => void }) {
  return <main className="startup-error" role="alert"><h1>Votre espace n’a pas pu s’ouvrir</h1><p>Réessayez de charger la page.</p><button className="btn btn-primary" onClick={reset}>Réessayer</button></main>;
}
