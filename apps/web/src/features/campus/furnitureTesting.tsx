import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';

import { EMPTY_FURNITURE, type Furniture } from './furniture';

/**
 * Tests only: a query client that already holds `furniture.json`, so
 * components reading the terrain render without a request.
 */
export function FurnitureProvider({
  furniture = EMPTY_FURNITURE,
  children,
}: {
  furniture?: Furniture;
  children: ReactNode;
}) {
  const [client] = useState(() => {
    const queries = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queries.setQueryData(['furniture'], furniture);
    return queries;
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
