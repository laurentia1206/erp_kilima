import type { InputHTMLAttributes } from 'react';
export function Field({ label, value, onChange, className, ...attributes }: Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> & { label: string; value: string; onChange: (value: string) => void; className?: string }) {
  return <label className={`business-field${className ? ` ${className}` : ''}`}>{label}<input className="form-input" {...attributes} value={value} onInput={['date', 'month', 'datetime-local', 'time'].includes(attributes.type || '') ? event => onChange(event.currentTarget.value) : undefined} onChange={event => onChange(event.target.value)} /></label>;
}
