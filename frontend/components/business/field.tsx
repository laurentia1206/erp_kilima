import type { InputHTMLAttributes } from 'react';
export function Field({ label, value, onChange, ...attributes }: Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> & { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="business-field">{label}<input className="form-input" {...attributes} value={value} onChange={event => onChange(event.target.value)} /></label>;
}
