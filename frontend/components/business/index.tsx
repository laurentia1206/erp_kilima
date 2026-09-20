'use client';
import { Audit } from './audit';
import { Rates } from './rates';
import { Stock } from './stock';
import { Tasks } from './tasks';
import { Articles } from './articles';
import { Rooms } from './rooms';
import type { ScreenProps } from './shared';

export const BUSINESS_VIEWS = ['pilotage', 'audit', 'stock', 'taux', 'articles', 'hotel-chambres'];
export function BusinessScreen(props: ScreenProps) {
  switch (props.state.view) {
    case 'pilotage': return <Tasks {...props} />;
    case 'audit': return <Audit {...props} />;
    case 'stock': return <Stock {...props} />;
    case 'taux': return <Rates {...props} />;
    case 'articles': return <Articles {...props} />;
    case 'hotel-chambres': return <Rooms {...props} />;
    default: return null;
  }
}
