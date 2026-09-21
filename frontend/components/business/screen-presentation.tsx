'use client';
import { createContext, useContext, type ReactNode } from 'react';
import type { Snapshot } from '../../lib/runtime';

const ScreenIcon = createContext('ti-layout-dashboard');
export function ScreenPresentation({state, children}: {state: Snapshot; children: ReactNode}) {
  const icon = state.groups.flatMap(group => group.items).find(item => item.view === state.view)?.icon || 'ti-layout-dashboard';
  return <ScreenIcon.Provider value={icon}><div className="native-workspace tw:min-w-0" data-business-view={state.view}>{children}</div></ScreenIcon.Provider>;
}
export function ScreenTitle({children}: {children: ReactNode}) {
  const icon = useContext(ScreenIcon);
  return <h2 className="screen-title"><i className={`ti ${icon}`} aria-hidden="true" />{children}</h2>;
}
